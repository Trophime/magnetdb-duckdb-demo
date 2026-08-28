#!/usr/bin/env python
"""Retire magnets superseded by a newer build sharing the same coil part.

For every ``helix``/``bitter``/``supra`` part, builds that part's magnet
history (every magnet linked to it via ``magnet_parts``, ordered by
``assembled_at``) and flags every magnet in that history except the most
recently assembled one. The deduplicated union of flagged magnets is set to
``status='retired'`` via ``update_magnet_status`` (status_history logged,
the magnet's own parts cascaded to ``in_stock``).

A magnet with no ``assembled_at`` can't be ordered, so it's skipped with a
warning and left untouched. A magnet already ``retired`` or ``dead`` is
also left untouched, so re-running is a no-op once every candidate has been
processed.

The rule is per-part and literal: a magnet is retired if it is not the
latest holder of *any* shared coil part, even if it is still the latest
holder of a different one.

Writes by default; pass ``--dry-run`` to preview. Run from the repository
root, e.g.::

    python to_duckdb/demos/retire_superseded_magnets.py --dry-run
    python to_duckdb/demos/retire_superseded_magnets.py --db to_duckdb/test-magnetdb.duckdb
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB  # noqa: E402
from crud import update_magnet_status  # noqa: E402
from enums import LifecycleStatus  # noqa: E402
from schema import COIL_TYPES  # noqa: E402

_SKIP_STATUSES = frozenset({LifecycleStatus.RETIRED.value, LifecycleStatus.DEAD.value})


def build_part_histories(con) -> dict[str, list[tuple[str, datetime | None]]]:
    """Group magnet-usage history by coil-type part.

    Parameters
    ----------
    con:
        Open DuckDB connection.

    Returns
    -------
    dict[str, list[tuple[str, datetime or None]]]
        Part name -> list of ``(magnet_name, assembled_at)`` for every
        magnet linked to that part via ``magnet_parts``. Only parts whose
        ``type`` is in :data:`schema.COIL_TYPES` are included.
    """
    placeholders = ", ".join("?" * len(COIL_TYPES))
    rows = con.execute(
        f"SELECT mp.part_name, m.name, m.assembled_at "
        f"FROM magnet_parts mp "
        f"JOIN parts p ON p.name = mp.part_name "
        f"JOIN magnets m ON m.name = mp.magnet_name "
        f"WHERE p.type IN ({placeholders})",
        list(COIL_TYPES),
    ).fetchall()
    histories: dict[str, list[tuple[str, datetime | None]]] = defaultdict(list)
    for part_name, magnet_name, assembled_at in rows:
        histories[part_name].append((magnet_name, assembled_at))
    return histories


def compute_retirement_candidates(
    histories: dict[str, list[tuple[str, datetime | None]]],
) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """Flag every magnet that is not the latest holder of a shared coil part.

    Parameters
    ----------
    histories : dict[str, list[tuple[str, datetime or None]]]
        Part name -> ``(magnet_name, assembled_at)`` pairs, from
        :func:`build_part_histories`.

    Returns
    -------
    tuple[dict[str, list[str]], list[tuple[str, str]]]
        ``(candidates, warnings)``. ``candidates`` maps each flagged
        magnet's name to the part names that flagged it (for the
        status_history description). ``warnings`` lists ``(part_name,
        magnet_name)`` pairs for magnets with no ``assembled_at``, which
        are excluded from ordering entirely.
    """
    candidates: dict[str, list[str]] = defaultdict(list)
    warnings: list[tuple[str, str]] = []
    for part_name, entries in sorted(histories.items()):
        warnings.extend((part_name, name) for name, ts in entries if ts is None)
        dated = sorted(
            ((name, ts) for name, ts in entries if ts is not None),
            key=lambda entry: entry[1],
        )
        for name, _ts in dated[:-1]:
            candidates[name].append(part_name)
    return dict(candidates), warnings


def retire_magnets(con, candidates: dict[str, list[str]], dry_run: bool) -> None:
    """Retire every candidate magnet not already retired/dead.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    candidates : dict[str, list[str]]
        Magnet name -> part names that flagged it, from
        :func:`compute_retirement_candidates`.
    dry_run : bool
        If True, print what would change without writing anything.
    """
    changed = 0
    for name in sorted(candidates):
        current_status = con.execute(
            "SELECT status FROM magnets WHERE name = ?", [name]
        ).fetchone()[0]
        parts = ", ".join(candidates[name])
        if current_status in _SKIP_STATUSES:
            print(f"  = magnet    {name}  already {current_status}, skipped")
            continue
        if dry_run:
            print(f"[DRY RUN] would retire magnet {name}  (superseded for part(s): {parts})")
        else:
            update_magnet_status(
                con, name, LifecycleStatus.RETIRED.value,
                description=f"Superseded: no longer the most recently assembled magnet for shared part(s) {parts}.",
            )
        changed += 1
    print(f"\n{'Would retire' if dry_run else 'Retired'} {changed} magnet(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be changed without writing anything",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=args.dry_run) as con:
        histories = build_part_histories(con)
        candidates, warnings = compute_retirement_candidates(histories)

        for part_name, magnet_name in warnings:
            print(f"  ! part {part_name}: magnet {magnet_name} has no assembled_at -- skipped")

        if not candidates:
            print("Nothing to retire.")
            return

        retire_magnets(con, candidates, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
