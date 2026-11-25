"""Write a Feel++ simulation setup for a DuckDB assembly, or one of its magnets.

The assembly configuration, geometry and materials come from DuckDB (same
chain as compute_hoop_stats.py and export_inductance_matrix.py); the setup
files are generated locally by ``python_magnetsetup.setup.setup()``, with no
magnetdb server and no Postgres.

Output, in ``--wd DIR``:

    <target>-<method>-<model>-<geom>-sim.cfg / .json   Feel++ cfg and json model
    conductor-*.json, insulator-*.json                  generic material jsons
    *.csv                                               csv files written by the setup
    geometries/*.yaml                                   geometry YAMLs for the CAD step
    setup.json                                          UUID, inputs, provenance, geometry fingerprint

Examples:

    python setup_simulation.py --db magnetdb.duckdb --assembly M9_A230801_00 \\
        --magnet M23072801 --current M23072801=31000 \\
        --model thmag_hcurl --cooling gradHZ --wd setups/M23072801

    python setup_simulation.py --db magnetdb.duckdb --assembly M9_A230801_00 \\
        --current M23072801=31000 --current M9Bitters-newBi08=33000 \\
        --model thmag_hcurl --cooling gradHZ --wd setups/M9_A230801_00

Run it on a copy or a snapshot of the database. The setup directory contains
geometry and material values from the DB: it is as confidential as the DB.
CAD, mesh and solve are separate steps (see
plans/PLAN_setup_simulation.md).
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import uuid
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from config import DEFAULT_DB

SETUP_JSON = "setup.json"


def _parse_current(text: str) -> tuple[str, float]:
    """Parse ``NAME=VALUE`` into ``(name, value [A])``; raise ``ValueError`` if malformed."""
    name, sep, value = text.partition("=")
    if not sep or not name or not value:
        raise ValueError(f"expected NAME=VALUE, got {text!r}")
    return name, float(value)


def _assembly_magnet_order(yaml_path: str | Path) -> list[str]:
    """Return the magnet names of an Assembly YAML, in file order."""
    import python_magnetgeo as pmg
    from python_magnetgeo.utils import getObject

    pmg.verify_class_registration()
    return [magnet.name for magnet in getObject(str(yaml_path)).magnets]


def _sha256_file(path: Path) -> str:
    """Return the sha256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _geometry_fingerprint(geometries: Path) -> str:
    """Return the sha256 of the YAML files in *geometries*, in sorted name order."""
    digest = hashlib.sha256()
    for path in sorted(geometries.glob("*.yaml")):
        digest.update(path.name.encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def _version(package: str) -> str | None:
    """Return the installed version of *package*, or ``None``."""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _relative(path: str, wd: Path) -> str:
    """Return *path* relative to *wd* (paths from ``setup()`` are relative to it already)."""
    p = Path(path)
    if p.is_absolute():
        return str(p.relative_to(wd))
    return os.path.normpath(path)


def setup_simulation(
    assembly_name: str,
    wd: str | Path,
    currents: dict[str, float],
    *,
    model: str,
    magnet: str | None = None,
    db_path: str | Path | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    method: str = "cfpdes",
    geom: str = "Axi",
    cooling: str = "mean",
    static: bool = True,
    nonlinear: bool = False,
    force: bool = False,
    debug: bool = False,
    verbose: bool = False,
) -> dict:
    """Write a Feel++ setup directory for an assembly or one of its magnets.

    Parameters
    ----------
    assembly_name : str
        Assembly name in the ``assemblies`` table (e.g. ``"M9_A230801_00"``).
    wd : str or Path
        Output directory; created if missing, refused if not empty unless
        *force* is set.
    currents : dict of str to float
        Current per magnet [A]; exactly one entry per magnet of the target.
    model : str
        python_magnetsetup model (e.g. ``"thelec"``, ``"thmag_hcurl"``).
    magnet : str, optional
        Set up only this magnet of the assembly; default: the whole assembly.
    db_path : str or Path, optional
        DuckDB file, opened read-only. Give either *db_path* or *con*.
    con : duckdb.DuckDBPyConnection, optional
        An open connection or cursor, used as is and left open.
    method : str, optional
        Solver method (default ``"cfpdes"``).
    geom : str, optional
        ``"Axi"`` (default) or ``"3D"``.
    cooling : str, optional
        Cooling model for the thermal models (default ``"mean"``).
    static : bool, optional
        Static (default) or transient setup.
    nonlinear : bool, optional
        Nonlinear materials.
    force : bool, optional
        Write into a non-empty *wd*.
    debug, verbose : bool, optional
        Forwarded to ``setup()``.

    Returns
    -------
    dict
        The keys of python_magnetdb's ``Simulation.setup_state``:
        ``yamlfile``, ``cfgfile``, ``jsonfile``, ``xaofile``, ``meshfile``,
        ``csvfiles``, as paths relative to *wd*.

    Raises
    ------
    ValueError
        Neither or both of *db_path* and *con*; *wd* not empty; unknown
        assembly or magnet; currents missing or for unknown magnets; magnets
        of the assembly YAML not matching the DB.
    """
    if (db_path is None) == (con is None):
        raise ValueError("give exactly one of db_path or con")
    wd = Path(wd).resolve()
    if wd.exists() and any(wd.iterdir()) and not force:
        raise ValueError(f"{wd} is not empty (use force / --force)")

    import python_magnetsetup.setup as magnetsetup
    from python_magnetsetup.config import appenv

    import stress_map

    owns_con = con is None
    if owns_con:
        con = duckdb.connect(str(db_path), read_only=True)
    db_arg = str(db_path) if db_path is not None else ""
    tmpdir = None
    cwd = os.getcwd()
    try:
        _housing, magnet_configs = stress_map.load_assembly_config_from_duckdb(
            assembly_name, db_arg, con=con
        )
        configs = {name: config for name, config, _geo in magnet_configs}
        if magnet is not None and magnet not in configs:
            raise ValueError(
                f"magnet {magnet!r} is not linked to assembly {assembly_name!r} "
                f"(magnets: {', '.join(configs)})"
            )
        targets = [magnet] if magnet is not None else list(configs)
        missing = [name for name in targets if name not in currents]
        unknown = [name for name in currents if name not in targets]
        if missing or unknown:
            raise ValueError(
                f"currents must be given for exactly {', '.join(targets)}"
                + (f"; missing: {', '.join(missing)}" if missing else "")
                + (f"; unknown: {', '.join(unknown)}" if unknown else "")
            )
        types = dict(
            con.execute(
                "SELECT name, type FROM magnets WHERE list_contains(?, name)", [targets]
            ).fetchall()
        )
        setup_currents = {
            name: {"value": float(currents[name]), "type": types.get(name)} for name in targets
        }

        tmpdir = stress_map.prepare_geometry_directory(
            assembly_name,
            {"name": assembly_name, "magnets": list(configs.values())},
            db_arg,
            con=con,
        )
        geometries = tmpdir / "data" / "geometries"
        if magnet is not None:
            confdata = configs[magnet]
        else:
            order = _assembly_magnet_order(geometries / f"{assembly_name}.yaml")
            if sorted(order) != sorted(configs):
                raise ValueError(
                    f"magnets of {assembly_name}.yaml ({', '.join(order)}) do not match "
                    f"the DB magnets ({', '.join(configs)})"
                )
            confdata = {"name": assembly_name, "magnets": [{name: configs[name]} for name in order]}

        data_dir = str(tmpdir / "data")
        env = appenv(
            envfile=None,
            url_api=data_dir,
            yaml_repo=str(geometries),
            cad_repo=f"{data_dir}/cad",
            mesh_repo=data_dir,
            simage_repo=data_dir,
            mrecord_repo=data_dir,
            optim_repo=data_dir,
        )
        args = Namespace(
            method=method,
            time="static" if static else "transient",
            geom=geom,
            model=model,
            cooling=cooling,
            nonlinear=nonlinear,
            wd=str(wd),
            debug=debug,
            verbose=verbose,
        )
        target_name = magnet if magnet is not None else assembly_name
        wd.mkdir(parents=True, exist_ok=True)
        try:
            yamlfile, cfgfile, jsonfile, xaofile, meshfile, csvfiles = magnetsetup.setup(
                env, args, confdata, target_name, setup_currents
            )
        finally:
            os.chdir(cwd)  # setup() changes directory and never changes back

        shutil.copytree(geometries, wd / "geometries", dirs_exist_ok=True)
    finally:
        os.chdir(cwd)
        if owns_con:
            con.close()
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)

    setup_state = {
        "yamlfile": yamlfile,
        "cfgfile": _relative(cfgfile, wd),
        "jsonfile": _relative(jsonfile, wd),
        "xaofile": xaofile,
        "meshfile": meshfile,
        "csvfiles": [_relative(f, wd) for f in csvfiles],
    }
    record = {
        "uid": str(uuid.uuid4()),
        "kind": "fem",
        "target_type": "magnet" if magnet is not None else "assembly",
        "target_name": target_name,
        "method": method,
        "model": model,
        "geometry": geom,
        "cooling": cooling,
        "static": static,
        "non_linear": nonlinear,
        "currents": {name: value["value"] for name, value in setup_currents.items()},
        "provenance": {
            "db_path": str(db_path) if db_path is not None else None,
            "db_sha256": _sha256_file(Path(db_path)) if db_path is not None else None,
            "versions": {
                "python_magnetsetup": _version("python_magnetsetup"),
                "python_magnetgeo": _version("python_magnetgeo"),
            },
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "geometry_fingerprint": _geometry_fingerprint(wd / "geometries"),
        "setup_state": setup_state,
    }
    with open(wd / SETUP_JSON, "w") as f:
        json.dump(record, f, indent=2)
    return setup_state


def _current_arg(text: str) -> tuple[str, float]:
    """argparse type for ``--current NAME=VALUE``."""
    try:
        return _parse_current(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description="Write a Feel++ simulation setup for a DuckDB assembly or one of its magnets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"DuckDB file, opened read-only (default: {DEFAULT_DB})")
    parser.add_argument("--assembly", required=True, help="Assembly name (assemblies table)")
    parser.add_argument("--magnet", default=None,
                        help="Set up only this magnet of the assembly")
    parser.add_argument("--current", action="append", type=_current_arg, required=True,
                        metavar="NAME=VALUE",
                        help="Current [A] of one magnet; repeat for each magnet of the target")
    parser.add_argument("--method", default="cfpdes", help="Solver method (default: cfpdes)")
    parser.add_argument("--model", required=True,
                        help="python_magnetsetup model, e.g. thelec, thmag_hcurl")
    parser.add_argument("--geom", default="Axi", help="Axi or 3D (default: Axi)")
    parser.add_argument("--cooling", default="mean",
                        help="Cooling model for thermal models (default: mean)")
    parser.add_argument("--transient", action="store_true", help="Transient instead of static")
    parser.add_argument("--nonlinear", action="store_true", help="Nonlinear materials")
    parser.add_argument("--wd", required=True, help="Output directory")
    parser.add_argument("--force", action="store_true", help="Write into a non-empty --wd")
    parser.add_argument("--debug", action="store_true",
                        help="Verbose setup output, and tracebacks on errors")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    """Command-line entry point."""
    args = _parse_args(argv)
    currents: dict[str, float] = {}
    for name, value in args.current:
        if name in currents:
            raise SystemExit(f"error: --current {name} given twice")
        currents[name] = value
    try:
        state = setup_simulation(
            args.assembly,
            args.wd,
            currents,
            model=args.model,
            magnet=args.magnet,
            db_path=args.db,
            method=args.method,
            geom=args.geom,
            cooling=args.cooling,
            static=not args.transient,
            nonlinear=args.nonlinear,
            force=args.force,
            debug=args.debug,
        )
    # CLI boundary: python_magnetsetup raises bare Exception in places.
    except Exception as exc:
        if args.debug:
            raise
        raise SystemExit(f"error: {exc}") from exc
    wd = Path(args.wd)
    print(f"wrote {wd / state['cfgfile']}")
    print(f"wrote {wd / state['jsonfile']}")
    print(f"wrote {wd / SETUP_JSON}")


if __name__ == "__main__":
    main()
