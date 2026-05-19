"""
student_stress_map.py
=====================
Demonstrates how to compute a hoop stress map for a magnet using the
student DuckDB database and local YAML geometry files, without any
Django or MagnetDB infrastructure.

This script replicates the full chain of:

    python_magnetdb/actions/compute_stress_map_chart.py
    python_magnetdb/actions/generate_simulation_config.py
    python_magnetdb/actions/generate_magnet_directory.py
    python_magnetdb/actions/object_geometries.py

replacing only the Django/ORM data access layer with DuckDB queries.
Everything from magnet_setup() onwards is identical to the production code.

MagnetDB production chain
--------------------------
    Django ORM (Magnet model)
        │
        ├── generate_magnet_config(magnet_id)
        │       → config dict {"geom": ..., "Helix": [...], "Ring": [...]}
        │
        ├── generate_site_directory(site_id, tempdir)
        │       → writes {site_name}.yaml files to tempdir/data/geometries/
        │
        ├── appenv(yaml_repo=..., ...)
        │       → environment object pointing at file locations
        │
        ├── msite_setup(env, config, debug)
        │       → (Tubes, Helices, OHelices, BMagnets, UMagnets, Shims)
        │
        └── compute_stress_map_chart(data, i_h, i_b, i_s, magnet_type)
                → {"x": [...], "y": [...], "ymax": [...]}

Student chain (this script)
-----------------------------
    DuckDB + YAML files on disk
        │
        ├── load_site_config_from_duckdb(site_name)        ← replaces generate_magnet_config
        │
        ├── prepare_geometry_directory(site_name, ...)   ← replaces generate_site_directory
        │
        ├── appenv(...)                                    ← identical
        │
        ├── msite_setup(env, config, debug)               ← identical
        │
        └── compute_stress_map(data, i_h, i_b, i_s)       ← identical logic

Required files on disk (shipped with the student dataset)
----------------------------------------------------------
    student_data/
    ├── student_magnetdb.duckdb
    ├── geometries/               ← YAML files from python_magnetsetup/data/geometries/
    │   ├── HL-31.yaml
    │   ├── HL-31_H1.yaml
    │   ├── ...
    │   ├── Ring-H1H2.yaml
    │   └── ...
    └── records/
        └── *.txt

Requirements
------------
    pip install duckdb pandas matplotlib
    # Plus system packages:
    #   python3-magnettools  (provides magnettools.magnettools, magnettools.Bmap)
    #   python_magnetsetup   (provides python_magnetsetup.ana, python_magnetsetup.config)

Note on Rpe units
-----------------
In the DuckDB database, Rpe is stored as-is from the seed files.
Some seed files store it in Pa (e.g. 481e6), others in MPa (e.g. 481).
The config passed to magnet_setup() carries this value unchanged, exactly
as generate_simulation_config.py does. Verify the unit for your specific
dataset before interpreting ratio_rpe values.
"""

import argparse
import enum
import json
import re
import shutil
import tempfile
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import magnettools.Bmap as bmap
import magnettools.magnettools as mt
from python_magnetrun.data_dirs import PUPITRE_DATA_DIR
from python_magnetrun.magnetdata import load_magnetdata
from python_magnetrun.runetl import prepareData
from python_magnetsetup.ana import msite_setup
from python_magnetsetup.config import appenv


class PartType(str, enum.Enum):
    SUPRA = "supra"
    HELIX = "helix"
    RING = "ring"
    SCREEN = "screen"
    LEAD = "lead"
    BITTER = "bitter"

    @classmethod
    def choices(cls):
        return [(item.value, item.name) for item in cls]


class MagnetType(str, enum.Enum):
    INSERT = "insert"
    BITTERS = "bitters"
    SUPRAS = "supras"
    HYBRID = "hybrid"

    @classmethod
    def choices(cls):
        return [(item.value, item.name) for item in cls]


# ---------------------------------------------------------------------------
# Step 1 — Build config dict from DuckDB
#           Replicates generate_magnet_config() in generate_simulation_config.py
# ---------------------------------------------------------------------------


def _format_material_row(row: dict) -> dict:
    """Map DuckDB column names to the format expected by magnet_setup().
    Mirrors format_material() in generate_simulation_config.py exactly.
    """
    return {
        "Tref": row["t_ref"],
        "VolumicMass": row["volumic_mass"],
        "alpha": row["alpha"],
        "ElectricalConductivity": row["electrical_conductivity"],
        "MagnetPermeability": row["magnet_permeability"],
        "Poisson": row["poisson"],
        "Rpe": row["rpe"],  # unit: see module docstring
        "SpecificHeat": row["specific_heat"],
        "ThermalConductivity": row["thermal_conductivity"],
        "Young": row["young"],
        "CoefDilatation": row["expansion_coefficient"],
        "nuance": row["nuance"],
    }


