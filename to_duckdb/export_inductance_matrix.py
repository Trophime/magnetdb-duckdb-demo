"""Export the inductance matrix of an assembly to CSV.

The assembly is loaded from DuckDB and turned into magnettools objects (same
chain as compute_hoop_stats.py), then
``magnettools.inductances.compute_inductance_matrix`` writes the matrix [H].

Output files, for ``--csv OUT.csv``:

    OUT.csv          full symmetric matrix: helix tubes, then Bitters, then supras
    OUT_summary.csv  block totals L_H, L_B, L_S, M_HB, M_HS, M_BS (from magnettools)
    OUT_pairs.csv    consecutive helix tubes paired, H1H2, H3H4, ... (--pair-tubes)
    OUT_labels.csv   label, magnet, part: which DB part each row/column is

Example:

    python export_inductance_matrix.py --assembly M9_A230801_00 \\
        --csv M9_A230801_00_inductances.csv --pair-tubes

``--pair-tubes`` needs ``pair_tube_inductances`` in magnettools.inductances
(my-magnettools d4b4816 or later); without it the script stops with an error.
"""

import argparse
import csv
import importlib
import os
import re
import shutil
from pathlib import Path

import duckdb

from compute_hoop_stats import build_part_column_map
from config import DEFAULT_DB

# build_part_column_map() column prefix -> magnettools label group
_PART_GROUPS = {"H": "H", "B": "B", "Supra": "S"}


def _load_inductances(pair_tubes: bool) -> tuple:
    """Return ``(compute_inductance_matrix, pair_tube_inductances or None)`` from magnettools."""
    try:
        inductances = importlib.import_module("magnettools.inductances")
    except ImportError as exc:
        raise ImportError(
            "magnettools.inductances is not available: install python3-magnettools >= 1.2.3"
        ) from exc
    pair = None
    if pair_tubes:
        pair = getattr(inductances, "pair_tube_inductances", None)
        if pair is None:
            raise ImportError(
                "--pair-tubes: the magnettools python bindings have no "
                "magnettools.inductances.pair_tube_inductances "
                f"({inductances.__file__}); it needs my-magnettools d4b4816 or later"
            )
    return inductances.compute_inductance_matrix, pair


def _sibling(csvfile: Path, suffix: str) -> Path:
    """Return ``<stem><suffix><ext>`` next to *csvfile*."""
    stem, ext = os.path.splitext(csvfile)
    return Path(f"{stem}{suffix}{ext}")


def _part_magnets(con: duckdb.DuckDBPyConnection, assembly_name: str) -> dict[str, str]:
    """Return ``{part_name: magnet_name}`` for the magnets of the assembly."""
    rows = con.execute(
        """
        SELECT mp.part_name, mp.magnet_name
        FROM assembly_magnets am
        JOIN magnet_parts mp ON mp.magnet_name = am.magnet_name
        WHERE am.assembly_name = ?
        """,
        [assembly_name],
    ).fetchall()
    return dict(rows)


def build_label_rows(
    labels: list[str],
    part_map: dict[str, str],
    part_magnets: dict[str, str],
    pair_labels: list[str] | None = None,
) -> list[dict[str, str]] | None:
    """Match the matrix labels with the DB parts, group by group.

    Inside each group (helix tubes ``H``, Bitters ``B``, supras ``S``) the
    k-th matrix label is matched with the k-th DB part. Both magnettools label
    styles are accepted: ``H_0`` (python3-magnettools 1.2.6) and ``H1`` (later).

    Parameters
    ----------
    labels : list of str
        Row/column labels returned by ``compute_inductance_matrix``.
    part_map : dict of str to str
        ``{H1_fast: part, B1_fast: part, Supra1_fast: part}``, as returned by
        :func:`compute_hoop_stats.build_part_column_map`.
    part_magnets : dict of str to str
        ``{part: magnet}`` for the parts of the assembly.
    pair_labels : list of str, optional
        Labels returned by ``pair_tube_inductances``. One extra row is added
        per helix pair, with the names of its two parts (and magnets, if they
        differ) joined by ``;``.

    Returns
    -------
    list of dict or None
        One ``{"label", "magnet", "part"}`` row per matrix label, in matrix
        order, then the pair rows. ``None`` (with a warning) when a group has
        a different number of matrix labels and DB parts: magnettools does
        not split the assembly like the DB does.
    """
    parts: dict[str, list[str]] = {"H": [], "B": [], "S": []}
    for column, part in part_map.items():
        match = re.fullmatch(r"(H|B|Supra)\d+_fast", column)
        parts[_PART_GROUPS[match.group(1)]].append(part)

    matched = [
        (label, match.group(1))
        for label in labels
        if (match := re.fullmatch(r"(H|B|S)_?\d+", label))
    ]
    for group, group_parts in parts.items():
        n_labels = sum(1 for _label, g in matched if g == group)
        if n_labels != len(group_parts):
            print(
                f"[WARN] group {group}: {n_labels} matrix labels but "
                f"{len(group_parts)} DB parts; no label sidecar written."
            )
            return None

    part_iters = {group: iter(group_parts) for group, group_parts in parts.items()}
    rows = []
    for label, group in matched:
        part = next(part_iters[group])
        rows.append({"label": label, "magnet": part_magnets[part], "part": part})

    if pair_labels:
        tubes = [row for row, (_label, group) in zip(rows, matched, strict=True) if group == "H"]
        helix_pairs = [label for label in pair_labels if re.fullmatch(r"H\d+H\d+", label)]
        for k, label in enumerate(helix_pairs):
            pair = tubes[2 * k : 2 * k + 2]
            rows.append({
                "label": label,
                "magnet": ";".join(dict.fromkeys(row["magnet"] for row in pair)),
                "part": ";".join(row["part"] for row in pair),
            })
    return rows


