"""
compute_hoop_stats.py
=====================
Compute per-part hoop-stress statistics for every experiment at a site and
persist the results in DuckDB.

For each experiment file not yet processed this module:
  1. Calls validate_fast_from_pupitre() to get the full hoop-stress time series
     (columns H1_fast, B1_fast, Supra1_fast, … depending on magnet_type).
  2. Saves the time series to a Parquet file with per-column and table-level
     PyArrow metadata (t0 timestamp, site name, unit/symbol per column, part map).
  3. Computes per-part stress-bin distributions    → hoop_stress_bin_stats
  4. Computes per-part rainflow fatigue cycle counts → hoop_stress_fatigue
  5. Marks the experiment as processed in hoop_stress_processed (idempotent).
  6. Appends "HOOP STRESS DONE" to experiments.status (idempotent).

Bin format
----------
Bins are specified as a comma-separated list of edge values in MPa:

    --bins 0,100,200,300,400,500,600

N edges define N-1 consecutive bins.  The legacy pair format
"l1:h1,l2:h2,..." is still accepted for backward compatibility.

Default bins span 0–600 MPa in 100 MPa steps (6 bins).

Usage
-----
    # via magnetdb.py (recommended):
    python magnetdb.py hoop-stress compute --site M9_M19061901 --db magnetdb.duckdb

    # standalone:
    python compute_hoop_stats.py --site M9_M19061901 --db magnetdb.duckdb
"""

import argparse
import json
import re
import shutil
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import DEFAULT_DB
from populate import _RECORDS_BASE as _DEFAULT_RECORDS_BASE
from populate import _SRV_SUBDIR as _DEFAULT_SRV_SUBDIR
from schema import ensure_schema

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_RECORDS_BASE = _DEFAULT_RECORDS_BASE
DEFAULT_SRV_SUBDIR = _DEFAULT_SRV_SUBDIR
DEFAULT_MAGNET_TYPE  = "all"

DEFAULT_BIN_EDGES: list[float] = [0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0]
DEFAULT_STRESS_BINS: list[tuple[float, float]] = [
    (DEFAULT_BIN_EDGES[i], DEFAULT_BIN_EDGES[i + 1])
    for i in range(len(DEFAULT_BIN_EDGES) - 1)
]

_HOOP_COL_RE = re.compile(r"^(H|B|Supra)\d+_fast$")

# ---------------------------------------------------------------------------
# Bin helpers
# ---------------------------------------------------------------------------


def bins_to_key(bins: list[tuple[float, float]]) -> str:
    """Return the canonical edges string used as the DB key, e.g. '0.0,100.0,200.0,...'."""
    edges = [bins[0][0]] + [hi for _, hi in bins]
    return ",".join(str(e) for e in edges)


def _parse_bins(s: str) -> list[tuple[float, float]]:
    """Parse bin specification into a list of (lo, hi) pairs.

    Accepts two formats:
      edges:  '0,100,200,300'         → [(0,100),(100,200),(200,300)]
      pairs:  '0:100,100:200,200:300' → same (legacy, still accepted)
    """
    if ":" in s:
        bins = []
        for pair in s.split(","):
            lo, hi = pair.strip().split(":")
            bins.append((float(lo), float(hi)))
        return bins
    edges = [float(x.strip()) for x in s.split(",")]
    if len(edges) < 2:
        raise ValueError(f"--bins needs at least 2 edge values, got: {s!r}")
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


# ---------------------------------------------------------------------------
# Part-column mapping
# ---------------------------------------------------------------------------