def load_site_config_from_duckdb(
    site_name: str,
    db_path: str,
    magnet_override: str | None = None,
) -> tuple[str, list[tuple[str, dict, str | None]]]:
    """
    Return (housing, [(magnet_name, config, geometry_data), ...]) for every magnet at a site.

    Resolve the site → magnet mapping and load the full part/material config
    in a single DB connection.  All magnets are returned regardless of
    commissioned/decommissioned status, ordered by commissioned_at DESC.

    Parameters
    ----------
    site_name       : Site name registered in DuckDB (e.g. "M9")
    db_path         : Path to the DuckDB file
    magnet_override : Explicit magnet name; returns only that magnet.
                      A warning is printed if it is not linked to the site.

    Returns
    -------
    housing : from sites.housing (e.g. "M9")
    magnets : list of (magnet_name, config, geometry_data) triples — config is a
              dict ready for magnet_setup() / prepare_geometry_directory();
              geometry_data is the JSON-serialised python_magnetgeo object stored
              in magnets.geometry_data (None if not yet imported with --geometry).

    Raises
    ------
    ValueError : site not found, no magnet linked, MAT_ISOLANT missing,
                 or no magnet has parts in the DB.
    """
    con = duckdb.connect(db_path, read_only=True)

    # ── 1. Site housing ───────────────────────────────────────────────────────
    site_row = con.execute(
        "SELECT housing FROM sites WHERE name = ?", [site_name]
    ).fetchone()
    if site_row is None:
        con.close()
        raise ValueError(
            f"Site '{site_name}' not found in DB. "
            "Check the site name and ensure seeds are loaded."
        )
    housing = site_row[0]

    # ── 2. Resolve magnet list ────────────────────────────────────────────────
    rows = con.execute(
        """
        SELECT magnet_name
        FROM site_magnets
        WHERE site_name = ?
        ORDER BY commissioned_at DESC NULLS LAST
        """,
        [site_name],
    ).fetchall()
    if not rows:
        con.close()
        raise ValueError(
            f"No magnet linked to site '{site_name}'. "
            "Check the site name and ensure seeds are loaded."
        )
    magnet_names = [r[0] for r in rows]

    # ── 3. Insulator material (shared by every part entry) ────────────────────
    isolant_row = con.execute("""
        SELECT t_ref, volumic_mass, alpha, electrical_conductivity,
               magnet_permeability, poisson, rpe, specific_heat,
               thermal_conductivity, young, expansion_coefficient, nuance
        FROM materials WHERE name = 'MAT_ISOLANT'
    """).fetchone()
    if isolant_row is None:
        con.close()
        raise ValueError(
            "MAT_ISOLANT not found in the database. "
            "Run seeds_to_duckdb.py to populate structural data first."
        )
    insulator_payload = _format_material_row(
        dict(
            zip(
                [
                    "t_ref",
                    "volumic_mass",
                    "alpha",
                    "electrical_conductivity",
                    "magnet_permeability",
                    "poisson",
                    "rpe",
                    "specific_heat",
                    "thermal_conductivity",
                    "young",
                    "expansion_coefficient",
                    "nuance",
                ],
                isolant_row,
            )
        )
    )

    # ── 4. Build config per magnet ────────────────────────────────────────────
    col_names = [
        "part_name",
        "part_type",
        "rank",
        "t_ref",
        "volumic_mass",
        "alpha",
        "electrical_conductivity",
        "magnet_permeability",
        "poisson",
        "rpe",
        "specific_heat",
        "thermal_conductivity",
        "young",
        "expansion_coefficient",
        "nuance",
    ]
    results: list[tuple[str, dict, str | None]] = []
    for magnet_name in magnet_names:
        parts = con.execute(
            """
            SELECT
                p.name          AS part_name,
                p.type          AS part_type,
                mp.rank,
                mat.t_ref, mat.volumic_mass, mat.alpha,
                mat.electrical_conductivity, mat.magnet_permeability,
                mat.poisson, mat.rpe, mat.specific_heat,
                mat.thermal_conductivity, mat.young,
                mat.expansion_coefficient, mat.nuance
            FROM magnet_parts mp
            JOIN parts   p   ON p.name  = mp.part_name
            JOIN magnets m   ON m.name  = mp.magnet_name
            LEFT JOIN materials mat ON mat.name = p.material_name
            WHERE m.name = ?
            ORDER BY mp.rank
            """,
            [magnet_name],
        ).fetchall()

        if not parts:
            print(f"  [WARN] Magnet '{magnet_name}' has no parts in the DB — skipping.")
            continue

        geo_row = con.execute(
            "SELECT geometry_data FROM magnets WHERE name = ?", [magnet_name]
        ).fetchone()
        geometry_data: str | None = geo_row[0] if geo_row else None

        config: dict = {"geom": f"{magnet_name}.yaml"}
        for row in parts:
            d = dict(zip(col_names, row))
            key = d["part_type"].capitalize()  # "Helix", "Ring", "Bitter", "Lead"
            if key not in config:
                config[key] = []
            config[key].append(
                {
                    "geom": f"{d['part_name']}.yaml",
                    "material": _format_material_row(d),
                    "insulator": insulator_payload,
                }
            )
        results.append((magnet_name, config, geometry_data))

    con.close()

    if not results:
        raise ValueError(
            f"No magnet with parts found for site '{site_name}'. "
            "Check the magnet names and ensure seeds are loaded."
        )

    return housing, results


# ---------------------------------------------------------------------------
# Step 1b — Generate MSite YAML from DuckDB geometry_data + site offsets
#            Mirrors Site.geometry_config_to_json() in python_magnetdb/models.py
# ---------------------------------------------------------------------------


def geometry_config_to_yaml(
    site_name: str,
    db_path: str,
    output_dir: str | Path | None = None,
    geometries_dir: str | Path | None = None,
) -> str:
    """
    Build a python_magnetgeo MSite from the site's magnet geometry_data and
    site_magnets positional offsets, then return its YAML representation.

    Mirrors ``Site.geometry_config_to_json()`` in python_magnetdb/models.py,
    replacing the Django ORM with DuckDB queries.

    Each magnet's assembly geometry is resolved in this order:

    1. ``magnets.geometry_data`` — JSON-serialised python_magnetgeo object stored
       at import time via ``magnetdb.py magnet add --geometry <yaml>``.
    2. ``geometries_dir`` fallback — load ``{magnet_name}.yaml`` from this
       directory (for DBs populated without ``--geometry``).

    Parameters
    ----------
    site_name      : Site name as registered in DuckDB (e.g. ``"M9_M19061901_0"``)
    db_path        : Path to the DuckDB file
    output_dir     : If given, also write ``<site_name>.yaml`` to this directory
                     via ``MSite.write_to_yaml()``.  The YAML string is returned
                     regardless.
    geometries_dir : Fallback directory containing ``{magnet_name}.yaml``
                     assembly-level files (Insert, Bitters, …) for magnets that
                     were imported without ``--geometry``.

    Returns
    -------
    str
        YAML representation of the ``MSite``.

    Raises
    ------
    ValueError
        If the site is not found, has no magnets, or a magnet's assembly
        geometry cannot be resolved from either the DB or *geometries_dir*.
    """
    import yaml as _yaml
    from python_magnetgeo.MSite import MSite

    print(f"  ── Preparing geometry directory for site '{site_name}' …")
    geo_dir = Path(geometries_dir) if geometries_dir else None
    print(f"geo_dir: {geo_dir}")

    con = duckdb.connect(db_path, read_only=True)

    if (
        con.execute("SELECT 1 FROM sites WHERE name = ?", [site_name]).fetchone()
        is None
    ):
        con.close()
        raise ValueError(f"Site '{site_name}' not found in DB.")

    rows = con.execute(
        """
        SELECT m.name, m.geometry_data, sm.z_offset, sm.r_offset, sm.parallax
        FROM site_magnets sm
        JOIN magnets m ON m.name = sm.magnet_name
        WHERE sm.site_name = ?
        ORDER BY sm.commissioned_at DESC NULLS LAST, m.name
    """,
        [site_name],
    ).fetchall()
    con.close()

    if not rows:
        raise ValueError(f"No magnets linked to site '{site_name}'.")

    magnets = []
    z_offset: list[float] = []
    r_offset: list[float] = []
    paralax: list[float] = []

    for magnet_name, geometry_data, z, r, p in rows:
        print(f"\t- Processing magnet '{magnet_name}' …")
        yaml_str = magnet_geometry_config_to_yaml(
            magnet_name, db_path, output_dir=geo_dir
        )
        magnet_obj = _yaml.load(yaml_str, Loader=_yaml.FullLoader)
        if output_dir is not None:
            magnet_obj.write_to_yaml(str(output_dir))
            print(f"   Written {Path(output_dir) / magnet_name}.yaml")

        magnets.append(magnet_obj)
        z_offset.append(float(z or 0.0))
        r_offset.append(float(r or 0.0))
        paralax.append(float(p or 0.0))

    obj = MSite(
        name=site_name,
        magnets=magnets,
        screens=[],
        z_offset=z_offset,
        r_offset=r_offset,
        paralax=paralax,
    )

    if output_dir is not None:
        obj.write_to_yaml(str(output_dir))
        print(f"   Written {Path(output_dir) / site_name}.yaml")

    return obj.to_yaml()


