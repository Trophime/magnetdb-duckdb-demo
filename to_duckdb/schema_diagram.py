#!/usr/bin/env python3
"""
schema_diagram.py
=================
Prints a text summary and/or renders a graphical ER diagram of the MagnetDB
DuckDB schema.

Usage
-----
    python schema_diagram.py [--db PATH] [--output PATH] [--text]

Options
-------
--db PATH      DuckDB file to introspect  (default: magnetdb.duckdb in CWD).
               If the file is not found, the schema is read from schema.py.
--output PATH  Save diagram to this file instead of opening a window
               (PNG / SVG / PDF; format inferred from extension).
               Default output name: schema_diagram.png
--text         Print a plain-text schema summary to stdout and exit.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Column:
    name: str
    dtype: str
    is_pk: bool = False
    fk_table: str | None = None


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    pk_columns: list[str] = field(default_factory=list)


@dataclass
class ForeignKey:
    src_table: str
    src_col: str
    dst_table: str
    dst_col: str


# ── Schema loading ─────────────────────────────────────────────────────────────

def _load_from_db(db_path: str) -> tuple[list[Table], list[ForeignKey]]:
    import duckdb
    con = duckdb.connect(db_path, read_only=True)

    table_names: list[str] = [
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
    ]

    # Primary keys
    pk_map: dict[str, list[str]] = {}
    for tname, col_names in con.execute(
        "SELECT table_name, constraint_column_names "
        "FROM duckdb_constraints() "
        "WHERE constraint_type = 'PRIMARY KEY' AND schema_name = 'main'"
    ).fetchall():
        pk_map[tname] = col_names

    # Foreign keys  (constraint_text = "FOREIGN KEY (col) REFERENCES tbl(col)")
    fks: list[ForeignKey] = []
    for tname, text in con.execute(
        "SELECT table_name, constraint_text "
        "FROM duckdb_constraints() "
        "WHERE constraint_type = 'FOREIGN KEY' AND schema_name = 'main'"
    ).fetchall():
        m = re.match(r"FOREIGN KEY \((\w+)\) REFERENCES (\w+)\((\w+)\)", text or "")
        if m:
            fks.append(ForeignKey(tname, m.group(1), m.group(2), m.group(3)))

    # Columns
    fk_lookup: dict[str, dict[str, str]] = {}
    for fk in fks:
        fk_lookup.setdefault(fk.src_table, {})[fk.src_col] = fk.dst_table

    tables: list[Table] = []
    for tname in table_names:
        rows = con.execute(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? "
            "ORDER BY ordinal_position",
            [tname],
        ).fetchall()
        pk_cols = pk_map.get(tname, [])
        columns = [
            Column(
                name=cname,
                dtype=dtype,
                is_pk=(cname in pk_cols),
                fk_table=fk_lookup.get(tname, {}).get(cname),
            )
            for cname, dtype in rows
        ]
        tables.append(Table(name=tname, columns=columns, pk_columns=pk_cols))

    con.close()
    return tables, fks


def _load_from_sql() -> tuple[list[Table], list[ForeignKey]]:
    sys.path.insert(0, str(Path(__file__).parent))
    from schema import SCHEMA_SQL  # noqa: PLC0415

    tables: list[Table] = []
    fks: list[ForeignKey] = []

    for m in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);",
        SCHEMA_SQL,
        re.DOTALL,
    ):
        tname = m.group(1)
        body = m.group(2)

        columns: list[Column] = []
        composite_pk: list[str] = []
        inline_pks: list[str] = []

        for raw in body.splitlines():
            line = raw.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue

            cpk = re.match(r"PRIMARY KEY\s*\((.+)\)", line)
            if cpk:
                composite_pk = [c.strip() for c in cpk.group(1).split(",")]
                continue

            cm = re.match(r"(\w+)\s+([\w\[\]()]+(?:\([^)]*\))?)", line)
            if not cm:
                continue
            cname, dtype = cm.group(1), cm.group(2)
            if cname.upper() in ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"):
                continue

            is_pk = bool(re.search(r"\bPRIMARY KEY\b", line))
            if is_pk:
                inline_pks.append(cname)

            ref = re.search(r"REFERENCES\s+(\w+)\((\w+)\)", line)
            if ref:
                fks.append(ForeignKey(tname, cname, ref.group(1), ref.group(2)))

            columns.append(Column(
                name=cname,
                dtype=dtype,
                is_pk=is_pk,
                fk_table=ref.group(1) if ref else None,
            ))

        pk_cols = composite_pk or inline_pks
        tables.append(Table(name=tname, columns=columns, pk_columns=pk_cols))

    return tables, fks


def load_schema(db_path: str | None) -> tuple[list[Table], list[ForeignKey], str]:
    if db_path and Path(db_path).exists():
        return *_load_from_db(db_path), f"live DB: {db_path}"
    fallback = str(Path(__file__).parent / "magnetdb.duckdb")
    if Path(fallback).exists():
        return *_load_from_db(fallback), f"live DB: {fallback}"
    return *_load_from_sql(), "schema.py (no DB file found)"


# ── Text output ───────────────────────────────────────────────────────────────

def print_text(tables: list[Table], fks: list[ForeignKey]) -> None:
    print(f"MagnetDB DuckDB schema  —  {len(tables)} tables, {len(fks)} FK relationships")
    print("=" * 72)
    for t in tables:
        print(f"\n  [{t.name}]")
        pk_set = set(t.pk_columns)
        for c in t.columns:
            flags: list[str] = []
            if c.is_pk or c.name in pk_set:
                flags.append("PK")
            if c.fk_table:
                flags.append(f"→ {c.fk_table}")
            tag = f"  [{', '.join(flags)}]" if flags else ""
            print(f"    {c.name:<36} {c.dtype:<22}{tag}")
    print("\n" + "=" * 72)
    print("Foreign-key relationships:")
    for fk in fks:
        print(f"  {fk.src_table}.{fk.src_col:<28}  →  {fk.dst_table}.{fk.dst_col}")


# ── Diagram layout ────────────────────────────────────────────────────────────

# (cx, cy) = top-centre of each table box in data units.
# Rows are spaced ~3.2 units apart; columns ~4.5 units apart.
_POSITIONS: dict[str, tuple[float, float]] = {
    # ── row 0: reference / root ───────────────────────────────────────────────
    "materials":                 ( 0.0,  9.6),
    "housing_config":            ( 9.0,  9.6),
    # ── row 1: core assembly ─────────────────────────────────────────────────
    "parts":                     ( 0.0,  6.4),
    "magnets":                   ( 4.5,  6.4),
    "sites":                     ( 9.0,  6.4),
    # ── row 2: junction tables ────────────────────────────────────────────────
    "magnet_parts":              ( 2.25, 3.2),
    "site_magnets":              ( 6.75, 3.2),
    # ── row 3: data / operational ────────────────────────────────────────────
    "experiments":               ( 0.0,  0.0),
    "operationaldata":           ( 4.5,  0.0),
    "overview_records":          ( 9.5,  0.0),
    # ── row 4: idempotency guards ────────────────────────────────────────────
    "exp_stats_processed":       ( 0.0, -3.2),
    "op_stats_processed":        ( 4.5, -3.2),
    "hoop_stress_processed":     ( 9.0, -3.2),
    # ── row 5: per-run scalars ───────────────────────────────────────────────
    "exp_run_scalars":           (-2.5, -6.4),
    "op_run_scalars":            ( 2.0, -6.4),
    # ── row 6: per-bin stats ─────────────────────────────────────────────────
    "exp_site_bin_stats":        (-3.5, -9.6),
    "exp_part_bin_stats":        ( 0.0, -9.6),
    "op_site_bin_stats":         ( 3.5, -9.6),
    "op_part_bin_stats":         ( 6.5, -9.6),
    "hoop_stress_bin_stats":     ( 9.5, -9.6),
    "hoop_stress_fatigue":       (12.5, -9.6),
}

_COLORS: dict[str, str] = {
    # reference
    "materials":            "#d4edda",
    "housing_config":       "#d4edda",
    # assembly
    "parts":                "#cce5ff",
    "magnets":              "#cce5ff",
    "sites":                "#cce5ff",
    "magnet_parts":         "#cce5ff",
    "site_magnets":         "#cce5ff",
    # data
    "experiments":          "#fff3cd",
    "operationaldata":      "#fff3cd",
    "overview_records":     "#fff3cd",
}
_DEFAULT_COLOR = "#f8d7da"  # statistics tables

_MAX_COLS = 7        # show at most this many column rows per box
_TABLE_W  = 2.9      # box width in data units
_ROW_H    = 0.27     # height per column row
_HEADER_H = 0.38     # height of table-name header strip


def _box_height(ncols: int) -> float:
    visible = min(ncols, _MAX_COLS + 1)  # +1 for the "… N more" row if needed
    return _HEADER_H + visible * _ROW_H


def _box_rect(cx: float, cy: float, ncols: int) -> tuple[float, float, float, float]:
    """Return (x0, y0, w, h) where (cx, cy) is the top-centre."""
    h = _box_height(ncols)
    return cx - _TABLE_W / 2, cy - h, _TABLE_W, h


def _centre(cx: float, cy: float, ncols: int) -> tuple[float, float]:
    h = _box_height(ncols)
    return cx, cy - h / 2


def draw_diagram(
    tables: list[Table],
    fks: list[ForeignKey],
    output: str | None,
) -> None:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    tmap = {t.name: t for t in tables}
    ncols_map = {t.name: len(t.columns) for t in tables}

    # ── figure bounds ─────────────────────────────────────────────────────────
    xs = [cx for tname, (cx, cy) in _POSITIONS.items() if tname in tmap]
    ys = [cy for tname, (cx, cy) in _POSITIONS.items() if tname in tmap]
    margin = 1.5
    x0_fig = min(xs) - _TABLE_W / 2 - margin
    x1_fig = max(xs) + _TABLE_W / 2 + margin
    y0_fig = min(ys) - max(_box_height(ncols_map.get(t, 1)) for t in _POSITIONS) - margin
    y1_fig = max(ys) + margin

    fig_w = (x1_fig - x0_fig) * 1.1
    fig_h = (y1_fig - y0_fig) * 1.1
    fig, ax = plt.subplots(figsize=(max(fig_w, 20), max(fig_h, 16)))
    ax.set_xlim(x0_fig, x1_fig)
    ax.set_ylim(y0_fig, y1_fig)
    ax.axis("off")
    ax.set_title(
        "MagnetDB DuckDB — Entity Relationship Diagram",
        fontsize=13, fontweight="bold", pad=10,
    )

    # ── pre-compute box centres for FK arrows ─────────────────────────────────
    centres: dict[str, tuple[float, float]] = {}
    for tname, (cx, cy) in _POSITIONS.items():
        if tname in tmap:
            centres[tname] = _centre(cx, cy, ncols_map[tname])

    # ── FK arrows (drawn first, underneath boxes) ─────────────────────────────
    # Structural FKs (darker) vs stats FKs (lighter)
    _stats_tables = {
        "op_stats_processed", "exp_stats_processed", "hoop_stress_processed",
        "op_run_scalars", "exp_run_scalars",
        "op_site_bin_stats", "op_part_bin_stats",
        "exp_site_bin_stats", "exp_part_bin_stats",
        "hoop_stress_bin_stats", "hoop_stress_fatigue",
    }

    for fk in fks:
        if fk.src_table not in centres or fk.dst_table not in centres:
            continue
        is_stats = fk.src_table in _stats_tables
        ax.annotate(
            "",
            xy=centres[fk.dst_table],
            xytext=centres[fk.src_table],
            arrowprops=dict(
                arrowstyle="-|>",
                color="#aaaaaa" if is_stats else "#555555",
                lw=0.7 if is_stats else 1.0,
                alpha=0.5 if is_stats else 0.8,
                connectionstyle="arc3,rad=0.15",
            ),
            zorder=1,
        )

    # ── table boxes ───────────────────────────────────────────────────────────
    for t in tables:
        if t.name not in _POSITIONS:
            continue
        cx, cy = _POSITIONS[t.name]
        x0, y0, w, h = _box_rect(cx, cy, len(t.columns))
        color = _COLORS.get(t.name, _DEFAULT_COLOR)
        pk_set = set(t.pk_columns)

        # outer rounded rectangle
        rect = mpatches.FancyBboxPatch(
            (x0, y0), w, h,
            boxstyle="round,pad=0.04",
            linewidth=1.2, edgecolor="#333333", facecolor=color,
            zorder=2,
        )
        ax.add_patch(rect)

        # header background
        header_rect = mpatches.FancyBboxPatch(
            (x0, y0 + h - _HEADER_H), w, _HEADER_H,
            boxstyle="round,pad=0.04",
            linewidth=0, edgecolor="none",
            facecolor="#00000015",
            zorder=3,
        )
        ax.add_patch(header_rect)

        # table name
        ax.text(
            x0 + w / 2, y0 + h - _HEADER_H / 2,
            t.name,
            ha="center", va="center",
            fontsize=7, fontweight="bold",
            zorder=4,
        )
        # header underline
        ax.plot(
            [x0, x0 + w], [y0 + h - _HEADER_H, y0 + h - _HEADER_H],
            color="#333333", lw=0.8, zorder=4,
        )

        # column rows
        visible_cols = t.columns[:_MAX_COLS]
        extra = len(t.columns) - _MAX_COLS

        for i, col in enumerate(visible_cols):
            row_y = y0 + h - _HEADER_H - (i + 0.55) * _ROW_H
            flags: list[str] = []
            if col.is_pk or col.name in pk_set:
                flags.append("PK")
            if col.fk_table:
                flags.append("FK")
            tag = " [" + ",".join(flags) + "]" if flags else ""
            ax.text(
                x0 + 0.06, row_y,
                col.name + tag,
                ha="left", va="center", fontsize=5.5, color="#111111", zorder=4,
            )
            ax.text(
                x0 + w - 0.06, row_y,
                col.dtype,
                ha="right", va="center", fontsize=4.8, color="#666666", zorder=4,
            )

        if extra > 0:
            row_y = y0 + h - _HEADER_H - (_MAX_COLS + 0.55) * _ROW_H
            ax.text(
                x0 + w / 2, row_y,
                f"… {extra} more column{'s' if extra > 1 else ''}",
                ha="center", va="center", fontsize=5.0,
                color="#888888", style="italic", zorder=4,
            )

    # ── legend ────────────────────────────────────────────────────────────────
    legend_elements = [
        mpatches.Patch(facecolor="#d4edda", edgecolor="#333333", label="Reference tables"),
        mpatches.Patch(facecolor="#cce5ff", edgecolor="#333333", label="Assembly tables"),
        mpatches.Patch(facecolor="#fff3cd", edgecolor="#333333", label="Data tables"),
        mpatches.Patch(facecolor="#f8d7da", edgecolor="#333333", label="Statistics tables"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=8, framealpha=0.9)

    plt.tight_layout(pad=0.5)
    if output:
        plt.savefig(output, dpi=150, bbox_inches="tight")
        print(f"Diagram saved to: {output}")
    else:
        plt.show()


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db",     default=None,  help="DuckDB file path")
    parser.add_argument("--output", default=None,  help="Save diagram to file (PNG/SVG/PDF)")
    parser.add_argument("--text",   action="store_true", help="Print text summary only")
    args = parser.parse_args()

    tables, fks, source = load_schema(args.db)
    print(f"Schema loaded from {source}  ({len(tables)} tables, {len(fks)} FK relationships)")

    if args.text:
        print_text(tables, fks)
        return

    output = args.output or "schema_diagram.png"
    draw_diagram(tables, fks, output)


if __name__ == "__main__":
    main()