def build_part_column_map(
    site_name: str,
    db_path: str,
    con: "duckdb.DuckDBPyConnection | None" = None,
) -> dict[str, str]:
    """Return {column_name: part_name} for all coil parts at a site.

    Column names follow the same convention as validate_fast_from_pupitre():
      - helices  → H1_fast, H2_fast, …  (parts ordered by rank within insert magnets)
      - bitters  → B1_fast, B2_fast, …  (parts ordered by rank within bitter magnets)
      - supras   → Supra1_fast, …        (parts ordered by rank within supra magnets)

    Magnets are ordered by commissioned_at DESC (same as load_site_config_from_duckdb).
    Within each magnet, parts are ordered by rank.

    con : Reuse an already-open connection instead of opening a new read-only
          one (avoids DuckDB's "different configuration" error when called
          from within a caller's open connection).
    """
    owns_con = con is None
    if con is None:
        con = duckdb.connect(db_path, read_only=True)

    rows = con.execute("""
        SELECT m.name AS magnet_name, m.type AS magnet_type,
               p.name AS part_name,  p.type  AS part_type, mp.rank
        FROM site_magnets sm
        JOIN magnets      m  ON m.name         = sm.magnet_name
        JOIN magnet_parts mp ON mp.magnet_name = m.name
        JOIN parts        p  ON p.name         = mp.part_name
        WHERE sm.site_name = ?
        ORDER BY sm.commissioned_at DESC NULLS LAST, mp.rank
    """, [site_name]).fetchall()
    if owns_con:
        con.close()

    h_idx = b_idx = s_idx = 1
    mapping: dict[str, str] = {}
    for _magnet, magnet_type, part_name, part_type, _rank in rows:
        mt = (magnet_type or "").lower()
        pt = (part_type  or "").lower()
        if mt in ("insert",) and pt in ("helix",):
            mapping[f"H{h_idx}_fast"] = part_name
            h_idx += 1
        elif mt in ("bitters",) and pt in ("bitter",):
            mapping[f"B{b_idx}_fast"] = part_name
            b_idx += 1
        elif mt in ("supras",) and pt in ("supra",):
            mapping[f"Supra{s_idx}_fast"] = part_name
            s_idx += 1

    return mapping


def resolve_z0_by_type(
    site_name: str,
    db_path: str,
    con: "duckdb.DuckDBPyConnection | None" = None,
) -> tuple[list[float], list[float]]:
    """Return (z0_h, z0_b): per-part observation z-position from
    site_magnets.z_offset, in the same H1_fast/H2_fast/… and
    B1_fast/B2_fast/… order build_part_column_map() assigns columns.

    z0_h has one entry per helix part (one per Tube); z0_b has one entry
    per bitter part (one per Bstack). Missing z_offset defaults to 0.0
    (magnet centered on z=0). Used by validate_fast_from_pupitre() to pick
    which turn-group/plate represents each part, and where Bz is evaluated.

    con : Reuse an already-open connection instead of opening a new
          read-only one (avoids DuckDB's "different configuration" error
          when called from within a caller's open connection).
    """
    owns_con = con is None
    if con is None:
        con = duckdb.connect(db_path, read_only=True)

    rows = con.execute("""
        SELECT sm.z_offset, m.type AS magnet_type, p.type AS part_type
        FROM site_magnets sm
        JOIN magnets      m  ON m.name         = sm.magnet_name
        JOIN magnet_parts mp ON mp.magnet_name = m.name
        JOIN parts        p  ON p.name         = mp.part_name
        WHERE sm.site_name = ?
        ORDER BY sm.commissioned_at DESC NULLS LAST, mp.rank
    """, [site_name]).fetchall()
    if owns_con:
        con.close()

    z0_h: list[float] = []
    z0_b: list[float] = []
    for z_offset, magnet_type, part_type in rows:
        mt = (magnet_type or "").lower()
        pt = (part_type or "").lower()
        z = float(z_offset or 0.0)
        if mt in ("insert",) and pt in ("helix",):
            z0_h.append(z)
        elif mt in ("bitters",) and pt in ("bitter",):
            z0_b.append(z)

    return z0_h, z0_b


# ---------------------------------------------------------------------------
# Parquet I/O
# ---------------------------------------------------------------------------


def _column_meta(col: str) -> dict[bytes, bytes]:
    """Return PyArrow field-level metadata for a hoop-stress column."""
    m = re.match(r"^(H|B|Supra)(\d+)_fast$", col)
    if not m:
        return {}
    prefix, idx = m.group(1), m.group(2)
    symbol = {"H": "σ_H", "B": "σ_B", "Supra": "σ_S"}[prefix]
    return {b"unit": b"MPa", b"symbol": f"{symbol}{idx}".encode()}