# ---------------------------------------------------------------------------
# Step 1c — Generate magnet assembly YAML from DuckDB geometry_data
#            Mirrors Magnet.geometry_config_to_yaml() in python_magnetdb/models.py
# ---------------------------------------------------------------------------


def magnet_geometry_config_to_yaml(
    magnet_name: str,
    db_path: str,
    output_dir: str | Path | None = None,
) -> str:
    """
    Build a python_magnetgeo assembly object from a magnet's parts and return
    its YAML representation.

    Mirrors ``Magnet.geometry_config_to_yaml()`` in python_magnetdb/models.py,
    replacing the Django ORM with DuckDB queries.  The assembly object
    (Insert, Bitters, or Supras) is reconstructed from the individual part
    geometry stored in ``parts.geometry_data``, exactly as the Django method
    builds it from ``magnet_part.part.geometry_config``.

    Because the DuckDB schema does not store ``angle``, ``inner_bore``, or
    ``outer_bore``, angles default to 0 and bore values are derived
    automatically from the parts' geometry (Insert/Bitters/Supras auto-compute
    when passed ``innerbore=0``/``outerbore=0``).

    Parameters
    ----------
    magnet_name : Magnet name as registered in DuckDB (e.g. ``"M19061901"``)
    db_path     : Path to the DuckDB file
    output_dir  : If given, also write ``<magnet_name>.yaml`` to this directory
                  via ``write_to_yaml()``.  The YAML string is returned regardless.

    Returns
    -------
    str
        YAML representation of the magnet assembly object.

    Raises
    ------
    ValueError
        If the magnet is not found, has no parts, or a part has no geometry_data.
    """
    import copy
    import json as _json
    from python_magnetgeo.deserialize import unserialize_object
    from python_magnetgeo.Insert import Insert
    from python_magnetgeo.Bitters import Bitters
    from python_magnetgeo.Supras import Supras

    print(
        f"  ── Generating magnet assembly YAML for '{magnet_name}' in output directory '{output_dir}' …",
        flush=True,
    )

    con = duckdb.connect(db_path, read_only=True)

    magnet_row = con.execute(
        "SELECT type FROM magnets WHERE name = ?", [magnet_name]
    ).fetchone()
    if magnet_row is None:
        con.close()
        raise ValueError(f"Magnet '{magnet_name}' not found in DB.")
    magnet_type = magnet_row[0]

    parts_rows = con.execute(
        """
        SELECT p.name, p.type, p.geometry_data
        FROM magnet_parts mp
        JOIN parts p ON p.name = mp.part_name
        WHERE mp.magnet_name = ?
        ORDER BY mp.rank
        """,
        [magnet_name],
    ).fetchall()
    con.close()

    if not parts_rows:
        raise ValueError(f"Magnet '{magnet_name}' has no parts in DB.")

    print(
        f"  Processing {magnet_type.upper()} magnet '{magnet_name}' "
        f"with {len(parts_rows)} part(s) …"
    )

    if magnet_type == MagnetType.INSERT:
        helices, hangles, rings, rangles, currentleads = [], [], [], [], []
        for part_name, part_type, geometry_data in parts_rows:
            if not geometry_data:
                raise ValueError(
                    f"Part '{part_name}' has no geometry_data. "
                    "Re-import with 'magnetdb.py magnet add --geometry'."
                )
            config = copy.deepcopy(_json.loads(geometry_data))
            config["name"] = part_name
            obj = unserialize_object(config)
            if part_type == PartType.HELIX:
                helices.append(obj)
                hangles.append(0)
            elif part_type == PartType.RING:
                rings.append(obj)
                rangles.append(0)
            elif part_type == PartType.LEAD:
                currentleads.append(obj)
            else:
                raise ValueError(
                    f"Unsupported part type '{part_type}' for '{part_name}' in "
                    f"INSERT magnet '{magnet_name}'. Expected HELIX, RING, or LEAD."
                )
        assembly = Insert(
            name=magnet_name,
            helices=helices,
            rings=rings,
            currentleads=currentleads,
            hangles=hangles,
            rangles=rangles,
            innerbore=0,
            outerbore=0,
        )

    elif magnet_type == MagnetType.BITTERS:
        magnets, currentleads = [], []
        for part_name, part_type, geometry_data in parts_rows:
            if not geometry_data:
                raise ValueError(
                    f"Part '{part_name}' has no geometry_data. "
                    "Re-import with 'magnetdb.py magnet add --geometry'."
                )
            config = copy.deepcopy(_json.loads(geometry_data))
            config["name"] = part_name
            obj = unserialize_object(config)
            if part_type == PartType.BITTER:
                magnets.append(obj)
            elif part_type == PartType.LEAD:
                currentleads.append(obj)
            else:
                raise ValueError(
                    f"Unsupported part type '{part_type}' for '{part_name}' in "
                    f"BITTERS magnet '{magnet_name}'. Expected BITTER or LEAD."
                )
        assembly = Bitters(
            name=magnet_name,
            magnets=magnets,
            innerbore=0,
            outerbore=0,
        )

    elif magnet_type == MagnetType.SUPRAS:
        magnets, currentleads = [], []
        for part_name, part_type, geometry_data in parts_rows:
            if not geometry_data:
                raise ValueError(
                    f"Part '{part_name}' has no geometry_data. "
                    "Re-import with 'magnetdb.py magnet add --geometry'."
                )
            config = copy.deepcopy(_json.loads(geometry_data))
            config["name"] = part_name
            obj = unserialize_object(config)
            if part_type == PartType.SUPRA:
                magnets.append(obj)
            elif part_type == PartType.LEAD:
                currentleads.append(obj)
            else:
                raise ValueError(
                    f"Unsupported part type '{part_type}' for '{part_name}' in "
                    f"SUPRAS magnet '{magnet_name}'. Expected SUPRA or LEAD."
                )
        assembly = Supras(
            name=magnet_name,
            magnets=magnets,
            innerbore=0,
            outerbore=0,
        )

    else:
        raise ValueError(
            f"Unsupported magnet type '{magnet_type}' for '{magnet_name}'. "
            f"Expected one of: {[t.value for t in MagnetType if t != MagnetType.HYBRID]}."
        )

    if output_dir is not None:
        assembly.write_to_yaml(str(output_dir))
        print(f"   Written {Path(output_dir) / magnet_name}.yaml")

    print(f"  Generated assembly YAML for magnet '{magnet_name}'.")
    # print(f"  Assembly summary: {assembly.to_yaml()}")
    return assembly.to_yaml()


