"""
stress_map.py
=============
Hoop-stress analysis for a site using DuckDB + YAML geometry files.

Replaces the Django/ORM data-access layer of the MagnetDB production chain
with DuckDB queries; everything from magnet_setup() onwards is identical.

Public API
----------
    load_site_config_from_duckdb(site_name, db_path)
    prepare_geometry_directory(site_name, magnets, geometries_dir, tempdir)
    load_magnettools(config, tempdir, debug)
    compute_hoop_at_currents(data, i_h, i_b, i_s)
    annotate_with_rpe(result, site_name, db_path)
    compute_stress_stats(df)
    compute_fatigue(df, col)
    plot_stress_map(df, magnet_name, i_h)
    plot_stress_history(df, site_name)
    plot_fatigue(df, cycles_df, site_name, col, bins)

CLI (also accessible via ``magnetdb.py hoop-stress``)
-----------------------------------------------------
    python stress_map.py barchart <site> [--i-h ...] [--i-b ...] [--i-s ...]
    python stress_map.py history  <site> [--pupitre ...] [--use-mrun]
    python stress_map.py stats    <site> [--pupitre ...] [--output ...]
    python stress_map.py fatigue  <site> [--pupitre ...] [--bins ...]

Note on Rpe units
-----------------
Rpe is stored as-is from the seed files (Pa in some, MPa in others).
Verify the unit for your dataset before interpreting ratio_rpe values.
"""