def save_hoop_parquet(
    df: pd.DataFrame,
    path: Path,
    *,
    site_name: str,
    housing: str,
    t0: str,
    experiment_file: str,
    part_map: dict[str, str],
) -> Path:
    """Write *df* to a Parquet file with rich PyArrow metadata.

    Table-level metadata: site_name, housing, t0 (ISO timestamp string),
    experiment_file, part_map (JSON).
    Field-level metadata: unit and symbol for each *_fast column.
    """
    table = pa.Table.from_pandas(df, preserve_index=False)
    inv_part_map = {v: k for k, v in part_map.items()}

    # Per-field metadata (columns may already be renamed to part names, so
    # resolve back to the slot name _column_meta expects)
    new_fields = []
    for field in table.schema:
        slot_name = inv_part_map.get(field.name, field.name)
        extra = _column_meta(slot_name)
        if extra:
            new_fields.append(field.with_metadata(extra))
        else:
            new_fields.append(field)

    # Table-level metadata
    table_meta = {
        b"site_name":       site_name.encode(),
        b"housing":         (housing or "").encode(),
        b"t0":              (t0 or "").encode(),
        b"experiment_file": experiment_file.encode(),
        b"part_map":        json.dumps(part_map).encode(),
    }
    new_schema = pa.schema(new_fields, metadata=table_meta)
    table = table.cast(new_schema)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="snappy")
    return path


# ---------------------------------------------------------------------------
# Bin statistics (same additive pattern as compute_op_stats)
# ---------------------------------------------------------------------------


def _bin_series(
    sigma: pd.Series,
    dt: pd.Series,
    bins: list[tuple[float, float]],
) -> list[dict]:
    """Return rows for hoop_stress_bin_stats for one part column."""
    rows = []
    sigma = sigma.astype(float)
    dt = dt.astype(float)
    for low, high in bins:
        mask = (sigma >= low) & (sigma < high)
        sub_s = sigma[mask]
        sub_dt = dt[mask]
        if sub_s.empty:
            continue
        rows.append({
            "stress_bin_low":  low,
            "stress_bin_high": high,
            "n_samples":  len(sub_s),
            "sum_dt":     float(sub_dt.sum()),
            "sum_x_dt":   float((sub_s * sub_dt).sum()),
            "sum_x2_dt":  float((sub_s**2 * sub_dt).sum()),
            "min_x":      float(sub_s.min()),
            "max_x":      float(sub_s.max()),
        })
    return rows


# ---------------------------------------------------------------------------
# Rainflow fatigue
# ---------------------------------------------------------------------------


def _rainflow_stats(sigma: pd.Series) -> dict[str, float]:
    """Return {n_cycles, sum_range3} from a rainflow count of *sigma*."""
    try:
        import rainflow
    except ImportError:
        return {"n_cycles": 0.0, "sum_range3": 0.0}

    cycles = rainflow.count_cycles(sigma.to_numpy().astype(float))
    n_cycles = 0.0
    sum_range3 = 0.0
    for rng, count in cycles:
        n_cycles += count
        sum_range3 += count * float(rng) ** 3
    return {"n_cycles": n_cycles, "sum_range3": sum_range3}


# ---------------------------------------------------------------------------
# DuckDB helpers
# ---------------------------------------------------------------------------


def _get_experiments(con, site_name: str) -> pd.DataFrame:
    return con.execute(
        "SELECT id, name, file FROM experiments "
        "WHERE site_name = ? AND file IS NOT NULL ORDER BY id",
        [site_name],
    ).df()


def _check_processed(
    con, exp_id: int, bin_key: str
) -> tuple[bool, set[str]]:
    """Check whether this (experiment, bin_key) pair has already been processed.

    Returns (already_done, other_keys) where:
      already_done  – True if this exact bin_key is recorded for exp_id
      other_keys    – set of different bin keys already stored for exp_id
    """
    rows = con.execute(
        "SELECT bin_config FROM hoop_stress_processed WHERE experiment_id = ?", [exp_id]
    ).fetchall()
    stored = {r[0] for r in rows}
    return bin_key in stored, stored - {bin_key}