# ---------------------------------------------------------------------------
# Step 2 — Prepare geometry directory on disk
#           Replicates generate_site_directory() without Django
# ---------------------------------------------------------------------------


def prepare_geometry_directory(
    site_name: str, config: dict, db_path: str, geometries_dir: str | Path | None = None
) -> Path:
    """
    Build a temporary directory tree that magnet_setup() can read:

        <tempdir>/
        ├── config.json
        └── data/
            ├── geometries/
            │   ├── {magnet_name}.yaml      ← top-level insert/bitters geometry
            │   ├── {part_name}.yaml        ← one file per part
            │   └── ...
            └── cad/

    The magnet name is derived from config["geom"] (e.g. "M19061901.yaml" → "M19061901").
    site_name is used only for the temp-directory prefix.

    Geometry YAML files are written from one of three sources (tried in order):
    1. ``geometry_data`` argument — JSON already fetched by load_site_config_from_duckdb;
       no extra DB connection needed.
    2. ``geometry_data`` column in DuckDB — fetched via geometry_config_to_yaml when
       geometry_data argument is None.
    3. ``geometries_dir`` fallback — a directory of pre-extracted YAML files
       (used for seed-based data that pre-dates geometry_data storage).

    Returns the Path of the created temp directory (caller should clean up).
    """

    print(f"\n── Preparing geometry directory for magnet '{config.keys()}' …")

    src_dir = Path(geometries_dir) if geometries_dir else None
    if src_dir is not None and not src_dir.is_dir():
        print(
            f"  [WARN] geometries_dir not found: {src_dir} — will rely on DB-stored geometry_data."
        )
        src_dir = None

    tempdir = Path(tempfile.mkdtemp(prefix=f"magnetdb_student_{site_name}_"))
    data_geom = tempdir / "data" / "geometries"
    data_geom.mkdir(parents=True)
    (tempdir / "data" / "cad").mkdir()

    geometry_data = geometry_config_to_yaml(
        site_name, db_path, output_dir=data_geom, geometries_dir=src_dir
    )
    with open(data_geom / f"{site_name}.yaml", "w") as f:
        f.write(geometry_data)

    # TODO: add save per magnet

    # Write config.json alongside the data/ tree
    with open(tempdir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    return tempdir


# ---------------------------------------------------------------------------
# Step 3 — Load MagnetTools objects
#           Replicates get_magnet_data() in object_geometries.py without Django
# ---------------------------------------------------------------------------


def load_magnettools(config: dict, tempdir: Path, debug: bool = False) -> tuple:
    """
    Call magnet_setup() from python_magnetsetup with the prepared directory,
    returning (Tubes, Helices, OHelices, BMagnets, UMagnets, Shims).

    This is identical to the body of get_magnet_data() in object_geometries.py.
    """
    data_dir = str(tempdir / "data")
    env = appenv(
        envfile=None,
        url_api=data_dir,
        yaml_repo=f"{data_dir}/geometries",
        cad_repo=f"{data_dir}/cad",
        mesh_repo=data_dir,
        simage_repo=data_dir,
        mrecord_repo=data_dir,
        optim_repo=data_dir,
    )
    print(f"load_magnettools: env={env}, config={config}")
    return msite_setup(env, config, debug)


# ---------------------------------------------------------------------------
# Step 4 — Compute hoop stress time series from a pupitre file
#           Fast vectorised alternative to the row-by-row compute_stress_map_chart
# ---------------------------------------------------------------------------


def validate_fast_from_pupitre(
    data: tuple,
    pupitre_file: str,
    housing: str,
    magnet_type: str = "H",
    check: bool = False,
    use_mrun: bool = False,
    site: str = "",
) -> pd.DataFrame:
    """
    Fast vectorised hoop-stress computation over a pupitre time series.

    Precomputes, at unit current (1 A), for each tube i:
      - r[i]        : inner radius of the tube
      - j_unit[i]   : current density at inner radius for IH = 1 A
      - Bz_tubes[i] : Bz at (r[i], 0) produced by all tubes at IH = 1 A
      - Bz_bmag[i]  : Bz at (r[i], 0) produced by all BMagnets at IB = 1 A
      - Bz_umag[i]  : Bz at (r[i], 0) produced by all UMagnets at IS = 1 A

    Hoop stress estimate for tube i at time step k:
      sigma_i(k) = r_i * j_unit_i * IH(k)
                       * (Bz_tubes_i * IH(k) + Bz_bmag_i * IB(k) + Bz_umag_i * IS(k))

    All per-timestep work is pure NumPy — no C++ calls inside the time loop.

    Parameters
    ----------
    data         : MagnetTools tuple from load_magnettools()
    pupitre_file : Path to the pupitre file (.txt, .tdms, or .csv)
    housing      : Housing name (e.g. "M9")
    magnet_type  : "H" for insert helices, "B" for bitters (used in sanity check)
    check        : If True, validate fast results against bmap.getHoop row by row
    use_mrun     : If True, load via python_magnetrun.MagnetRun.load_mrun() instead
                   of load_magnetdata() + prepareData(); supports .tdms in addition
                   to .txt/.csv and handles path auto-resolution.
    site         : Site name forwarded to load_mrun() (ignored when use_mrun=False)

    Returns
    -------
    DataFrame with time series columns: t, IH, IB, [IS,] H1_fast, H2_fast, ...
    """
    Tubes, Helices, OHelices, BMagnets, UMagnets, Shims = data
    icurrents = mt.get_currents(Tubes, Helices, BMagnets, UMagnets)
    n_tubes = len(Tubes)

    # ------------------------------------------------------------------
    # 1. Precompute unit-current quantities for every tube
    # ------------------------------------------------------------------
    r = np.zeros(n_tubes)
    j_unit = np.zeros(n_tubes)
    Bz_tubes = np.zeros(n_tubes)
    Bz_bmag = np.zeros(n_tubes) if len(BMagnets) else None
    Bz_umag = np.zeros(n_tubes) if len(UMagnets) else None

    def _zero_vcurrents():
        v = mt.DoubleVector(icurrents)
        for i in range(len(v)):
            v[i] = 0.0
        return v

    num = 0
    if len(Tubes):
        v = _zero_vcurrents()
        v[num] = 1.0  # IH = 1 A
        mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices, v)
        for i, Tube in enumerate(Tubes):
            r[i] = Tube.get_R_int()
            n_elem = Tube.get_n_elem()
            mid_elem = int(n_elem / 2) if (n_elem % 2) == 0 else int((n_elem + 1) / 2)
            j_unit[i] = Helices[mid_elem + Tube.get_index()].get_CurrentDensity()
        Bz_tubes = np.array(
            [mt.MagneticField(Tubes, Helices, BMagnets, UMagnets, ri, 0)[1] for ri in r]
        )
        num += 1

    if len(BMagnets):
        v = _zero_vcurrents()
        v[num] = 1.0  # IB = 1 A
        mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices, v)
        Bz_bmag = np.array(
            [mt.MagneticField(Tubes, Helices, BMagnets, UMagnets, ri, 0)[1] for ri in r]
        )
        num += 1

    if len(UMagnets):
        v = _zero_vcurrents()
        v[num] = 1.0  # IS = 1 A
        mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices, v)
        Bz_umag = np.array(
            [mt.MagneticField(Tubes, Helices, BMagnets, UMagnets, ri, 0)[1] for ri in r]
        )

    print(f"   Precomputed unit-current quantities for {n_tubes} tube(s).")

    # ------------------------------------------------------------------
    # 2. Load pupitre data
    # ------------------------------------------------------------------
    print(f"\n── Loading pupitre data: {pupitre_file} …")
    if use_mrun:
        from python_magnetrun.MagnetRun import load_mrun

        mrun = load_mrun(pupitre_file, housing=housing, site=site)
        df = mrun.MagnetData.Data
    else:
        mdata = load_magnetdata(pupitre_file)
        prepareData(mdata, housing)
        df = mdata.Data

    n_t = len(df)
    IH_arr = df["IH"].to_numpy() if "IH" in df.columns else np.zeros(n_t)
    IB_arr = df["IB"].to_numpy() if "IB" in df.columns else np.zeros(n_t)
    IS_arr = df["IS"].to_numpy() if "IS" in df.columns else np.zeros(n_t)

    Bz_bmag_arr = Bz_bmag if Bz_bmag is not None else np.zeros(n_tubes)
    Bz_umag_arr = Bz_umag if Bz_umag is not None else np.zeros(n_tubes)

    # ------------------------------------------------------------------
    # 3. Vectorised hoop stress — shapes (N, 1) broadcast against (1, T)
    #    sigma[i, k] = r[i] * (j_unit[i] * IH[k])
    #                        * (Bz_tubes[i]*IH[k] + Bz_bmag[i]*IB[k] + Bz_umag[i]*IS[k])
    # ------------------------------------------------------------------
    IH = IH_arr[np.newaxis, :]  # (1, T)
    IB = IB_arr[np.newaxis, :]
    IS = IS_arr[np.newaxis, :]

    r2 = r[:, np.newaxis]  # (N, 1)
    j_unit2 = j_unit[:, np.newaxis]
    Bz_t2 = Bz_tubes[:, np.newaxis]
    Bz_b2 = Bz_bmag_arr[:, np.newaxis]
    Bz_u2 = Bz_umag_arr[:, np.newaxis]

    Bz_total = Bz_t2 * IH + Bz_b2 * IB + Bz_u2 * IS  # (N, T)
    j_real = j_unit2 * IH  # (N, T)
    sigma = r2 * j_real * Bz_total  # (N, T) [Pa]
    sigma_MPa = sigma * 1e-6

    # ------------------------------------------------------------------
    # 3b. Optional sanity check: fast sigma_MPa vs bmap.getHoop row by row
    # ------------------------------------------------------------------
    if check:
        print("\n── Sanity check: fast vs bmap.getHoop …")
        mdata_type = {"H": Helices, "B": BMagnets, "S": UMagnets}
        max_err = np.zeros(n_tubes)

        for k, row in enumerate(df.itertuples(index=False)):
            v = _zero_vcurrents()
            num = 0
            if len(Tubes):
                v[num] = row.IH
                num += 1
            if len(BMagnets):
                v[num] = row.IB
                num += 1
            if len(UMagnets):
                v[num] = getattr(row, "IS", 0.0)
            mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices, v)

            headers, hoop_values = bmap.getHoop(
                mdata_type[magnet_type], Tubes, Helices, BMagnets, UMagnets, magnet_type
            )
            ref_df = pd.DataFrame.from_records(hoop_values, columns=headers)
            ref_hoop = ref_df["Hoop[MPa]"].to_numpy()

            for i in range(n_tubes):
                err = abs(sigma_MPa[i, k] - ref_hoop[i])
                max_err[i] = max(max_err[i], err)

        print("   Max absolute error per tube [MPa]:")
        for i in range(n_tubes):
            print(f"     H{i+1}: {max_err[i]:.4e} MPa")

    # ------------------------------------------------------------------
    # 4. Store results in DataFrame
    # ------------------------------------------------------------------
    for i in range(n_tubes):
        df[f"H{i+1}_fast"] = sigma_MPa[i, :]

    return df


