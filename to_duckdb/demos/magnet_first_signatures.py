#!/usr/bin/env python
"""Field signature of the first 'real' experiment of each magnet.

For each magnet, its experiments (through the assemblies that contain it,
``assembly_magnets``) are tried in order of experiment name. One is skipped
while it is too short (``--min-duration``) or its field never exceeds
``--min-field``; the next one is then tried, up to ``--max-tries``.

The ``Field`` signature of the chosen file is computed with python_magnetrun
(``Signature.from_mdata(..., "Field", "t", threshold)``, then ``compact()``):
a string of regimes ``U`` (up), ``P`` (plateau) and ``D`` (down). A sample is
``U`` or ``D`` when the field changes by at least *threshold* since the
previous sample, so at 1 Hz the threshold is a ramp rate in T/s: slower ramps
are seen as plateaux. Entries whose signature is a single ``P`` are rerun at
the ``--fallback`` thresholds and shown in a second table.

Repeated units are written compressed: ``(PU)33`` = 33 times ``PU``,
``(PUPD)12`` = 12 times ``PUPD``. Both tables are printed as Markdown.

Usage
-----
    python magnet_first_signatures.py --db magnetdb-2026-10-08.duckdb
    python magnet_first_signatures.py --magnet M25012001 M19020601 --min-field 1.5
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd
from python_magnetrun.MagnetRun import load_mrun
from python_magnetrun.signature import Signature

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB  # noqa: E402
from populate import _RECORDS_BASE, _SRV_SUBDIR  # noqa: E402

logging.disable(logging.WARNING)


def _quick_stats(path: Path) -> tuple[float, float] | None:
    """Return (duration [s], max |Field| [T]) from Date/Time/Field, or None if unreadable."""
    try:
        df = pd.read_csv(path, sep=r"\s+", skiprows=1, usecols=["Date", "Time", "Field"],
                         on_bad_lines="skip", engine="c")
        field = pd.to_numeric(df["Field"], errors="coerce")
        ts = pd.to_datetime(df["Date"] + " " + df["Time"], format="%Y.%m.%d %H:%M:%S",
                            errors="coerce").dropna()
        if ts.empty:
            return None
        return (ts.iloc[-1] - ts.iloc[0]).total_seconds(), float(field.abs().max())
    except Exception:
        return None


def _compress(regimes: str) -> str:
    """Write repeated 2-letter units as (XY)n, then repeated 4-letter ones as (WXYZ)n."""
    regimes = re.sub(r"(UP|DP|PU|PD)\1{2,}",
                     lambda m: f"({m.group(1)}){len(m.group(0)) // 2}", regimes)
    return re.sub(r"([UDP]{4})\1{2,}",
                  lambda m: f"({m.group(1)}){len(m.group(0)) // 4}", regimes)


def _signature(md, threshold: float) -> str:
    """Compacted, compressed Field signature of *md* at *threshold* [T per sample]."""
    sig = Signature.from_mdata(md, "Field", "t", threshold)
    sig.compact()
    return _compress("".join(sig.regimes))


def main() -> None:
    """Print the first-experiment Field signature of each magnet (Markdown tables).

    Parameters
    ----------
    None
        Options are read from the command line (see ``--help``).

    Returns
    -------
    None
        Two Markdown tables are printed to stdout: one row per magnet, then
        the single-``P`` entries rerun at the fallback thresholds.
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})")
    p.add_argument("--records-base", type=Path, default=_RECORDS_BASE,
                   help=f"Root of the records tree; pupitre files in <records-base>/{_SRV_SUBDIR}/<housing>")
    p.add_argument("--min-duration", type=float, default=120.0,
                   help="[s] files shorter than this are skipped (default: 120)")
    p.add_argument("--min-field", type=float, default=1.0,
                   help="[T] the field must exceed this (default: 1.0)")
    p.add_argument("--threshold", type=float, default=0.1,
                   help="[T per sample] signature threshold (default: 0.1, i.e. 0.1 T/s at 1 Hz)")
    p.add_argument("--fallback", type=float, nargs="+", default=[0.05, 0.02, 0.01, 0.005],
                   help="[T per sample] thresholds tried for single-P entries")
    p.add_argument("--max-tries", type=int, default=300,
                   help="experiments tried per magnet (default: 300)")
    p.add_argument("--magnet", nargs="+", default=None, help="only these magnets")
    args = p.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    by_magnet: dict[str, list] = {}
    for magnet, mtype, housing, file in con.execute(
        """
        SELECT m.name, m.type, a.housing, e.file
        FROM magnets m
        JOIN assembly_magnets am ON am.magnet_name = m.name
        JOIN assemblies a ON a.name = am.assembly_name
        JOIN experiments e ON e.assembly_name = a.name
        ORDER BY m.name, e.name
        """
    ).fetchall():
        if args.magnet is None or magnet in args.magnet:
            by_magnet.setdefault(magnet, []).append((mtype, housing, file))
    con.close()

    srv = Path(args.records_base) / _SRV_SUBDIR
    stats_cache: dict[Path, tuple[float, float] | None] = {}
    data_cache: dict[Path, object] = {}
    single_p = []  # (magnet, housing, file, path)

    print("| Magnet | Type | Housing | Chosen experiment file | Rank | Skipped | Duration [min] "
          f"| Field max [T] | Signature ({args.threshold:g} T) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for magnet in sorted(by_magnet, key=lambda m: (by_magnet[m][0][2], m)):
        tries = by_magnet[magnet][: args.max_tries]
        chosen = None
        for rank, (mtype, housing, file) in enumerate(tries, start=1):
            path = Path(file) if Path(file).is_absolute() else srv / housing / file
            if path not in stats_cache:
                stats_cache[path] = _quick_stats(path)
            st = stats_cache[path]
            if st and st[0] >= args.min_duration and st[1] > args.min_field:
                chosen = (rank, mtype, housing, file, path, st)
                break
        if chosen is None:
            mtype, housing = tries[0][0], tries[0][1]
            print(f"| `{magnet}` | {mtype} | {housing} | none in the first {len(tries)} | — "
                  f"| {len(tries)} | — | — | — |")
            continue
        rank, mtype, housing, file, path, (duration, fmax) = chosen
        try:
            if path not in data_cache:
                data_cache[path] = load_mrun(str(path), housing=housing, auto_resolve=False).getMData()
            sig = _signature(data_cache[path], args.threshold)
        except Exception as exc:
            sig = f"error: {type(exc).__name__}"
        if sig == "P":
            single_p.append((magnet, housing, file, path))
        print(f"| `{magnet}` | {mtype} | {housing} | `{file}` | {rank} | {rank - 1} "
              f"| {duration / 60:.0f} | {fmax:.2f} | `{sig}`{' ⚠' if sig == 'P' else ''} |")

    if not single_p:
        return
    print("\nSingle-P entries rerun with lower thresholds [T per sample]:\n")
    print("| Magnet | Housing | File | dt [s] | " + " | ".join(f"{t:g} T" for t in args.fallback) + " |")
    print("|---|---|---|---|" + "---|" * len(args.fallback))
    for magnet, housing, file, path in single_p:
        md = data_cache[path]
        dt = float(md.getData(["t"])["t"].diff().median())
        cells = []
        for threshold in args.fallback:
            s = _signature(md, threshold)
            cells.append(f"`{s}`" if len(s) <= 60 else f"`{s[:57]}…`")
        print(f"| `{magnet}` | {housing} | `{file}` | {dt:g} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