def _mark_processed(
    con, exp_id: int, magnet_type: str, bin_key: str, parquet_path: str | None
) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO hoop_stress_processed
            (experiment_id, bin_config, magnet_type, parquet_path)
        VALUES (?, ?, ?, ?)
        """,
        [exp_id, bin_key, magnet_type, parquet_path],
    )


def _insert_bin_stats(con, exp_id: int, part_name: str, rows: list[dict]) -> None:
    for r in rows:
        con.execute(
            """
            INSERT OR REPLACE INTO hoop_stress_bin_stats
                (experiment_id, part_name, stress_bin_low, stress_bin_high,
                 n_samples, sum_dt, sum_x_dt, sum_x2_dt, min_x, max_x)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [exp_id, part_name,
             r["stress_bin_low"], r["stress_bin_high"],
             r["n_samples"], r["sum_dt"], r["sum_x_dt"],
             r["sum_x2_dt"], r["min_x"], r["max_x"]],
        )


def _insert_fatigue(con, exp_id: int, part_name: str, stats: dict) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO hoop_stress_fatigue
            (experiment_id, part_name, n_cycles, sum_range3)
        VALUES (?, ?, ?, ?)
        """,
        [exp_id, part_name, stats["n_cycles"], stats["sum_range3"]],
    )


_HOOP_STATUS_TOKEN = "HOOP STRESS DONE"


def _append_hoop_status(con, exp_id: int) -> None:
    """Append the hoop-stress-done token to experiments.status (idempotent).

    Mirrors compute_exp_stats.py's 'STATS DONE' convention, but appends
    rather than overwrites so both pipelines' completion stays visible —
    'pending'/empty is replaced outright (it carries no information),
    anything else becomes '<status>, HOOP STRESS DONE'.
    """
    row = con.execute("SELECT status FROM experiments WHERE id = ?", [exp_id]).fetchone()
    status = row[0] if row else None
    if status and _HOOP_STATUS_TOKEN in status:
        return
    new_status = (
        _HOOP_STATUS_TOKEN
        if not status or status == "pending"
        else f"{status}, {_HOOP_STATUS_TOKEN}"
    )
    con.execute("UPDATE experiments SET status = ? WHERE id = ?", [new_status, exp_id])


# ---------------------------------------------------------------------------
# Part history (cross-experiment/site aggregation)
# ---------------------------------------------------------------------------


def part_history_stats(
    part_name: str,
    db_path: str,
    con: "duckdb.DuckDBPyConnection | None" = None,
) -> dict:
    """Aggregate a part's hoop-stress bin-stats and fatigue proxy across every
    experiment it has served in.

    Parameters
    ----------
    part_name : str
        DB part name (``parts.name``).
    db_path : str
        Path to the DuckDB file.
    con : duckdb.DuckDBPyConnection, optional
        Reuse an already-open connection instead of opening a new read-only
        one.

    Returns
    -------
    dict
        ``{"part_name": str, "experiments": list[dict], "bin_stats": list[dict],
        "fatigue": dict}``. ``experiments`` entries have ``experiment_id``,
        ``site_name``, ``experiment_name``. ``bin_stats`` entries are summed
        across experiments, keyed by ``stress_bin_low``/``stress_bin_high``,
        with the same fields as ``hoop_stress_bin_stats``. ``fatigue`` is
        ``{"n_cycles": float, "sum_range3": float}`` summed across
        experiments. All empty/zero if the part has no recorded data.
    """
    owns_con = con is None
    if con is None:
        con = duckdb.connect(db_path, read_only=True)

    experiments = con.execute("""
        SELECT DISTINCT b.experiment_id, e.site_name, e.name AS experiment_name
        FROM hoop_stress_bin_stats b
        JOIN experiments e ON e.id = b.experiment_id
        WHERE b.part_name = ?
        ORDER BY e.site_name, b.experiment_id
    """, [part_name]).fetchall()

    bin_rows = con.execute("""
        SELECT stress_bin_low, stress_bin_high,
               SUM(n_samples)  AS n_samples,
               SUM(sum_dt)     AS sum_dt,
               SUM(sum_x_dt)   AS sum_x_dt,
               SUM(sum_x2_dt)  AS sum_x2_dt,
               MIN(min_x)      AS min_x,
               MAX(max_x)      AS max_x
        FROM hoop_stress_bin_stats
        WHERE part_name = ?
        GROUP BY stress_bin_low, stress_bin_high
        ORDER BY stress_bin_low
    """, [part_name]).fetchall()

    fatigue_row = con.execute("""
        SELECT SUM(n_cycles), SUM(sum_range3)
        FROM hoop_stress_fatigue
        WHERE part_name = ?
    """, [part_name]).fetchone()

    if owns_con:
        con.close()

    return {
        "part_name": part_name,
        "experiments": [
            {"experiment_id": r[0], "site_name": r[1], "experiment_name": r[2]}
            for r in experiments
        ],
        "bin_stats": [
            {
                "stress_bin_low": r[0], "stress_bin_high": r[1],
                "n_samples": r[2], "sum_dt": r[3], "sum_x_dt": r[4],
                "sum_x2_dt": r[5], "min_x": r[6], "max_x": r[7],
            }
            for r in bin_rows
        ],
        "fatigue": {
            "n_cycles": fatigue_row[0] if fatigue_row and fatigue_row[0] is not None else 0.0,
            "sum_range3": fatigue_row[1] if fatigue_row and fatigue_row[1] is not None else 0.0,
        },
    }


def build_part_history_series(
    part_name: str,
    db_path: str,
    parquet_dir: str,
    con: "duckdb.DuckDBPyConnection | None" = None,
    verbose: bool = True,
) -> "Path | None":
    """Concatenate a part's raw hoop-stress time series across every
    experiment it has served in, sorted chronologically, and persist it.

    Reads each contributing experiment's Parquet file (resolved via
    ``hoop_stress_processed.parquet_path``, deduped by ``experiment_id``
    using the latest ``processed_at`` when multiple bin configs exist),
    pulls the ``part_name`` column and ``t``, and reconstructs an absolute
    timestamp from the file's own ``t0``/``site_name`` table metadata (see
    :func:`save_hoop_parquet`). Experiments whose Parquet predates the
    part-name column rename (no ``part_name`` column) are skipped with a
    ``[WARN]``.

    Parameters
    ----------
    part_name : str
        DB part name (``parts.name``); also the column name expected in
        each experiment's Parquet file.
    db_path : str
        Path to the DuckDB file.
    parquet_dir : str
        Directory the per-experiment hoop-stress Parquet files live in (the
        same one ``hoop-stress compute`` writes to). The concatenated
        history file is written to ``<parquet_dir>/parts/<part_name>.parquet``.
    con : duckdb.DuckDBPyConnection, optional
        Reuse an already-open connection instead of opening a new read-only
        one.
    verbose : bool
        Print ``[WARN]``/``[INFO]`` progress lines.

    Returns
    -------
    :class:`~pathlib.Path` or None
        Path to the written file, or None if no experiment contributed data.
    """
    owns_con = con is None
    if con is None:
        con = duckdb.connect(db_path, read_only=True)

    rows = con.execute("""
        SELECT experiment_id, parquet_path
        FROM (
            SELECT experiment_id, parquet_path, processed_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY experiment_id ORDER BY processed_at DESC
                   ) AS rn
            FROM hoop_stress_processed
            WHERE experiment_id IN (
                SELECT DISTINCT experiment_id FROM hoop_stress_bin_stats WHERE part_name = ?
            )
        )
        WHERE rn = 1
        ORDER BY experiment_id
    """, [part_name]).fetchall()

    if owns_con:
        con.close()

    frames: list[pd.DataFrame] = []
    for exp_id, parquet_path in rows:
        if not parquet_path:
            continue
        try:
            table = pq.read_table(parquet_path)
        except Exception as exc:
            if verbose:
                print(f"  [WARN] [{exp_id}] cannot read {parquet_path}: {exc}")
            continue

        if part_name not in table.column_names:
            if verbose:
                print(
                    f"  [WARN] [{exp_id}] {parquet_path}: no '{part_name}' column "
                    f"(pre-rename file), skipping"
                )
            continue
        if "t" not in table.column_names:
            if verbose:
                print(f"  [WARN] [{exp_id}] {parquet_path}: no 't' column, skipping")
            continue

        meta = table.schema.metadata or {}
        t0_str = meta.get(b"t0", b"").decode()
        site_name = meta.get(b"site_name", b"").decode()
        if not t0_str:
            if verbose:
                print(f"  [WARN] [{exp_id}] {parquet_path}: no t0 metadata, skipping")
            continue

        df = table.select(["t", part_name]).to_pandas()
        frames.append(pd.DataFrame({
            "timestamp": pd.Timestamp(t0_str) + pd.to_timedelta(df["t"].astype(float), unit="s"),
            "hoop_stress_MPa": df[part_name].astype(float),
            "experiment_id": exp_id,
            "site_name": site_name,
        }))

    if not frames:
        if verbose:
            print(f"[INFO] No processed experiments found for part '{part_name}'.")
        return None

    result = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)

    out_dir = Path(parquet_dir) / "parts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{part_name}.parquet"
    pq.write_table(pa.Table.from_pandas(result, preserve_index=False), out_path, compression="snappy")
    return out_path


# ---------------------------------------------------------------------------
# dt helper (same logic as compute_op_stats._compute_dt)
# ---------------------------------------------------------------------------


def _compute_dt(df: pd.DataFrame) -> pd.Series:
    if "t" in df.columns:
        return df["t"].diff().fillna(0.0).clip(lower=0.0)
    return pd.Series(1.0, index=df.index)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def compute_hoop_stress_history(
    site_name: str,
    db_path: str,
    *,
    magnet_type: str = DEFAULT_MAGNET_TYPE,
    bins: list[tuple[float, float]] = DEFAULT_STRESS_BINS,
    parquet_dir: str | None = None,
    geometries_dir: str | None = None,
    reprocess: bool = False,
    dry_run: bool = False,
    use_mrun: bool = False,
    pupitre_datadir: str = "",
    verbose: bool = True,
) -> dict:
    """Process all experiment files for *site_name* and persist hoop-stress stats.

    Parameters
    ----------
    site_name      : site FK (must exist in the sites table)
    db_path        : path to the DuckDB file
    magnet_type    : "H", "B", "S", or "all"
    bins           : list of (low, high) stress bins in MPa
    parquet_dir    : directory for Parquet output files (default: <db dir>/hoop_parquet)
    geometries_dir : override for geometry YAML directory
    reprocess      : if True, overwrite already-processed files
    dry_run        : discover files but do not write to DB or disk
    use_mrun       : pass to validate_fast_from_pupitre
    pupitre_datadir: root for pupitre files
    verbose        : print progress lines
    """
    from stress_map import (
        load_site_config_from_duckdb,
        load_magnettools,
        prepare_geometry_directory,
        validate_fast_from_pupitre,
    )
    try:
        from python_magnetrun.utils.timestamps import parse_filename_timestamp
    except ImportError:
        parse_filename_timestamp = None

    db_path = str(db_path)
    con = duckdb.connect(db_path)
    ensure_schema(con)

    experiments = _get_experiments(con, site_name)
    if experiments.empty:
        if verbose:
            print(f"[INFO] No experiments found for site '{site_name}'.")
        con.close()
        return {"new": 0, "skipped": 0, "errors": []}

    # ── Load site config and magnettools (shared across all experiments) ──────
    try:
        housing, magnet_configs = load_site_config_from_duckdb(site_name, db_path, con=con)
    except ValueError as exc:
        print(f"[ERROR] Cannot load site config for '{site_name}': {exc}")
        con.close()
        return {"new": 0, "skipped": 0, "errors": [str(exc)]}

    part_map = build_part_column_map(site_name, db_path, con=con)
    z0_h, z0_b = resolve_z0_by_type(site_name, db_path, con=con)

    # Parquet output directory
    pq_dir = Path(parquet_dir) if parquet_dir else Path(db_path).parent / "hoop_parquet"
    if not dry_run:
        pq_dir.mkdir(parents=True, exist_ok=True)

    results: dict = {"new": 0, "skipped": 0, "errors": []}

    # Build the geometry directory once per site (geometry is rebuilt on the
    # fly from parts.geometry_data — see prepare_geometry_directory()). It
    # creates and owns its own temp directory, cleaned up in the `finally`
    # below. con=con reuses our already-open connection instead of opening a
    # second one to the same file (DuckDB disallows mixed read-only/
    # read-write connections to one file).
    site_config = {
        "name": site_name,
        "magnets": [config for _magnet_name, config, _geo in magnet_configs],
    }
    try:
        tmpdir_path = prepare_geometry_directory(
            site_name, site_config, db_path,
            geometries_dir=geometries_dir, con=con,
        )
    except Exception as exc:
        print(f"[ERROR] geometry prep for '{site_name}': {exc}")
        con.close()
        return {"new": 0, "skipped": 0, "errors": [str(exc)]}

    try:
        # Load magnettools objects (Tubes, Helices, BMagnets, UMagnets, …).
        # site_config is the same shape prepare_geometry_directory() used above —
        # msite_setup() (inside load_magnettools) always expects confdata['magnets'].
        try:
            data = load_magnettools(site_config, tmpdir_path)
        except Exception as exc:
            print(f"[ERROR] Cannot load magnettools for '{site_name}': {exc}")
            con.close()
            return {"new": 0, "skipped": 0, "errors": [str(exc)]}

        for _, exp_row in experiments.iterrows():
            exp_id   = int(exp_row["id"])
            exp_name = str(exp_row["name"])
            _f = Path(str(exp_row["file"]))
            if not _f.is_absolute() and pupitre_datadir:
                exp_file = str(Path(pupitre_datadir) / housing / _f.name)
            else:
                exp_file = str(_f)

            bin_key = bins_to_key(bins)
            already_done, other_keys = _check_processed(con, exp_id, bin_key)
            if other_keys:
                print(
                    f"  [WARN] [{exp_id}] {exp_name}: previously processed with "
                    f"different bin(s): {sorted(other_keys)}. "
                    f"Use --reprocess to overwrite."
                )
            if already_done and not reprocess:
                results["skipped"] += 1
                continue

            if verbose:
                print(f"  processing [{exp_id}] {exp_name}")

            if dry_run:
                results["new"] += 1
                continue

            try:
                df = validate_fast_from_pupitre(
                    data, exp_file, housing,
                    magnet_type=magnet_type,
                    use_mrun=use_mrun,
                    site=site_name,
                    z0_h=z0_h,
                    z0_b=z0_b,
                )
            except Exception as exc:
                if verbose:
                    print(f"  [ERROR] {exp_name}: {exc}")
                results["errors"].append((exp_name, str(exc)))
                continue

            # Hoop stress columns present in this DataFrame
            hoop_cols = [c for c in df.columns if _HOOP_COL_RE.match(c)]
            if not hoop_cols:
                if verbose:
                    print(f"  [SKIP] {exp_name}: no hoop-stress columns in output")
                results["errors"].append((exp_name, "no hoop columns"))
                continue

            dt = _compute_dt(df)

            # t0 timestamp from filename
            t0_str = ""
            if parse_filename_timestamp is not None:
                try:
                    t0_dt = parse_filename_timestamp(Path(exp_file).name)
                    if t0_dt is not None:
                        t0_str = t0_dt.isoformat()
                except Exception:
                    pass

            # Save Parquet (columns renamed to part names; original df with
            # slot names is left untouched for the bin-stats/fatigue loop below)
            exp_part_map = {k: v for k, v in part_map.items() if k in hoop_cols}
            pq_path = pq_dir / f"{exp_name}.parquet"
            try:
                save_hoop_parquet(
                    df.rename(columns=exp_part_map), pq_path,
                    site_name=site_name,
                    housing=housing,
                    t0=t0_str,
                    experiment_file=exp_file,
                    part_map=exp_part_map,
                )
            except Exception as exc:
                if verbose:
                    print(f"  [WARN] Parquet write failed for {exp_name}: {exc}")
                pq_path = None

            # Bin stats + rainflow per part
            for col in hoop_cols:
                part_name = part_map.get(col, col)
                sigma = df[col]

                bin_rows = _bin_series(sigma, dt, bins)
                _insert_bin_stats(con, exp_id, part_name, bin_rows)

                fatigue = _rainflow_stats(sigma)
                _insert_fatigue(con, exp_id, part_name, fatigue)

            _mark_processed(
                con, exp_id, magnet_type, bin_key,
                str(pq_path) if pq_path else None,
            )
            _append_hoop_status(con, exp_id)
            results["new"] += 1
    finally:
        shutil.rmtree(tmpdir_path, ignore_errors=True)

    con.close()

    if verbose:
        print(
            f"\nDone — {results['new']} processed, "
            f"{results['skipped']} skipped, "
            f"{len(results['errors'])} errors"
        )
    return results


# ---------------------------------------------------------------------------
# CLI (standalone entry point)
# ---------------------------------------------------------------------------


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute per-part hoop-stress statistics and persist to DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db",           default=DEFAULT_DB,
                        help=f"DuckDB file (default: {DEFAULT_DB})")
    parser.add_argument("--site",         required=True,
                        help="Site name (FK in sites table)")
    parser.add_argument("--magnet-type",  default=DEFAULT_MAGNET_TYPE,
                        choices=["H", "B", "S", "all"],
                        dest="magnet_type",
                        help="Coil type(s) to compute (default: all)")
    parser.add_argument("--bins",         default=None,
                        help="Bin edges in MPa as a comma-separated list, e.g. "
                             f"'0,100,200,300,400,500,600' (default: {','.join(str(int(e)) for e in DEFAULT_BIN_EDGES)}). "
                             "Legacy pair format 'l1:h1,l2:h2,...' is also accepted.")
    parser.add_argument("--parquet-dir",  default=None, dest="parquet_dir",
                        help="Output directory for Parquet files (default: <db dir>/hoop_parquet)")
    parser.add_argument("--geometries",   default=None,
                        help="Override geometry YAML directory")
    parser.add_argument("--reprocess",    action="store_true",
                        help="Re-compute already-processed experiments")
    parser.add_argument("--dry-run",      action="store_true", dest="dry_run",
                        help="Discover files but do not write to DB or disk")
    parser.add_argument("--use-mrun",     action="store_true", dest="use_mrun",
                        help="Load files via python_magnetrun.MagnetRun.load_mrun()")
    parser.add_argument("--records-base",    default=str(DEFAULT_RECORDS_BASE), dest="records_base",
                        help=f"Root of the records tree (parent of --srv-subdir) "
                             f"(default: {DEFAULT_RECORDS_BASE})")
    parser.add_argument("--srv-subdir",      default=DEFAULT_SRV_SUBDIR, dest="srv_subdir",
                        help=f"Subdirectory of records-base for pupitre TXT files "
                             f"(default: {DEFAULT_SRV_SUBDIR})")
    parser.add_argument("--quiet",        action="store_true",
                        help="Suppress per-file output")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)
    bins = _parse_bins(args.bins) if args.bins else DEFAULT_STRESS_BINS
    pupitre_datadir = (
        str(Path(args.records_base) / args.srv_subdir) if args.records_base else ""
    )

    compute_hoop_stress_history(
        site_name=args.site,
        db_path=args.db,
        magnet_type=args.magnet_type,
        bins=bins,
        parquet_dir=args.parquet_dir,
        geometries_dir=args.geometries,
        reprocess=args.reprocess,
        dry_run=args.dry_run,
        use_mrun=args.use_mrun,
        pupitre_datadir=pupitre_datadir,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