def _resolve_pupitre_path(filename: str, pupitre_datadir: str, housing: str) -> str:
    """Resolve a bare pupitre filename to an existing path.

    Search order (mirrors expand_input_files from python_magnetrun.utils.files):
    1. filename as-is (absolute or already has a directory component)
    2. cwd / filename
    3. pupitre_datadir / filename
    4. pupitre_datadir / housing / filename  (housing subdirectory)

    Returns the first path that exists, or filename unchanged if none found.
    """
    p = Path(filename)
    if p.is_absolute() or p.parent != Path("."):
        return filename

    candidates = [
        Path.cwd() / filename,
    ]
    if pupitre_datadir:
        candidates.append(Path(pupitre_datadir) / filename)
        if housing and housing not in ("notdefined", ""):
            candidates.append(Path(pupitre_datadir) / housing / filename)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return filename


def resolve_pupitre_files(
    site_name: str,
    db_path: str,
    files: list[str] | None = None,
    pupitre_datadir: str = "",
    housing: str = "",
) -> list[str]:
    """
    Return the ordered list of pupitre files to process for a site.

    Parameters
    ----------
    site_name      : Site name registered in DuckDB (e.g. "M9")
    db_path        : Path to the DuckDB file
    files          : Explicit file list from --pupitre.
                     - None or empty → fetch all experiment files for the site.
                     - Non-empty     → validate each against the experiments table;
                                       files absent from the table trigger a warning
                                       but are still included.
    pupitre_datadir: Root directory for pupitre files (e.g. PUPITRE_DATA_DIR).
                     Used to resolve bare filenames from the DB.
    housing        : Housing name (e.g. "M9") appended as a subdirectory fallback.

    Returns
    -------
    Non-empty list of resolved file paths, sorted by experiment id (DB order) when
    auto-discovered, or preserving the user's order otherwise.

    Raises
    ------
    ValueError if no files can be returned (empty table and no explicit list).
    """
    con = duckdb.connect(db_path, read_only=True)

    if not files:
        rows = con.execute(
            "SELECT file FROM experiments "
            "WHERE site_name = ? AND file IS NOT NULL "
            "ORDER BY id",
            [site_name],
        ).fetchall()
        con.close()
        result = [r[0] for r in rows if r[0]]
        if not result:
            raise ValueError(
                f"No experiment files found for site '{site_name}'. "
                "Populate the experiments table or pass --pupitre explicitly."
            )
        print(f"   Found {len(result)} experiment file(s) for site '{site_name}'.")
        result = [_resolve_pupitre_path(f, pupitre_datadir, housing) for f in result]
        return result

    # Validate each provided file against the experiments table.
    # Match by exact path OR by basename — the DB may store absolute paths.
    for f in files:
        basename = Path(f).name
        row = con.execute(
            "SELECT 1 FROM experiments "
            "WHERE site_name = ? AND (file = ? OR file LIKE ?)",
            [site_name, f, f"%/{basename}"],
        ).fetchone()
        if row is None:
            print(f"  [WARN] '{f}' not found in experiments for site '{site_name}'.")
    con.close()
    return [_resolve_pupitre_path(f, pupitre_datadir, housing) for f in files]