import argparse
import glob as _glob
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
from config import DEFAULT_DB
from enums import MagnetType, PartType
from populate import _RECORDS_BASE as _DEFAULT_RECORDS_BASE, _SRV_SUBDIR as _DEFAULT_SRV_SUBDIR
from python_magnetrun.magnetdata import load_magnetdata
from python_magnetrun.runetl import prepareData
from python_magnetrun.utils.timestamps import parse_filename_timestamp
from python_magnetsetup.ana import msite_setup
from python_magnetsetup.config import appenv


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
    con: "duckdb.DuckDBPyConnection | None" = None,
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
    con             : Reuse an already-open connection instead of opening a new
                       read-only one (avoids DuckDB's "different configuration"
                       error when called from within a caller's open connection).

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
    owns_con = con is None
    if con is None:
        con = duckdb.connect(db_path, read_only=True)

    # ── 1. Site housing ───────────────────────────────────────────────────────
    site_row = con.execute(
        "SELECT housing FROM sites WHERE name = ?", [site_name]
    ).fetchone()
    if site_row is None:
        if owns_con:
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
        if owns_con:
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
        if owns_con:
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

    if owns_con:
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
    con: "duckdb.DuckDBPyConnection | None" = None,
) -> str:
    """
    Build a python_magnetgeo MSite by rebuilding each linked magnet's
    assembly YAML on the fly from that magnet's own parts, then combining
    them with each magnet's ``site_magnets`` positional offsets.

    Mirrors ``Site.geometry_config_to_json()`` in python_magnetdb/models.py,
    replacing the Django ORM with DuckDB queries.

    ``parts.geometry_data`` is the only geometry ever persisted — there is
    no stored magnet- or site-level geometry to read. Each magnet linked to
    *site_name* has its assembly YAML reconstructed by
    ``magnet_geometry_config_to_yaml()`` from its parts' ``geometry_data``;
    this function combines those into one ``MSite``.

    Parameters
    ----------
    site_name      : Site name as registered in DuckDB (e.g. ``"M9_M19061901_0"``)
    db_path        : Path to the DuckDB file
    output_dir     : If given, also write ``<site_name>.yaml`` (and each
                     magnet's ``<magnet_name>.yaml``) to this directory via
                     ``write_to_yaml()``.  The YAML string is returned
                     regardless — this is a write location, not a read source.
    geometries_dir : Passed straight through as ``output_dir`` to
                     ``magnet_geometry_config_to_yaml()`` for each magnet —
                     also a write location, not a fallback read source.
    con            : Reuse an already-open connection instead of opening a
                     new read-only one (avoids DuckDB's "different
                     configuration" error when called from within a
                     caller's open connection). Passed through to
                     ``magnet_geometry_config_to_yaml()`` for each magnet.

    Returns
    -------
    str
        YAML representation of the ``MSite``.

    Raises
    ------
    ValueError
        If the site is not found, has no magnets, or any part of a linked
        magnet is missing ``geometry_data``.
    """
    import yaml as _yaml
    from python_magnetgeo.MSite import MSite

    print(f"  ── Preparing geometry directory for site '{site_name}' …")
    geo_dir = Path(geometries_dir) if geometries_dir else None

    owns_con = con is None
    if con is None:
        con = duckdb.connect(db_path, read_only=True)

    if (
        con.execute("SELECT 1 FROM sites WHERE name = ?", [site_name]).fetchone()
        is None
    ):
        if owns_con:
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
    if owns_con:
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
            magnet_name, db_path, output_dir=geo_dir, con=con if not owns_con else None,
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
    con: "duckdb.DuckDBPyConnection | None" = None,
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
    con         : Reuse an already-open connection instead of opening a new
                  read-only one (avoids DuckDB's "different configuration"
                  error when called from within a caller's open connection).

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

    owns_con = con is None
    if con is None:
        con = duckdb.connect(db_path, read_only=True)

    magnet_row = con.execute(
        "SELECT type FROM magnets WHERE name = ?", [magnet_name]
    ).fetchone()
    if magnet_row is None:
        if owns_con:
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
    if owns_con:
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
            f"Expected one of: {[t.value for t in MagnetType]}."
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
    site_name: str,
    config: dict,
    db_path: str,
    geometries_dir: str | Path | None = None,
    con: "duckdb.DuckDBPyConnection | None" = None,
) -> Path:
    """
    Build a temporary directory tree that magnet_setup() can read:

        <tempdir>/
        ├── config.json
        └── data/
            ├── geometries/
            │   ├── {site_name}.yaml        ← MSite geometry (site + all magnets)
            │   ├── {part_name}.yaml        ← one file per part
            │   └── ...
            └── cad/

    site_name is used both for the temp-directory prefix and to look up the
    site's magnets in the DB.

    Geometry is rebuilt on the fly, bottom-up, from ``parts.geometry_data`` —
    the only geometry ever persisted — via ``geometry_config_to_yaml()``.
    *db_path* is required for this lookup; *config* plays no part in
    geometry resolution and is only written verbatim to ``config.json`` for
    ``magnet_setup()``'s other inputs. *geometries_dir*, if given, is passed
    through to ``geometry_config_to_yaml()`` as a write location for the
    rebuilt per-magnet YAML — not a fallback read source; a part missing
    ``geometry_data`` always raises ``ValueError``.

    Parameters
    ----------
    con : Reuse an already-open connection instead of opening a new
          read-only one (avoids DuckDB's "different configuration" error
          when called from within a caller's open connection). Passed
          through to ``geometry_config_to_yaml()``.

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
        site_name, db_path, output_dir=data_geom, geometries_dir=src_dir, con=con,
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
    # print(f"load_magnettools: env={env}, config={config}")
    return msite_setup(env, config, debug)


# ---------------------------------------------------------------------------
# Step 4 — Compute hoop stress time series from a pupitre file
#           Fast vectorised alternative to the row-by-row compute_stress_map_chart
# ---------------------------------------------------------------------------


def _assert_current_units(units: dict, cols: list[str], ureg) -> None:
    """Verify each of *cols* (e.g. IH, IB, IS) is declared as a current unit.

    Skips columns with no declared unit (unit metadata unavailable). Only
    the current inputs are checked here — the geometry-derived quantities
    (r, j_unit, Bz) come from magnettools, which exposes no unit metadata
    to check against.
    """
    for col in cols:
        entry = units.get(col)
        if not entry or entry[1] is None:
            continue
        if entry[1].dimensionality != ureg.ampere.dimensionality:
            raise ValueError(
                f"validate_fast_from_pupitre: expected a current unit for {col!r}, got {entry[1]}"
            )


def _section_index_at_z(elements, indices, z0: float = 0.0) -> int:
    """Return the index from *indices* whose z-extent contains *z0*.

    *elements* is the flat ``VectorOfBitters`` (``Helices`` or ``BMagnets``)
    holding every section's geometry/current-density data; *indices* are the
    global indices into it for one part's sections (e.g. one Tube's
    turn-groups, or one Bitter part's Bstack). Falls back to the section
    with the closest ``get_Z_offset()`` to *z0* if none of them actually
    contains it (gap between sections, or *z0* outside the part entirely).
    """
    best_idx = indices[0]
    best_dist = None
    for idx in indices:
        elem = elements[idx]
        z_off = elem.get_Z_offset()
        half_h = elem.get_HalfHeight()
        if (z_off - half_h) <= z0 <= (z_off + half_h):
            return idx
        dist = abs(z0 - z_off)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_idx = idx
    return best_idx


def validate_fast_from_pupitre(
    data: tuple,
    pupitre_file: str,
    housing: str,
    magnet_type: str = "H",
    check: bool = False,
    use_mrun: bool = False,
    site: str = "",
    z0_h: list[float] | None = None,
    z0_b: list[float] | None = None,
) -> pd.DataFrame:
    """
    Fast vectorised hoop-stress computation over a pupitre time series.

    Precomputes, at unit current (1 A), for each part i (one Tube for
    Helix, one Bstack — a group of turn-group plates — for Bitter):
      - r[i]        : inner radius of the part
      - j_unit[i]   : current density of the section whose z-extent
                      contains z0_h[i]/z0_b[i] (see _section_index_at_z())
      - Bz_tubes[i] : Bz at (r[i], z0[i]) produced by all tubes at IH = 1 A
      - Bz_bmag[i]  : Bz at (r[i], z0[i]) produced by all BMagnets at IB = 1 A
      - Bz_umag[i]  : Bz at (r[i], z0[i]) produced by all UMagnets at IS = 1 A

    Hoop stress estimate for part i at time step k:
      sigma_i(k) = r_i * j_unit_i * IH(k)
                       * (Bz_tubes_i * IH(k) + Bz_bmag_i * IB(k) + Bz_umag_i * IS(k))

    All per-timestep work is pure NumPy — no C++ calls inside the time loop.

    Parameters
    ----------
    data         : MagnetTools tuple from load_magnettools()
    pupitre_file : Path to the pupitre file (.txt, .tdms, or .csv)
    housing      : Housing name (e.g. "M9")
    magnet_type  : which coil type(s) to compute hoop stress for:
                     "H"   — insert helices only (columns H1_fast, H2_fast, …)
                     "B"   — bitter parts only   (columns B1_fast, B2_fast, …)
                     "S"   — supras only         (columns Supra1_fast, Supra2_fast, …)
                     "all" — all present types (H + B + S columns combined)
                   Also controls which reference magnet type is used in the
                   bmap.getHoop sanity check (ignored when check=False).
    check        : If True, validate fast results against bmap.getHoop row by row
                   (only supported for single types "H", "B", "S", not "all")
    use_mrun     : If True, load via python_magnetrun.MagnetRun.load_mrun() instead
                   of load_magnetdata() + prepareData(); supports .tdms in addition
                   to .txt/.csv and handles path auto-resolution.
    site         : Site name forwarded to load_mrun() (ignored when use_mrun=False)
    z0_h         : Per-Tube observation z-position, in H1_fast/H2_fast/…
                   order (e.g. from resolve_z0_by_type()). Defaults to all
                   0.0 (magnets centered on z=0) when None.
    z0_b         : Per-Bstack (per Bitter part) observation z-position, in
                   B1_fast/B2_fast/… order. Defaults to all 0.0 when None.

    Returns
    -------
    DataFrame with time series columns: t, IH, IB, [IS,] and a subset of
    H1_fast…HN_fast, B1_fast…BM_fast, Supra1_fast…Supra K_fast
    depending on magnet_type and which magnet groups are present in *data*.
    """
    Tubes, Helices, OHelices, BMagnets, UMagnets, Shims = data
    icurrents = mt.get_currents(Tubes, Helices, BMagnets, UMagnets)
    n_tubes = len(Tubes)
    n_umag = len(UMagnets)

    # Group BMagnets into per-part stacks (Bstacks) so hoop stress is
    # reported once per DB Bitter part, not once per physical plate.
    if len(BMagnets):
        _stacks = mt.create_Bstack(BMagnets)
        b_group_indices = [
            [_stacks[s][i] for i in range(len(_stacks[s]))] for s in range(len(_stacks))
        ]
    else:
        b_group_indices = []
    n_bmag = len(b_group_indices)

    # z0_h/z0_b: per-Tube / per-Bstack observation z-position (default 0.0
    # = magnets centered on z=0). Selects which turn-group/plate represents
    # each part, and where Bz is evaluated for it.
    if z0_h is None:
        z0_h = [0.0] * n_tubes
    if z0_b is None:
        z0_b = [0.0] * n_bmag

    # Which types to compute (gate early so we skip unnecessary work)
    _do_h = (magnet_type in ("H", "all")) and n_tubes > 0
    _do_b = (magnet_type in ("B", "all")) and n_bmag > 0
    _do_s = (magnet_type in ("S", "all")) and n_umag > 0

    # ------------------------------------------------------------------
    # 1. Precompute unit-current quantities for every magnet type
    #
    # Inner radii are pure geometry — extract before any set_currents call.
    # Current densities require set_currents(group=1 A). Both are sampled
    # from the section whose z-extent contains that part's z0 (see
    # _section_index_at_z()), not an arbitrary array-index "middle".
    # Bz contributions are evaluated at ALL requested (r, z0) positions in
    # each single-group pass so no extra set_currents calls are needed.
    # ------------------------------------------------------------------
    h_sel = [
        _section_index_at_z(
            Helices, range(Tube.get_index(), Tube.get_index() + Tube.get_n_elem()), z0_h[i]
        )
        for i, Tube in enumerate(Tubes)
    ]
    b_sel = [
        _section_index_at_z(BMagnets, idxs, z0_b[j])
        for j, idxs in enumerate(b_group_indices)
    ]

    r_h = np.array([Tubes[i].get_R_int() for i in range(n_tubes)]) if n_tubes else np.zeros(0)
    r_b = np.array([BMagnets[i].get_R_int() for i in b_sel]) if n_bmag else np.zeros(0)
    r_s = np.array([UMag.get_R_int() for UMag in UMagnets]) if n_umag else np.zeros(0)

    z0_h_arr = np.array(z0_h) if n_tubes else np.zeros(0)
    z0_b_arr = np.array(z0_b) if n_bmag else np.zeros(0)
    z0_s_arr = np.zeros(n_umag)  # Supra not covered by per-section z0 (out of scope)

    j_unit_h = np.zeros(n_tubes)
    j_unit_b = np.zeros(n_bmag)
    j_unit_s = np.zeros(n_umag)

    # Bz[src_at_tgt]: Bz at *tgt* (r, z0) when *src* current = 1 A, rest = 0
    Bz_h_at_rh = np.zeros(n_tubes)
    Bz_b_at_rh = np.zeros(n_tubes)
    Bz_s_at_rh = np.zeros(n_tubes)
    Bz_h_at_rb = np.zeros(n_bmag)
    Bz_b_at_rb = np.zeros(n_bmag)
    Bz_s_at_rb = np.zeros(n_bmag)
    Bz_h_at_rs = np.zeros(n_umag)
    Bz_b_at_rs = np.zeros(n_umag)
    Bz_s_at_rs = np.zeros(n_umag)

    def _zero_vcurrents():
        v = mt.DoubleVector(icurrents)
        for i in range(len(v)):
            v[i] = 0.0
        return v

    def _bz_at(radii, z0s):
        return np.array(
            [
                mt.MagneticField(Tubes, Helices, BMagnets, UMagnets, r, z)[1]
                for r, z in zip(radii, z0s)
            ]
        )

    num = 0
    if n_tubes:
        v = _zero_vcurrents()
        v[num] = 1.0  # IH = 1 A
        mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices, v)
        for i, sel in enumerate(h_sel):
            j_unit_h[i] = Helices[sel].get_CurrentDensity()
        if _do_h:
            Bz_h_at_rh = _bz_at(r_h, z0_h_arr)
        if _do_b:
            Bz_h_at_rb = _bz_at(r_b, z0_b_arr)
        if _do_s:
            Bz_h_at_rs = _bz_at(r_s, z0_s_arr)
        num += 1

    if n_bmag:
        v = _zero_vcurrents()
        v[num] = 1.0  # IB = 1 A
        mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices, v)
        for j, sel in enumerate(b_sel):
            j_unit_b[j] = BMagnets[sel].get_CurrentDensity()
        if _do_h:
            Bz_b_at_rh = _bz_at(r_h, z0_h_arr)
        if _do_b:
            Bz_b_at_rb = _bz_at(r_b, z0_b_arr)
        if _do_s:
            Bz_b_at_rs = _bz_at(r_s, z0_s_arr)
        num += 1

    if n_umag:
        v = _zero_vcurrents()
        v[num] = 1.0  # IS = 1 A
        mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices, v)
        for k, UMag in enumerate(UMagnets):
            j_unit_s[k] = UMag.get_CurrentDensity()
        if _do_h:
            Bz_s_at_rh = _bz_at(r_h, z0_h_arr)
        if _do_b:
            Bz_s_at_rb = _bz_at(r_b, z0_b_arr)
        if _do_s:
            Bz_s_at_rs = _bz_at(r_s, z0_s_arr)

    print(
        f"   Precomputed unit-current quantities: "
        f"{n_tubes} helix tube(s), {n_bmag} bitter part(s), {n_umag} supra(s)."
    )

    # ------------------------------------------------------------------
    # 2. Load pupitre data
    # ------------------------------------------------------------------
    print(f"\n── Loading pupitre data: {pupitre_file} …")
    if use_mrun:
        from python_magnetrun.MagnetRun import load_mrun

        mrun = load_mrun(pupitre_file, housing=housing, site=site)
        mrun.MagnetData.Units()
        df = mrun.MagnetData.Data
        units = mrun.MagnetData.units
    else:
        mdata = load_magnetdata(pupitre_file)
        prepareData(mdata, housing)
        mdata.Units()
        df = mdata.Data
        units = mdata.units

    # Drop rows where all current columns are NaN — they would propagate NaN
    # into the stress computation and produce broken plots.
    current_cols = [c for c in ("IH", "IB", "IS") if c in df.columns]

    from python_magnetrun.magnetdata_base import _make_ureg

    _assert_current_units(units, current_cols, _make_ureg())

    if current_cols:
        n_before = len(df)
        df = df.dropna(subset=current_cols, how="all").reset_index(drop=True)
        n_dropped = n_before - len(df)
        if n_dropped:
            print(f"  [warn] dropped {n_dropped}/{n_before} rows with all-NaN currents")

    n_t = len(df)
    IH_arr = df["IH"].to_numpy() if "IH" in df.columns else np.zeros(n_t)
    IB_arr = df["IB"].to_numpy() if "IB" in df.columns else np.zeros(n_t)
    IS_arr = df["IS"].to_numpy() if "IS" in df.columns else np.zeros(n_t)

    # ------------------------------------------------------------------
    # 3. Vectorised hoop stress — (N, 1) broadcast against (1, T)
    #
    #    For each magnet group X ∈ {H, B, S} with driver current I_X:
    #      sigma_X[j, k] = r_X[j] * j_unit_X[j] * I_X[k]
    #                           * (Bz_h_at_rX[j]*IH[k]
    #                              + Bz_b_at_rX[j]*IB[k]
    #                              + Bz_s_at_rX[j]*IS[k])
    # ------------------------------------------------------------------
    IH = IH_arr[np.newaxis, :]  # (1, T)
    IB = IB_arr[np.newaxis, :]
    IS = IS_arr[np.newaxis, :]

    sigma_h: np.ndarray | None = None
    sigma_b: np.ndarray | None = None
    sigma_s: np.ndarray | None = None

    if _do_h:
        _Bz = (
            Bz_h_at_rh[:, np.newaxis] * IH
            + Bz_b_at_rh[:, np.newaxis] * IB
            + Bz_s_at_rh[:, np.newaxis] * IS
        )
        sigma_h = (
            r_h[:, np.newaxis] * (j_unit_h[:, np.newaxis] * IH) * _Bz * 1e-6
        )  # MPa

    if _do_b:
        _Bz = (
            Bz_h_at_rb[:, np.newaxis] * IH
            + Bz_b_at_rb[:, np.newaxis] * IB
            + Bz_s_at_rb[:, np.newaxis] * IS
        )
        sigma_b = (
            r_b[:, np.newaxis] * (j_unit_b[:, np.newaxis] * IB) * _Bz * 1e-6
        )  # MPa

    if _do_s:
        _Bz = (
            Bz_h_at_rs[:, np.newaxis] * IH
            + Bz_b_at_rs[:, np.newaxis] * IB
            + Bz_s_at_rs[:, np.newaxis] * IS
        )
        sigma_s = (
            r_s[:, np.newaxis] * (j_unit_s[:, np.newaxis] * IS) * _Bz * 1e-6
        )  # MPa

    # ------------------------------------------------------------------
    # 3b. Optional sanity check: fast sigma vs bmap.getHoop row by row.
    #     Skipped for magnet_type="all" — run single-type checks instead.
    # ------------------------------------------------------------------
    if check:
        if magnet_type == "all":
            print(
                "\n── Sanity check skipped for magnet_type='all' — run H/B/S separately."
            )
        else:
            print("\n── Sanity check: fast vs bmap.getHoop …")
            _sigma_check = {"H": sigma_h, "B": sigma_b, "S": sigma_s}[magnet_type]
            _n_check = {"H": n_tubes, "B": n_bmag, "S": n_umag}[magnet_type]
            _label_prefix = {"H": "H", "B": "B", "S": "Supra"}[magnet_type]
            max_err = np.zeros(_n_check)

            for k, row in enumerate(df.itertuples(index=False)):
                v = _zero_vcurrents()
                _cnum = 0
                if n_tubes:
                    v[_cnum] = getattr(row, "IH", 0.0)
                    _cnum += 1
                if n_bmag:
                    v[_cnum] = getattr(row, "IB", 0.0)
                    _cnum += 1
                if n_umag:
                    v[_cnum] = getattr(row, "IS", 0.0)
                mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices, v)

                headers, hoop_values = bmap.getHoop(Tubes, Helices, BMagnets, UMagnets)
                ref_df = pd.DataFrame.from_records(hoop_values, columns=headers)
                # Filter to rows belonging to the selected type (by "num" prefix,
                # e.g. "H1", "B1", "Supra1" — bmap.getHoop() has no "label" column)
                mask = ref_df["num"].str.startswith(_label_prefix)
                ref_hoop = ref_df.loc[mask, "Hoop[MPa]"].to_numpy()

                for i in range(_n_check):
                    if i < len(ref_hoop):
                        max_err[i] = max(
                            max_err[i], abs(_sigma_check[i, k] - ref_hoop[i])
                        )

            col_prefix = {"H": "H", "B": "B", "S": "Supra"}[magnet_type]
            print(f"   Max absolute error per {magnet_type} element [MPa]:")
            for i in range(_n_check):
                print(f"     {col_prefix}{i+1}: {max_err[i]:.4e} MPa")

    # ------------------------------------------------------------------
    # 4. Store results in DataFrame
    # ------------------------------------------------------------------
    if _do_h and sigma_h is not None:
        for i in range(n_tubes):
            df[f"H{i+1}_fast"] = sigma_h[i, :]

    if _do_b and sigma_b is not None:
        for j in range(n_bmag):
            df[f"B{j+1}_fast"] = sigma_b[j, :]

    if _do_s and sigma_s is not None:
        for k in range(n_umag):
            df[f"Supra{k+1}_fast"] = sigma_s[k, :]

    return df


def _expand_pupitre_pattern(
    pattern: str, pupitre_datadir: str, housing: str
) -> list[str]:
    """Expand a glob pattern to matching pupitre file paths.

    For patterns with an explicit directory component, glob them directly.
    For bare names or bare glob patterns, search in order:
    1. cwd
    2. pupitre_datadir
    3. pupitre_datadir / housing

    Returns all matches from the first directory that yields any result.
    Falls back to [pattern] unchanged if nothing matches anywhere.
    """
    p = Path(pattern)
    if p.is_absolute() or p.parent != Path("."):
        matches = sorted(_glob.glob(str(p)))
        return matches if matches else [pattern]

    search_dirs: list[Path] = [Path.cwd()]
    if pupitre_datadir:
        search_dirs.append(Path(pupitre_datadir))
        if housing and housing not in ("notdefined", ""):
            search_dirs.append(Path(pupitre_datadir) / housing)

    for base in search_dirs:
        matches = sorted(_glob.glob(str(base / pattern)))
        if matches:
            return matches

    return [pattern]


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
    pupitre_datadir: Root directory for pupitre files (records_base / srv_subdir).
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
        resolved: list[str] = []
        for f in result:
            resolved.extend(_expand_pupitre_pattern(f, pupitre_datadir, housing))
        return resolved

    # Expand each pattern, then validate each resolved file against the experiments table.
    # Match by exact path OR by basename — the DB may store absolute paths.
    resolved = []
    for pattern in files:
        expanded = _expand_pupitre_pattern(pattern, pupitre_datadir, housing)
        for f in expanded:
            basename = Path(f).name
            row = con.execute(
                "SELECT 1 FROM experiments "
                "WHERE site_name = ? AND (file = ? OR file LIKE ?)",
                [site_name, f, f"%/{basename}"],
            ).fetchone()
            if row is None:
                print(
                    f"  [WARN] '{f}' not found in experiments for site '{site_name}'."
                )
        resolved.extend(expanded)
    con.close()
    return resolved


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
    fast_cols = [c for c in df.columns if re.match(r"(H|B|Supra)\d+_fast", c)]
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
    fast_cols = [c for c in df.columns if re.match(r"(H|B|Supra)\d+_fast", c)]
    plot_cols = [c for c in ("IH", "IB") if c in df.columns] + fast_cols

    # Report and drop rows where every plotted column is NaN.
    nan_counts = {c: int(df[c].isna().sum()) for c in plot_cols if df[c].isna().any()}
    if nan_counts:
        print(f"  [plot] NaN counts per column: {nan_counts}")
    mask = df[plot_cols].notna().any(axis=1)
    n_dropped = int((~mask).sum())
    if n_dropped:
        print(f"  [plot] dropping {n_dropped} all-NaN rows before plotting")
        df = df[mask].reset_index(drop=True)

    def _normalize(s: pd.Series) -> pd.Series:
        lo = s.min(skipna=True)
        hi = s.max(skipna=True)
        if pd.isna(lo) or pd.isna(hi) or hi == lo:
            return pd.Series(np.zeros(len(s)), index=s.index)
        return (s - lo) / (hi - lo)

    x = (
        df["t_abs"]
        if "t_abs" in df.columns
        else (df["t"] if "t" in df.columns else df.index)
    )

    plt.figure(figsize=(10, 5))
    if "IH" in df.columns:
        plt.plot(
            x,
            _normalize(df["IH"]),
            label=f"IH (max={df['IH'].max(skipna=True):.0f} A)",
            linewidth=2,
        )
    if "IB" in df.columns:
        plt.plot(
            x,
            _normalize(df["IB"]),
            label=f"IB (max={df['IB'].max(skipna=True):.0f} A)",
            linewidth=2,
        )
    for col in fast_cols:
        plt.plot(
            x,
            _normalize(df[col]),
            label=f"{col} (max={df[col].max(skipna=True):.2f} MPa)",
            linewidth=2,
        )
    plt.xlabel("t [s]" if "t_abs" in df.columns or "t" in df.columns else "index")
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
        default=DEFAULT_DB,
        help=f"Path to the DuckDB file (default: {DEFAULT_DB})",
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
        "--records-base",
        default=str(_DEFAULT_RECORDS_BASE),
        dest="records_base",
        metavar="DIR",
        help=(
            "Root of the records tree. pupitre files are resolved under "
            "records-base/srv-subdir[/<housing>]. "
            f"(default: {_DEFAULT_RECORDS_BASE!r})"
        ),
    )
    p.add_argument(
        "--srv-subdir",
        default=_DEFAULT_SRV_SUBDIR,
        dest="srv_subdir",
        help=f"Subdirectory of records-base for pupitre TXT files "
             f"(default: {_DEFAULT_SRV_SUBDIR!r})",
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
        default="all",
        choices=["H", "B", "S", "all"],
        help=(
            "Coil type(s) to compute hoop stress for: "
            "H (insert helices), B (bitter plates), S (supras), "
            "all (H + B + S combined). Also selects the reference type for "
            "--check validation (ignored when magnet-type=all). Default: all"
        ),
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

    from compute_hoop_stats import resolve_z0_by_type

    records_base = getattr(args, "records_base", "")
    srv_subdir   = getattr(args, "srv_subdir", _DEFAULT_SRV_SUBDIR)
    pupitre_datadir = (
        str(Path(records_base) / srv_subdir) if records_base else ""
    )
    files = resolve_pupitre_files(
        args.site_name,
        args.db,
        args.pupitre or None,
        pupitre_datadir=pupitre_datadir,
        housing=housing,
    )
    z0_h, z0_b = resolve_z0_by_type(args.site_name, args.db)
    print(
        f"\n── Computing hoop stress time series (housing={housing}, "
        f"{len(files)} file(s)) …"
    )

    dfs: list[pd.DataFrame] = []
    file_starts: list[float | None] = []
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
            z0_h=z0_h,
            z0_b=z0_b,
        )
        dt = parse_filename_timestamp(f)
        file_starts.append(dt.timestamp() if dt is not None else None)
        dfs.append(df)

    # Build t_abs: seconds from the first file's start time.
    # This keeps each file's trace at its real position on the time axis
    # so multiple files don't overlap at t=0.
    if len(dfs) > 1 and "t" in dfs[0].columns:
        t0 = next((s for s in file_starts if s is not None), None)
        for df, fs in zip(dfs, file_starts):
            offset = (fs - t0) if (fs is not None and t0 is not None) else 0.0
            df["t_abs"] = df["t"] + offset
        result = (
            pd.concat(dfs, ignore_index=True)
            .sort_values("t_abs")
            .reset_index(drop=True)
        )
    else:
        result = dfs[0] if len(dfs) == 1 else pd.concat(dfs, ignore_index=True)
        if "t" in result.columns:
            result["t_abs"] = result["t"]

    fast_cols = [c for c in result.columns if re.match(r"(H|B|Supra)\d+_fast", c)]
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
        fast_cols = [c for c in df.columns if re.match(r"(H|B|Supra)\d+_fast", c)]
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
