#!/usr/bin/env python
"""Find experiments by Field signature pattern and max-plateau constraints.

An experiment matches when:

1. if ``--pattern`` is given, its compacted ``Field`` signature (a string of
   regimes ``U`` up, ``P`` plateau, ``D`` down, computed with
   python_magnetrun) fully matches that regular expression; without
   ``--pattern`` any signature is accepted;
2. its *max plateau* -- the ``P`` regime with the highest mean field -- has a
   mean field in ``[--bmin, --bmax]`` [T];
3. that plateau lasts at least ``--min-plateau`` [s].

For example, the pattern ``P?(UP)+(DP)*DP?`` is a staircase: ``UPUP...UP``
up to the top plateau, then ``DPD...PD`` back down, with optional zero-field
plateaux at both ends.

Pupitre files are only loaded for candidates kept by a SQL pre-filter on
``exp_run_scalars``: ``field_max`` in ``[bmin, bmax + overshoot]`` and
``duration_field_on_s >= min_plateau``.

A sample is ``U`` or ``D`` when the field changes by at least ``--threshold``
since the previous sample, so at 1 Hz the threshold is a ramp rate in T/s:
slower ramps are seen as plateaux (see ``magnet_first_signatures.py``).

Usage
-----
    python find_experiments_by_signature.py --db magnetdb-2026-11-16.duckdb \\
        --housing M9 --bmin 20 --bmax 25 --min-plateau 300
    python find_experiments_by_signature.py --pattern 'P?(UP)+(DP)*DP?' --bmin 30 --bmax 40
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import duckdb
from magnet_first_signatures import _compress
from python_magnetrun.MagnetRun import load_mrun
from python_magnetrun.signature import Signature
from python_magnetrun.utils.narwhals_compat import to_pandas

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB  # noqa: E402
from populate import _RECORDS_BASE, _SRV_SUBDIR  # noqa: E402

logging.disable(logging.WARNING)

STAIRCASE_PATTERN = r"P?(UP)+(DP)*DP?"


def _candidates(con, args) -> list[tuple]:
    """Return (name, housing, assembly, file) rows passing the scalar pre-filter."""
    sql = """
        SELECT e.name, a.housing, e.assembly_name, e.file
        FROM experiments e
        JOIN assemblies a ON a.name = e.assembly_name
        JOIN exp_run_scalars fmax ON fmax.experiment_id = e.id AND fmax.channel = 'field_max'
        JOIN exp_run_scalars fon  ON fon.experiment_id  = e.id AND fon.channel  = 'duration_field_on_s'
        WHERE fmax.value BETWEEN ? AND ?
          AND fon.value >= ?
    """
    params: list = [args.bmin, args.bmax + args.overshoot, args.min_plateau]
    if args.housing:
        sql += " AND a.housing IN (SELECT unnest(?))"
        params.append(args.housing)
    if args.assembly:
        sql += " AND e.assembly_name IN (SELECT unnest(?))"
        params.append(args.assembly)
    if args.date_from:
        sql += " AND strptime(e.name, '%Y.%m.%d - %H:%M:%S') >= CAST(? AS TIMESTAMP)"
        params.append(args.date_from)
    if args.date_to:
        sql += " AND strptime(e.name, '%Y.%m.%d - %H:%M:%S') < CAST(? AS TIMESTAMP)"
        params.append(args.date_to)
    sql += " ORDER BY e.name"
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"
    return con.execute(sql, params).fetchall()


def plateaux_from_signature(sig: Signature, t, field) -> list[tuple[float, float]]:
    """Return the (mean field, duration) of each plateau regime of a signature.

    Parameters
    ----------
    sig : Signature
        Compacted signature computed on the same samples as *t* and *field*;
        ``sig.changes`` are positional indices of regime starts.
    t : :class:`~pandas.Series`
        Time axis [s].
    field : :class:`~pandas.Series`
        Field samples [T].

    Returns
    -------
    list of tuple of float
        One ``(mean_field [T], duration [s])`` per ``P`` regime, in order.
    """
    bounds = list(sig.changes) + [len(t) - 1]
    out = []
    for i, regime in enumerate(sig.regimes):
        if regime != "P":
            continue
        start, end = bounds[i], bounds[i + 1]
        if end <= start:
            continue
        out.append((float(field.iloc[start:end + 1].mean()), float(t.iloc[end] - t.iloc[start])))
    return out


def main() -> None:
    """Print experiments matching a signature pattern and max-plateau limits.

    Parameters
    ----------
    None
        Options are read from the command line (see ``--help``).

    Returns
    -------
    None
        A Markdown table of matching experiments and a count summary are
        printed to stdout.
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})")
    p.add_argument("--records-base", type=Path, default=_RECORDS_BASE,
                   help=f"Root of the records tree; pupitre files in <records-base>/{_SRV_SUBDIR}/<housing>")
    p.add_argument("--pattern", default=None,
                   help="regex the whole compacted signature must match, e.g. "
                        f"'{STAIRCASE_PATTERN}' for a staircase (default: any signature)")
    p.add_argument("--bmin", type=float, required=True, help="[T] lower bound of the max-plateau field")
    p.add_argument("--bmax", type=float, required=True, help="[T] upper bound of the max-plateau field")
    p.add_argument("--min-plateau", type=float, default=60.0,
                   help="[s] minimum duration of the max plateau (default: 60)")
    p.add_argument("--overshoot", type=float, default=0.5,
                   help="[T] field_max may exceed --bmax by this in the SQL pre-filter (default: 0.5)")
    p.add_argument("--threshold", type=float, default=0.1,
                   help="[T per sample] signature threshold (default: 0.1, i.e. 0.1 T/s at 1 Hz)")
    p.add_argument("--housing", nargs="+", default=None, help="only these housings")
    p.add_argument("--assembly", nargs="+", default=None, help="only these assemblies")
    p.add_argument("--from", dest="date_from", default=None, help="only experiments on/after this date")
    p.add_argument("--to", dest="date_to", default=None, help="only experiments before this date")
    p.add_argument("--limit", type=int, default=None, help="at most this many candidates are loaded")
    args = p.parse_args()

    pattern = re.compile(args.pattern) if args.pattern else None
    con = duckdb.connect(args.db, read_only=True)
    candidates = _candidates(con, args)
    con.close()
    print(f"{len(candidates)} candidate(s) after the SQL pre-filter\n")

    srv = Path(args.records_base) / _SRV_SUBDIR
    n_loaded = n_pattern = 0
    rows = []
    for name, housing, assembly, file in candidates:
        path = Path(file) if Path(file).is_absolute() else srv / housing / file
        try:
            md = load_mrun(str(path), housing=housing, auto_resolve=False).getMData()
            sig = Signature.from_mdata(md, "Field", "t", args.threshold)
            sig.compact()
            df = to_pandas(md.getData(["t", "Field"]))
        except Exception as exc:  # noqa: BLE001 - malformed files raise many types
            print(f"skip {name} ({housing}): {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        n_loaded += 1
        regimes = "".join(sig.regimes)
        if pattern and not pattern.fullmatch(regimes):
            continue
        n_pattern += 1
        plats = plateaux_from_signature(sig, df["t"], df["Field"])
        if not plats:
            continue
        bmax_plat, dur = max(plats, key=lambda x: x[0])
        if args.bmin <= bmax_plat <= args.bmax and dur >= args.min_plateau:
            rows.append((name, housing, assembly, _compress(regimes), bmax_plat, dur, len(plats)))

    print("| Experiment | Housing | Assembly | Signature | Max plateau B [T] | Duration [s] | Plateaux |")
    print("|---|---|---|---|---|---|---|")
    for name, housing, assembly, sig, b, dur, n in rows:
        print(f"| `{name}` | {housing} | {assembly} | `{sig}` | {b:.2f} | {dur:.0f} | {n} |")
    matched = f"{n_pattern} matched the pattern" if pattern else "pattern: any"
    print(f"\n{len(candidates)} candidates, {n_loaded} loaded, {matched}, "
          f"{len(rows)} matched all constraints")


if __name__ == "__main__":
    main()