# ---------------------------------------------------------------------------
# Step 5 — Annotate with Rpe from DuckDB and print summary
# ---------------------------------------------------------------------------


def annotate_with_rpe(result: dict, site_name: str, db_path: str) -> pd.DataFrame:
    """
    Join hoop stress results with Rpe values from DuckDB to compute
    σ/Rpe safety ratios.

    All coil parts (helix, bitter, supra) are fetched for the site, ordered
    helices first then bitters then supras (by rank within each type) to match
    the output order of bmap.getHoop, and aligned positionally with result["x"].
    """
    con = duckdb.connect(db_path, read_only=True)
    rpe_df = con.execute(
        """
        SELECT p.name AS part, mat.rpe, mat.nuance
        FROM magnet_parts mp
        JOIN parts        p  ON p.name  = mp.part_name
        JOIN magnets      m  ON m.name  = mp.magnet_name
        JOIN site_magnets sm ON sm.magnet_name = m.name
        LEFT JOIN materials mat ON mat.name = p.material_name
        WHERE sm.site_name = ?
          AND p.type IN ('helix', 'bitter', 'supra')
        ORDER BY
            CASE p.type WHEN 'helix' THEN 0 WHEN 'bitter' THEN 1 ELSE 2 END,
            mp.rank
        """,
        [site_name],
    ).df()
    con.close()
    print(f"rpe: {rpe_df}")

    df = pd.DataFrame(
        {
            "coil": result["x"],
            "hoop_MPa": result["y"],
            "hoop_max_MPa": result["ymax"],
        }
    )
    df = pd.concat([df, rpe_df.reset_index(drop=True)], axis=1)

    df["rpe"] = df["rpe"] / 1e6  # Pa → MPa
    df["ratio_rpe"] = df["hoop_MPa"] / df["rpe"]
    df["ratio_rpe_max"] = df["hoop_max_MPa"] / df["rpe"]
    return df


# ---------------------------------------------------------------------------
# Step 6 — Plot (matches the chart displayed in the MagnetDB web interface)
# ---------------------------------------------------------------------------


def plot_stress_map(df: pd.DataFrame, magnet_name: str, i_h: float) -> None:
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(
        x - 0.2,
        df["hoop_MPa"],
        width=0.4,
        label=f"Hoop stress at I={i_h/1e3:.1f} kA",
        color="steelblue",
    )
    ax.bar(
        x + 0.2,
        df["hoop_max_MPa"],
        width=0.4,
        label="Hoop stress at I=31 kA (max)",
        color="tomato",
        alpha=0.7,
    )
    if df["rpe"].notna().any():
        ax.step(
            x,
            df["rpe"],
            where="mid",
            color="black",
            linestyle="--",
            linewidth=1.5,
            label="Rpe",
        )
    ax.set_xlabel("Coil")
    ax.set_ylabel("Hoop stress [MPa]")
    ax.set_title(f"Hoop stress map — {magnet_name}")
    ax.set_xticks(x)
    ax.set_xticklabels(df["coil"])
    ax.legend()
    ax.grid(axis="y", alpha=0.4)
    plt.tight_layout()
    plt.savefig(f"stress_map_{magnet_name}.png", dpi=150)
    print(f"\nPlot saved to stress_map_{magnet_name}.png")
    plt.show()


# ---------------------------------------------------------------------------
# Step 4b — Single-point hoop stress for barchart subcommand
#            Restored from the original compute_stress_map logic
# ---------------------------------------------------------------------------


def compute_hoop_at_currents(
    data: tuple,
    i_h: float,
    i_b: float,
    i_s: float,
) -> dict:
    """
    Compute hoop stress at given currents and at maximum current (31 kA).

    Returns
    -------
    dict with keys:
        x        : coil numbers
        y        : hoop stress [MPa] at (i_h, i_b, i_s)
        ymax     : hoop stress [MPa] at maximum current (31 kA)
        Bz0      : central field [T] at (i_h, i_b, i_s)
        Bz0_max  : central field [T] at 31 kA
    """
    print(
        f"\n── Computing hoop stress at currents IH={i_h} A, IB={i_b} A, IS={i_s} A …"
    )
    print(f"   MagnetTools data: {type(data)}, {len(data)} elements")
    Tubes, Helices, OHelices, BMagnets, UMagnets, Shims = data

    def _set_currents(ih, ib, is_):
        icurrents = mt.get_currents(Tubes, Helices, BMagnets, UMagnets)
        vcurrents = mt.DoubleVector(icurrents)
        num = 0
        if len(Tubes):
            vcurrents[num] = ih
            num += 1
        if len(BMagnets):
            vcurrents[num] = ib
            num += 1
        if len(UMagnets):
            vcurrents[num] = is_
        mt.set_currents(
            Tubes, Helices, BMagnets, UMagnets, OHelices, mt.DoubleVector(vcurrents)
        )

    def _get_hoop():
        mdata_type = {"H": Helices, "B": BMagnets, "S": UMagnets}
        headers, values = bmap.getHoop(Tubes, Helices, BMagnets, UMagnets)
        hdf = pd.DataFrame.from_records(values, columns=headers)
        return hdf["num"].tolist(), hdf["Hoop[MPa]"].tolist()

    _set_currents(i_h, i_b, i_s)
    Bz0 = mt.MagneticField(Tubes, Helices, BMagnets, UMagnets, 0, 0)[1]
    x, y = _get_hoop()

    _set_currents(31e3, 31e3, 0)
    Bz0_max = mt.MagneticField(Tubes, Helices, BMagnets, UMagnets, 0, 0)[1]
    _, ymax = _get_hoop()

    return {"x": x, "y": y, "ymax": ymax, "Bz0": Bz0, "Bz0_max": Bz0_max}


