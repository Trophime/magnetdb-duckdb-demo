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
        ├── generate_magnet_directory(magnet_id, tempdir)
        │       → writes {part_name}.yaml files to tempdir/data/geometries/
        │
        ├── appenv(yaml_repo=..., ...)
        │       → environment object pointing at file locations
        │
        ├── magnet_setup(env, config, debug)
        │       → (Tubes, Helices, OHelices, BMagnets, UMagnets, Shims)
        │
        └── compute_stress_map_chart(data, i_h, i_b, i_s, magnet_type)
                → {"x": [...], "y": [...], "ymax": [...]}

Student chain (this script)
-----------------------------
    DuckDB + YAML files on disk
        │
        ├── load_magnet_config_from_duckdb(magnet_name)   ← replaces generate_magnet_config
        │
        ├── prepare_geometry_directory(magnet_name, ...)  ← replaces generate_magnet_directory
        │
        ├── appenv(...)                                    ← identical
        │
        ├── magnet_setup(env, config, debug)               ← identical
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
import json
import shutil
import tempfile
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

import magnettools.Bmap as bmap
import magnettools.magnettools as mt
from python_magnetsetup.ana import magnet_setup
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
        "Tref":                  row["t_ref"],
        "VolumicMass":           row["volumic_mass"],
        "alpha":                 row["alpha"],
        "ElectricalConductivity": row["electrical_conductivity"],
        "MagnetPermeability":    row["magnet_permeability"],
        "Poisson":               row["poisson"],
        "Rpe":                   row["rpe"],         # unit: see module docstring
        "SpecificHeat":          row["specific_heat"],
        "ThermalConductivity":   row["thermal_conductivity"],
        "Young":                 row["young"],
        "CoefDilatation":        row["expansion_coefficient"],
        "nuance":                row["nuance"],
    }


def load_magnet_config_from_duckdb(magnet_name: str, db_path: str) -> dict:
    """
    Build the config dict that magnet_setup() expects, reading from DuckDB
    instead of the Django ORM.

    Produces a dict with the same structure as generate_magnet_config():
    {
        "geom": "M19061901.yaml",
        "Helix": [
            {"geom": "H15101601.yaml", "material": {...}, "insulator": {...}},
            ...
        ],
        "Ring": [
            {"geom": "M19061901_R1.yaml", "material": {...}, "insulator": {...}},
            ...
        ]
    }

    Notes
    -----
    - "geom" keys use {part.name}.yaml, matching generate_magnet_directory()
      which writes files named after parts, not geometry stems.
    - Part sections are keyed by capitalised type: Helix, Ring, Bitter, Lead.
    - Parts are ordered by magnet_parts.rank, preserving assembly order.
    - MAT_ISOLANT must be present in the DB (loaded via seeds_to_duckdb.py).
    """
    con = duckdb.connect(db_path, read_only=True)

    # Fetch insulator (MAT_ISOLANT) — required for every part entry
    isolant_rows = con.execute("""
        SELECT t_ref, volumic_mass, alpha, electrical_conductivity,
               magnet_permeability, poisson, rpe, specific_heat,
               thermal_conductivity, young, expansion_coefficient, nuance
        FROM materials WHERE name = 'MAT_ISOLANT'
    """).fetchall()

    if not isolant_rows:
        raise ValueError(
            "MAT_ISOLANT not found in the database. "
            "Run seeds_to_duckdb.py to populate structural data first."
        )
    insulator_payload = _format_material_row(dict(zip(
        ["t_ref", "volumic_mass", "alpha", "electrical_conductivity",
         "magnet_permeability", "poisson", "rpe", "specific_heat",
         "thermal_conductivity", "young", "expansion_coefficient", "nuance"],
        isolant_rows[0]
    )))

    # Fetch all parts for this magnet, ordered by assembly rank
    parts = con.execute("""
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
    """, [magnet_name]).fetchall()

    con.close()

    if not parts:
        raise ValueError(
            f"Magnet '{magnet_name}' not found in DB or has no parts. "
            f"Check the magnet name and ensure seeds are loaded."
        )

    col_names = [
        "part_name", "part_type", "rank",
        "t_ref", "volumic_mass", "alpha",
        "electrical_conductivity", "magnet_permeability",
        "poisson", "rpe", "specific_heat",
        "thermal_conductivity", "young",
        "expansion_coefficient", "nuance",
    ]

    config = {"geom": f"{magnet_name}.yaml"}

    for row in parts:
        d = dict(zip(col_names, row))
        key = d["part_type"].capitalize()   # "Helix", "Ring", "Bitter", "Lead"
        if key not in config:
            config[key] = []
        config[key].append({
            "geom":      f"{d['part_name']}.yaml",
            "material":  _format_material_row(d),
            "insulator": insulator_payload,
        })

    return config