def export_inductance_matrix(
    assembly_name: str,
    db_path: str | Path,
    csvfile: str | Path,
    *,
    pair_tubes: bool = False,
    geometries_dir: str | Path | None = None,
    verbose: bool = True,
) -> dict:
    """Compute the inductance matrix of an assembly and write it as CSV.

    Parameters
    ----------
    assembly_name : str
        Assembly name in the ``assemblies`` table (e.g. ``"M9_A230801_00"``).
    db_path : str or Path
        DuckDB file, opened read-only.
    csvfile : str or Path
        Output matrix [H]. magnettools also writes ``<stem>_summary<ext>``;
        this function writes ``<stem>_labels<ext>`` and, with *pair_tubes*,
        ``<stem>_pairs<ext>``.
    pair_tubes : bool, optional
        Also pair consecutive helix tubes (H1+H2, H3+H4, ...) with
        ``magnettools.inductances.pair_tube_inductances``.
    geometries_dir : str or Path, optional
        Forwarded to ``prepare_geometry_directory``.
    verbose : bool, optional
        Print the object counts and the magnettools tables.

    Returns
    -------
    dict
        ``result``: dict returned by ``compute_inductance_matrix``;
        ``pairs``: dict returned by ``pair_tube_inductances``, or ``None``;
        ``labels``: sidecar rows, or ``None`` if not written;
        ``files``: list of :class:`~pathlib.Path` written by this call.

    Raises
    ------
    ImportError
        magnettools is missing, or *pair_tubes* is set and it has no
        ``pair_tube_inductances``.
    ValueError
        The assembly cannot be loaded, or *pair_tubes* is set and the number
        of helix tubes is odd.
    """
    compute_inductance_matrix, pair_tube_inductances = _load_inductances(pair_tubes)
    from stress_map import (
        load_assembly_config_from_duckdb,
        load_magnettools,
        prepare_geometry_directory,
    )

    db_path = str(db_path)
    csvfile = Path(csvfile)
    csvfile.parent.mkdir(parents=True, exist_ok=True)
    pairs_csvfile = _sibling(csvfile, "_pairs")
    labels_csvfile = _sibling(csvfile, "_labels")

    con = duckdb.connect(db_path, read_only=True)
    tmpdir = None
    try:
        _housing, magnet_configs = load_assembly_config_from_duckdb(assembly_name, db_path, con=con)
        assembly_config = {
            "name": assembly_name,
            "magnets": [config for _magnet_name, config, _geo in magnet_configs],
        }
        tmpdir = prepare_geometry_directory(
            assembly_name, assembly_config, db_path, geometries_dir=geometries_dir, con=con,
        )
        Tubes, Helices, _OHelices, BMagnets, UMagnets, _Shims = load_magnettools(assembly_config, tmpdir)
        if verbose:
            print(f"Tubes: {len(Tubes)}, BMagnets: {len(BMagnets)}, UMagnets: {len(UMagnets)}")

        result = compute_inductance_matrix(
            Tubes, Helices, BMagnets, UMagnets, csvfile=str(csvfile), verbose=verbose,
        )
        files = [csvfile, _sibling(csvfile, "_summary")]
        pairs = None
        if pair_tubes:
            pairs = pair_tube_inductances(result, csvfile=str(pairs_csvfile), verbose=verbose)
            files.append(pairs_csvfile)

        part_map = build_part_column_map(assembly_name, db_path, con=con)
        part_magnets = _part_magnets(con, assembly_name)
    finally:
        con.close()
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)

    label_rows = build_label_rows(
        result["labels"], part_map, part_magnets, pairs["labels"] if pairs else None,
    )
    if label_rows is not None:
        with open(labels_csvfile, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["label", "magnet", "part"])
            writer.writeheader()
            writer.writerows(label_rows)
        files.append(labels_csvfile)

    if verbose:
        for path in files:
            print(f"wrote {path}")
    return {"result": result, "pairs": pairs, "labels": label_rows, "files": files}


def _parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description="Compute the inductance matrix of an assembly with magnettools and save it as CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"DuckDB file, opened read-only (default: {DEFAULT_DB})")
    parser.add_argument("--assembly", required=True,
                        help="Assembly name (FK in assemblies table)")
    parser.add_argument("--csv", required=True, dest="csvfile",
                        help="Output CSV for the inductance matrix [H]")
    parser.add_argument("--pair-tubes", action="store_true", dest="pair_tubes",
                        help="Also pair consecutive helix tubes (H1H2, H3H4, ...), "
                             "saved to <stem>_pairs<ext>")
    parser.add_argument("--geometries", default=None,
                        help="Override geometry YAML directory")
    parser.add_argument("--quiet", action="store_true",
                        help="Do not print the matrices")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    """Command-line entry point."""
    args = _parse_args(argv)
    try:
        export_inductance_matrix(
            args.assembly,
            args.db,
            args.csvfile,
            pair_tubes=args.pair_tubes,
            geometries_dir=args.geometries,
            verbose=not args.quiet,
        )
    except (ImportError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