# ---------------------------------------------------------------------------
# Step 5b — Stats from hoop stress history
# ---------------------------------------------------------------------------


def compute_stress_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Return per-coil descriptive statistics from a validate_fast_from_pupitre DataFrame."""
    fast_cols = [c for c in df.columns if re.match(r"H\d+_fast", c)]
    rows = []
    for col in fast_cols:
        s = df[col]
        rows.append(
            {
                "coil": col,
                "min": s.min(),
                "max": s.max(),
                "mean": s.mean(),
                "std": s.std(),
                "p50": s.quantile(0.50),
                "p95": s.quantile(0.95),
                "p99": s.quantile(0.99),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 5c — Rainflow fatigue counting
# ---------------------------------------------------------------------------


def compute_fatigue(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """
    Apply rainflow cycle counting to one hoop-stress time series column.

    Requires the ``rainflow`` package (pip install rainflow).

    Returns
    -------
    DataFrame with columns: range, mean, count, i_start, i_end
    """
    import rainflow

    sigma = df[col].to_numpy()
    cycles = list(rainflow.count_cycles(sigma))
    return pd.DataFrame(cycles, columns=["range", "mean", "count", "i_start", "i_end"])


def plot_fatigue(
    df: pd.DataFrame,
    cycles_df: pd.DataFrame,
    magnet_name: str,
    col: str,
    bins: int = 15,
    output_png: str | None = None,
) -> None:
    """Two-panel plot: hoop stress time series + rainflow amplitude histogram."""
    x = df["t"] if "t" in df.columns else df.index
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    ax1.plot(x, df[col], color="steelblue", linewidth=1)
    ax1.set_title(f"Hoop stress time series — {col} ({magnet_name})")
    ax1.set_xlabel("t [s]" if "t" in df.columns else "index")
    ax1.set_ylabel("Hoop stress [MPa]")
    ax1.grid(True, alpha=0.3)

    amplitudes = cycles_df["range"].to_numpy()
    ax2.hist(amplitudes, bins=bins, color="orange", edgecolor="black", alpha=0.8)
    ax2.set_title(f"Rainflow fatigue analysis — {col} ({len(cycles_df)} cycles)")
    ax2.set_xlabel("Cycle amplitude [MPa]")
    ax2.set_ylabel("Occurrences")
    ax2.grid(axis="y", linestyle="--", alpha=0.5)

    plt.tight_layout()
    if output_png is None:
        output_png = f"fatigue_{col}_{magnet_name}.png"
    plt.savefig(output_png, dpi=150)
    print(f"\nPlot saved to {output_png}")
    plt.close()


# ---------------------------------------------------------------------------
# Step 7 — Normalized time-series plot (matches validate_fast_from_pupitre output)
# ---------------------------------------------------------------------------


def plot_stress_history(
    df: pd.DataFrame, magnet_name: str, output_png: str | None = None
) -> None:
    def _normalize(s: pd.Series) -> pd.Series:
        lo, hi = s.min(), s.max()
        if hi == lo:
            return pd.Series(np.zeros(len(s)), index=s.index)
        return (s - lo) / (hi - lo)

    x = df["t"] if "t" in df.columns else df.index
    fast_cols = [c for c in df.columns if re.match(r"H\d+_fast", c)]

    plt.figure(figsize=(10, 5))
    if "IH" in df.columns:
        plt.plot(
            x,
            _normalize(df["IH"]),
            label=f"IH (max={df['IH'].max():.0f} A)",
            linewidth=2,
        )
    if "IB" in df.columns:
        plt.plot(
            x,
            _normalize(df["IB"]),
            label=f"IB (max={df['IB'].max():.0f} A)",
            linewidth=2,
        )
    for col in fast_cols:
        plt.plot(
            x,
            _normalize(df[col]),
            label=f"{col} (max={df[col].max():.2f} MPa)",
            linewidth=2,
        )
    plt.xlabel("t [s]" if "t" in df.columns else "index")
    plt.ylabel("Normalized value")
    plt.title(f"Normalized currents and hoop stress — {magnet_name}")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    if output_png is None:
        output_png = f"stress_history_{magnet_name}.png"
    plt.savefig(output_png, dpi=150)
    print(f"\nPlot saved to {output_png}")
    plt.close()


# ---------------------------------------------------------------------------
# Main — subcommand dispatcher
# ---------------------------------------------------------------------------


def _add_shared_args(p: argparse.ArgumentParser) -> None:
    """Add arguments common to every subcommand."""
    p.add_argument("site_name", help="Site name as registered in DuckDB (e.g. M9)")
    p.add_argument(
        "--db",
        default="student_magnetdb.duckdb",
        help="Path to the student DuckDB (default: student_magnetdb.duckdb)",
    )
    p.add_argument(
        "--geometries",
        default="geometries",
        help="Directory of YAML geometry files (default: geometries/)",
    )
    p.add_argument(
        "--debug", action="store_true", help="Enable debug output from magnet_setup()"
    )


def _add_pupitre_args(p: argparse.ArgumentParser) -> None:
    """Add arguments for subcommands that read a pupitre time-series file."""
    p.add_argument(
        "--pupitre",
        nargs="*",
        default=None,
        metavar="FILE",
        help="Pupitre file(s) (.txt, .tdms, .csv). "
        "Omit to use all experiment files registered for the site.",
    )
    p.add_argument(
        "--pupitre-datadir",
        default=PUPITRE_DATA_DIR,
        metavar="DIR",
        help=(
            "Root directory for pupitre .txt files used to resolve bare filenames "
            "from the experiments table. Search order: cwd → DIR → DIR/<housing>. "
            "(overrides MAGNETRUN_PUPITRE_DATA_DIR / PUPITRE_DATADIR; "
            f"default: {PUPITRE_DATA_DIR!r})"
        ),
    )
    p.add_argument(
        "--use-mrun",
        action="store_true",
        help="Load via python_magnetrun.MagnetRun.load_mrun() "
        "(supports .tdms and path auto-resolution)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Validate fast results against bmap.getHoop row by row",
    )
    p.add_argument(
        "--magnet-type",
        default="H",
        choices=["H", "B", "S"],
        help="Coil type for --check validation (default: H)",
    )


def _load_site(
    args: argparse.Namespace,
) -> tuple[list[tuple[tuple, object, str]], str]:
    """
    Resolve site → all magnets, prepare geometry directories, and load
    MagnetTools objects for each.

    Returns ([(data, tempdir, magnet_name), ...], housing).
    """
    print(f"\n── Loading site '{args.site_name}' from DB '{args.db}' …")
    housing, magnets = load_site_config_from_duckdb(args.site_name, args.db)
    # print(f"magnets: {magnets}")
    # print(type(magnets[0]))

    site_config = {
        "name": args.site_name,
        "magnets": [config for magnet_name, config, _ in magnets],
    }
    tempdir = prepare_geometry_directory(
        args.site_name,
        site_config,
        args.db,
        geometries_dir=args.geometries,
    )

    for magnet_name, config, _ in magnets:
        print(
            f"  Prepared geometry directory for magnet '{magnet_name}' at {tempdir} ({config.keys()})"
        )

    print("\n── Loading MagnetTools objects …")
    data = load_magnettools(site_config, tempdir, debug=args.debug)
    Tubes, Helices, OHelices, BMagnets, UMagnets, Shims = data
    print(
        f"Tubes: {len(Tubes)}  Helices: {len(Helices)}  "
        f"BMagnets: {len(BMagnets)}  UMagnets: {len(UMagnets)}"
    )

    return tempdir, data, magnets, housing


def _load_history(args: argparse.Namespace, data: tuple, housing: str) -> pd.DataFrame:
    """
    Resolve pupitre files, compute hoop stress for each, and return a single
    concatenated DataFrame.

    File resolution:
    - args.pupitre is None or [] → all experiment files for the site (DB order)
    - args.pupitre is a list     → validated against experiments table (warn on miss)
    """
    if not housing:
        raise ValueError(
            "Housing could not be determined from the site. "
            "Check that sites.housing is set in the DB."
        )

    files = resolve_pupitre_files(
        args.site_name,
        args.db,
        args.pupitre or None,
        pupitre_datadir=getattr(args, "pupitre_datadir", "") or "",
        housing=housing,
    )
    print(
        f"\n── Computing hoop stress time series (housing={housing}, "
        f"{len(files)} file(s)) …"
    )

    dfs: list[pd.DataFrame] = []
    for f in files:
        print(f"   Processing {f} …")
        df = validate_fast_from_pupitre(
            data,
            f,
            housing,
            magnet_type=args.magnet_type,
            check=args.check,
            use_mrun=args.use_mrun,
            site=args.site_name,
        )
        dfs.append(df)

    result = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]
    if len(dfs) > 1 and "t" in result.columns:
        result = result.sort_values("t").reset_index(drop=True)

    fast_cols = [c for c in result.columns if re.match(r"H\d+_fast", c)]
    show_cols = [c for c in ["t", "IH", "IB"] if c in result.columns] + fast_cols
    print(result[show_cols].head().to_string(index=False))
    return result


def cmd_barchart(args: argparse.Namespace) -> None:
    tempdir, data, magnets, housing = _load_site(args)
    try:
        print(f"\n── Computing hoop stress at Ih={args.i_h/1e3:.1f} kA …")
        result = compute_hoop_at_currents(data, args.i_h, args.i_b, args.i_s)
        print(f"   Bz0 at requested current : {result['Bz0']:.3f} T")
        print(f"   Bz0 at max current (31kA): {result['Bz0_max']:.3f} T")
        print(
            pd.DataFrame(
                {
                    "coil": result["x"],
                    "hoop_MPa": result["y"],
                    "hoop_max_MPa": result["ymax"],
                }
            ).to_string(index=False)
        )

        print("\n── Annotating with Rpe …")
        df = annotate_with_rpe(result, args.site_name, args.db)
        print(
            df[
                [
                    "coil",
                    "part",
                    "nuance",
                    "hoop_MPa",
                    "hoop_max_MPa",
                    "rpe",
                    "ratio_rpe_max",
                ]
            ].to_string(index=False)
        )

        print(f"\n── Plotting … (df: {list(df.keys())})")
        plot_stress_map(df, args.site_name, args.i_h)
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def cmd_history(args: argparse.Namespace) -> None:
    tempdir, data, magnets, housing = _load_site(args)

    try:
        df = _load_history(args, data, housing)
        print("\n── Plotting …")
        plot_stress_history(df, args.site_name)
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def cmd_stats(args: argparse.Namespace) -> None:
    tempdir, data, magnets, housing = _load_site(args)

    try:
        df = _load_history(args, data, housing)
        print("\n── Statistics …")
        stats = compute_stress_stats(df)
        print(stats.to_string(index=False))
        if args.output:
            stats.to_csv(args.output, index=False)
            print(f"\nStats saved to {args.output}")
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def cmd_fatigue(args: argparse.Namespace) -> None:
    tempdir, data, magnets, housing = _load_site(args)
    try:
        df = _load_history(args, data, housing)
        fast_cols = [c for c in df.columns if re.match(r"H\d+_fast", c)]
        print(f"\n── Rainflow fatigue analysis ({len(fast_cols)} coil(s)) …")
        for col in fast_cols:
            cycles_df = compute_fatigue(df, col)
            print(f"\n   {col}: {len(cycles_df)} cycles detected")
            print(cycles_df.describe().to_string())
            plot_fatigue(df, cycles_df, args.site_name, col, bins=args.bins)
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Hoop stress analysis for a site using DuckDB + YAML files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{barchart,history,stats,fatigue}",
    )

    # ── barchart ──────────────────────────────────────────────────────────────
    p_bar = subparsers.add_parser(
        "barchart",
        help="Bar chart of hoop stress at given currents vs Rpe",
    )
    _add_shared_args(p_bar)
    p_bar.add_argument(
        "--i-h", type=float, default=20000.0, help="Helix current [A] (default: 20000)"
    )
    p_bar.add_argument(
        "--i-b", type=float, default=0.0, help="Bitter current [A] (default: 0)"
    )
    p_bar.add_argument(
        "--i-s", type=float, default=0.0, help="Supra current [A] (default: 0)"
    )
    p_bar.set_defaults(func=cmd_barchart)

    # ── history ───────────────────────────────────────────────────────────────
    p_hist = subparsers.add_parser(
        "history",
        help="Hoop stress vs time from a pupitre file (normalised plot)",
    )
    _add_shared_args(p_hist)
    _add_pupitre_args(p_hist)
    p_hist.set_defaults(func=cmd_history)

    # ── stats ─────────────────────────────────────────────────────────────────
    p_stats = subparsers.add_parser(
        "stats",
        help="Descriptive statistics of hoop stress time series",
    )
    _add_shared_args(p_stats)
    _add_pupitre_args(p_stats)
    p_stats.add_argument(
        "--output", default=None, help="Save stats table to CSV (default: print only)"
    )
    p_stats.set_defaults(func=cmd_stats)

    # ── fatigue ───────────────────────────────────────────────────────────────
    p_fat = subparsers.add_parser(
        "fatigue",
        help="Rainflow cycle counting on hoop stress time series",
    )
    _add_shared_args(p_fat)
    _add_pupitre_args(p_fat)
    p_fat.add_argument(
        "--bins", type=int, default=15, help="Number of histogram bins (default: 15)"
    )
    p_fat.set_defaults(func=cmd_fatigue)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