# ---------------------------------------------------------------------------
# Step 2 — Prepare geometry directory on disk
#           Replicates generate_magnet_directory() without Django
# ---------------------------------------------------------------------------

def prepare_geometry_directory(
    magnet_name: str,
    config: dict,
    db_path: str,
    geometries_dir: str | Path | None = None,
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

    Geometry YAML files are written from one of two sources (tried in order):
    1. ``geometry_data`` column in DuckDB — JSON-serialized python_magnetgeo object
       stored by add_magnet.py at import time.  No external files needed.
    2. ``geometries_dir`` fallback — a directory of pre-extracted YAML files
       (used for seed-based data that pre-dates geometry_data storage).

    Returns the Path of the created temp directory (caller should clean up).
    """
    src_dir = Path(geometries_dir) if geometries_dir else None
    if src_dir is not None and not src_dir.is_dir():
        print(f"  [WARN] geometries_dir not found: {src_dir} — will rely on DB-stored geometry_data.")
        src_dir = None

    tempdir = Path(tempfile.mkdtemp(prefix=f"magnetdb_student_{magnet_name}_"))
    data_geom = tempdir / "data" / "geometries"
    data_geom.mkdir(parents=True)
    (tempdir / "data" / "cad").mkdir()

    # Look up {part_name} → {geometry_stem, geometry_data} and magnet geometry from DuckDB
    con = duckdb.connect(db_path, read_only=True)
    part_rows = con.execute("""
        SELECT p.name, p.geometry, p.geometry_data
        FROM magnet_parts mp
        JOIN parts   p ON p.name = mp.part_name
        JOIN magnets m ON m.name = mp.magnet_name
        WHERE m.name = ?
    """, [magnet_name]).fetchall()
    magnet_row = con.execute(
        "SELECT geometry, geometry_data FROM magnets WHERE name = ?", [magnet_name]
    ).fetchone()
    con.close()

    # Write top-level magnet geometry: stem/geometry_data → {magnet_name}.yaml
    magnet_geom_stem = magnet_row[0] if magnet_row else magnet_name
    magnet_geom_data = magnet_row[1] if magnet_row else None
    _write_yaml(src_dir, magnet_geom_stem, magnet_geom_data, data_geom, magnet_name)

    # Write per-part geometries: stem/geometry_data → {part_name}.yaml
    for part_name, geom_stem, geom_data in part_rows:
        _write_yaml(src_dir, geom_stem, geom_data, data_geom, part_name)

    # Write config.json alongside the data/ tree
    with open(tempdir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    return tempdir


def _yaml_from_geometry_data(geometry_data_json: str, dst_path: Path) -> bool:
    """
    Reconstruct a python_magnetgeo object from its DB-stored JSON and write it
    as a YAML file at dst_path.  Returns True on success.

    The JSON is produced by add_magnet.py at import time via
    python_magnetgeo.deserialize.serialize_instance.  This function reverses
    that: JSON → python_magnetgeo object → YAML string → file.
    """
    try:
        import json as _json
        import yaml as _yaml
        from python_magnetgeo.deserialize import unserialize_object
        d = _json.loads(geometry_data_json)
        obj = unserialize_object(d)
        dst_path.write_text(_yaml.dump(obj, default_flow_style=False, sort_keys=False))
        return True
    except Exception as exc:
        print(f"  [WARN] Could not reconstruct geometry from DB JSON for {dst_path.name}: {exc}")
        return False


def _write_yaml(
    src_dir: Path,
    stem: str | None,
    geometry_data: str | None,
    dst_dir: Path,
    dst_stem: str,
) -> None:
    """
    Write a geometry YAML file named ``{dst_stem}.yaml`` into dst_dir.

    Strategy (in order):
    1. If geometry_data (JSON) is available in the DB, reconstruct the
       python_magnetgeo object and dump it as YAML — no external files needed.
    2. Otherwise fall back to copying ``{stem}.yaml`` from src_dir (legacy
       behaviour for seed-based data that has a geometries directory).
    """
    dst = dst_dir / f"{dst_stem}.yaml"
    if geometry_data:
        if _yaml_from_geometry_data(geometry_data, dst):
            return
    # Fallback: copy from geometries directory
    if stem and src_dir:
        # stem may be a full path (from add_magnet) or a bare stem (from seeds)
        src = src_dir / f"{Path(stem).stem}.yaml"
        if src.exists():
            shutil.copy(src, dst)
            return
    print(f"  [WARN] No geometry source found for {dst_stem}.yaml")


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
    return magnet_setup(env, config, debug)


# ---------------------------------------------------------------------------
# Step 4 — Compute hoop stress map
#           Direct port of compute_stress_map_chart() in compute_stress_map_chart.py
# ---------------------------------------------------------------------------

def compute_stress_map(
    data: tuple,
    i_h: float,
    i_b: float,
    i_s: float,
    magnet_type: str = "H",
) -> dict:
    """
    Compute hoop stress at given currents and at maximum current (31 kA).

    Parameters
    ----------
    data        : MagnetTools tuple from load_magnettools()
    i_h         : helix current [A]
    i_b         : bitter current [A]
    i_s         : supra current [A]
    magnet_type : "H" for insert helices, "B" for bitters

    Returns
    -------
    dict with keys:
        x        : part numbers (coil indices)
        y        : hoop stress [MPa] at (i_h, i_b, i_s)
        ymax     : hoop stress [MPa] at maximum current (31 kA)
        Bz0      : central field [T] at (i_h, i_b, i_s)
        Bz0_max  : central field [T] at maximum current
    """
    (Tubes, Helices, OHelices, BMagnets, UMagnets, Shims) = data

    def _set_currents(ih, ib, is_):
        icurrents = mt.get_currents(Tubes, Helices, BMagnets, UMagnets)
        vcurrents = list(icurrents)
        num = 0
        if len(Tubes)    != 0: vcurrents[num] = ih;  num += 1
        if len(BMagnets) != 0: vcurrents[num] = ib;  num += 1
        if len(UMagnets) != 0: vcurrents[num] = is_; num += 1
        mt.set_currents(Tubes, Helices, BMagnets, UMagnets, OHelices,
                        mt.DoubleVector(vcurrents))

    def _get_hoop() -> tuple[list, list]:
        mdata = {"H": Helices, "B": BMagnets, "S": UMagnets}
        (headers, values) = bmap.getHoop(
            mdata[magnet_type], Tubes, Helices, BMagnets, UMagnets, magnet_type
        )
        df = pd.DataFrame.from_records(values)
        df.columns = headers
        return df["num"].tolist(), df["Hoop[MPa]"].tolist()

    # At requested currents
    _set_currents(i_h, i_b, i_s)
    Bz0 = mt.MagneticField(Tubes, Helices, BMagnets, UMagnets, 0, 0)[1]
    x, y = _get_hoop()

    # At maximum current (31 kA) — same logic as compute_max() in original
    _set_currents(31e3, 31e3, 0)
    Bz0_max = mt.MagneticField(Tubes, Helices, BMagnets, UMagnets, 0, 0)[1]
    _, ymax = _get_hoop()

    return {"x": x, "y": y, "ymax": ymax, "Bz0": Bz0, "Bz0_max": Bz0_max}


# ---------------------------------------------------------------------------
# Step 5 — Annotate with Rpe from DuckDB and print summary
# ---------------------------------------------------------------------------

def annotate_with_rpe(result: dict, magnet_name: str, db_path: str) -> pd.DataFrame:
    """
    Join hoop stress results with Rpe values from DuckDB to compute
    σ/Rpe safety ratios.
    """
    con = duckdb.connect(db_path, read_only=True)
    rpe_df = con.execute("""
        SELECT mp.coil_index, p.name AS part, mat.rpe, mat.nuance
        FROM magnet_parts mp
        JOIN parts   p   ON p.name  = mp.part_name
        JOIN magnets m   ON m.name  = mp.magnet_name
        LEFT JOIN materials mat ON mat.name = p.material_name
        WHERE m.name = ? AND mp.coil_index IS NOT NULL
        ORDER BY mp.coil_index
    """, [magnet_name]).df()
    con.close()

    df = pd.DataFrame({
        "coil_index":   result["x"],
        "hoop_MPa":     result["y"],
        "hoop_max_MPa": result["ymax"],
    })
    df = df.merge(rpe_df, on="coil_index", how="left")

    # ratio_rpe is only meaningful if rpe is in the same unit as hoop_MPa.
    # See the module docstring for the unit caveat.
    df["ratio_rpe"]     = df["hoop_MPa"]     / df["rpe"]
    df["ratio_rpe_max"] = df["hoop_max_MPa"] / df["rpe"]
    return df


# ---------------------------------------------------------------------------
# Step 6 — Plot (matches the chart displayed in the MagnetDB web interface)
# ---------------------------------------------------------------------------

def plot_stress_map(df: pd.DataFrame, magnet_name: str, i_h: float) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(df["coil_index"] - 0.2, df["hoop_MPa"],     width=0.4,
           label=f"Hoop stress at I={i_h/1e3:.1f} kA", color="steelblue")
    ax.bar(df["coil_index"] + 0.2, df["hoop_max_MPa"], width=0.4,
           label="Hoop stress at I=31 kA (max)", color="tomato", alpha=0.7)
    if df["rpe"].notna().any():
        ax.step(df["coil_index"], df["rpe"], where="mid",
                color="black", linestyle="--", linewidth=1.5, label="Rpe")
    ax.set_xlabel("Coil index (Icoil_N)")
    ax.set_ylabel("Hoop stress [MPa]")
    ax.set_title(f"Hoop stress map — {magnet_name}")
    ax.set_xticks(df["coil_index"])
    ax.legend()
    ax.grid(axis="y", alpha=0.4)
    plt.tight_layout()
    plt.savefig(f"stress_map_{magnet_name}.png", dpi=150)
    print(f"\nPlot saved to stress_map_{magnet_name}.png")
    plt.show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compute hoop stress map for a magnet using DuckDB + YAML files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("magnet_name",
                        help="Magnet name as registered in DuckDB (e.g. M19061901)")
    parser.add_argument("--db", default="student_magnetdb.duckdb",
                        help="Path to the student DuckDB (default: student_magnetdb.duckdb)")
    parser.add_argument("--geometries", default="geometries",
                        help="Directory of YAML geometry files (default: geometries/)")
    parser.add_argument("--i-h", type=float, default=20000.0,
                        help="Helix current in A (default: 20000 A)")
    parser.add_argument("--i-b", type=float, default=0.0,
                        help="Bitter current in A (default: 0 A)")
    parser.add_argument("--i-s", type=float, default=0.0,
                        help="Supra current in A (default: 0 A)")
    parser.add_argument("--magnet-type", default="H", choices=["H", "B", "S"],
                        help="Part type to compute hoop stress for (default: H)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug output from magnet_setup()")
    args = parser.parse_args()

    print(f"\n── Loading config from DuckDB for '{args.magnet_name}' …")
    config = load_magnet_config_from_duckdb(args.magnet_name, args.db)
    n_helices = len(config.get("Helix", []))
    n_rings   = len(config.get("Ring", []))
    n_bitters = len(config.get("Bitter", []))
    print(f"   Helix: {n_helices}  Ring: {n_rings}  Bitter: {n_bitters}")

    print(f"\n── Preparing geometry directory …")
    tempdir = prepare_geometry_directory(
        args.magnet_name, config, args.geometries, args.db
    )
    print(f"   Temp dir: {tempdir}")

    try:
        print(f"\n── Loading MagnetTools objects …")
        data = load_magnettools(config, tempdir, debug=args.debug)
        (Tubes, Helices, OHelices, BMagnets, UMagnets, Shims) = data
        print(f"   Tubes: {len(Tubes)}  Helices: {len(Helices)}  "
              f"BMagnets: {len(BMagnets)}  UMagnets: {len(UMagnets)}")

        print(f"\n── Computing stress map at I_h={args.i_h/1e3:.1f} kA …")
        result = compute_stress_map(
            data, args.i_h, args.i_b, args.i_s, args.magnet_type
        )
        print(f"   Bz0 at requested current : {result['Bz0']:.3f} T")
        print(f"   Bz0 at max current (31kA): {result['Bz0_max']:.3f} T")

        print(f"\n── Annotating with Rpe …")
        df = annotate_with_rpe(result, args.magnet_name, args.db)
        print(df[["coil_index", "part", "nuance", "hoop_MPa",
                   "hoop_max_MPa", "rpe", "ratio_rpe_max"]].to_string(index=False))

        print(f"\n── Plotting …")
        plot_stress_map(df, args.magnet_name, args.i_h)

    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


if __name__ == "__main__":
    main()
