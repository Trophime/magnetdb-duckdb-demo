"""
queries.py
==========
Example queries against the MagnetDB DuckDB.

Jupyter use: copy each numbered block as a separate cell.
             Run the connection cell (DB_PATH + con = …) first.

Requirements:
    pip install duckdb pandas
"""

from pathlib import Path

import duckdb

try:
    DB_PATH = str(Path(__file__).resolve().parent.parent / "magnetdb.duckdb")
except NameError:  # __file__ is undefined in Jupyter
    DB_PATH = "magnetdb.duckdb"

if __name__ == "__main__":
    con = duckdb.connect(DB_PATH, read_only=True)

    # ── 1. Full site hierarchy ─────────────────────────────────────────────────
    print("=== Site hierarchy ===")
    hierarchy = con.execute("""
        SELECT
            s.name        AS site,
            m.name        AS magnet,
            m.type        AS magnet_type,
            p.type        AS part_type,
            mp.coil_index,          -- Icoil_N column in records (NULL for rings/leads)
            mp.rank,                -- position in magnet assembly
            p.name        AS part,
            p.geometry,
            mat.nuance,
            mat.rpe / 1e6 AS rpe_MPa
        FROM sites s
        JOIN site_magnets sm ON sm.site_name   = s.name
        JOIN magnets m       ON m.name         = sm.magnet_name
        JOIN magnet_parts mp ON mp.magnet_name = m.name
        JOIN parts p         ON p.name        = mp.part_name
        LEFT JOIN materials mat ON mat.name   = p.material_name
        ORDER BY s.name, mp.rank
    """).df()
    print(hierarchy.to_string())

    # ── 2. Icoil → part mapping for a specific magnet ─────────────────────────
    print("\n=== Icoil → part mapping for M19061901 ===")
    coil_map = con.execute("""
        SELECT
            'Icoil' || mp.coil_index AS column_name,
            p.name                   AS part_name,
            p.type,
            p.geometry,
            mat.nuance,
            mat.rpe / 1e6            AS rpe_MPa,
            mat.electrical_conductivity / 1e6 AS sigma_MS_per_m
        FROM magnet_parts mp
        JOIN parts p    ON p.name  = mp.part_name
        JOIN magnets m  ON m.name  = mp.magnet_name
        LEFT JOIN materials mat ON mat.name = p.material_name
        WHERE m.name = 'M19061901'
          AND mp.coil_index IS NOT NULL
        ORDER BY mp.coil_index
    """).df()
    print(coil_map.to_string())

    # ── 3. All records for a site ─────────────────────────────────────────────
    print("\n=== Records for M9_M19061901 ===")
    records = con.execute("""
        SELECT id, file, status
        FROM experiments
        WHERE site_name = 'M9_M19061901'
        ORDER BY file
    """).df()
    print(records.to_string())

    # ── 4. Material comparison across all helices ────────────────────────────
    print("\n=== Helix materials summary ===")
    helix_mats = con.execute("""
        SELECT DISTINCT
            mat.name        AS material,
            mat.nuance,
            mat.rpe / 1e6   AS rpe_MPa,
            mat.electrical_conductivity / 1e6 AS sigma_MS_per_m,
            mat.young / 1e9 AS E_GPa
        FROM parts p
        JOIN materials mat ON mat.name = p.material_name
        WHERE p.type = 'helix'
        ORDER BY mat.rpe DESC
    """).df()
    print(helix_mats.to_string())

    # ── 5. How many coil channels does each magnet have? ─────────────────────
    print("\n=== Coil channel count per magnet ===")
    channels = con.execute("""
        SELECT
            m.name       AS magnet,
            m.type,
            COUNT(CASE WHEN mp.coil_index IS NOT NULL THEN 1 END) AS n_coils,
            COUNT(CASE WHEN p.type = 'ring'           THEN 1 END) AS n_rings,
            COUNT(CASE WHEN p.type = 'lead'           THEN 1 END) AS n_leads
        FROM magnets m
        JOIN magnet_parts mp ON mp.magnet_name = m.name
        JOIN parts p         ON p.name = mp.part_name
        GROUP BY m.name, m.type
        ORDER BY m.type, m.name
    """).df()
    print(channels.to_string())

    # ── 6. Parts shared across multiple magnets (reused helices/rings) ────────
    print("\n=== Parts used in more than one magnet ===")
    shared = con.execute("""
        SELECT
            p.name, p.type,
            COUNT(DISTINCT mp.magnet_name) AS n_magnets,
            STRING_AGG(mp.magnet_name, ', ' ORDER BY mp.magnet_name) AS in_magnets
        FROM magnet_parts mp
        JOIN parts p ON p.name = mp.part_name
        GROUP BY p.name, p.type
        HAVING COUNT(DISTINCT mp.magnet_name) > 1
        ORDER BY n_magnets DESC, p.type
    """).df()
    print(shared.to_string())

    # ── 7. All sites in which a magnet has been used, sorted by commission date ─
    print("\n=== Sites where magnet M19071101 has been used ===")
    magnet_sites = con.execute("""
        SELECT
            s.name              AS site,
            s.housing,
            s.status,
            s.commissioned_at,
            s.decommissioned_at
        FROM site_magnets sm
        JOIN sites s ON s.name = sm.site_name
        WHERE sm.magnet_name = 'M19071101'
        ORDER BY s.commissioned_at ASC NULLS LAST
    """).df()
    print(magnet_sites.to_string())

    # ── 8. All magnets and sites in which a part has been used,
    #       sorted by site commission date ─────────────────────────────────────
    print("\n=== Sites and magnets where part H15101601 has been used ===")
    part_history = con.execute("""
        SELECT
            p.name              AS part,
            p.type,
            mp.coil_index,
            m.name              AS magnet,
            m.type              AS magnet_type,
            s.name              AS site,
            s.housing,
            s.commissioned_at,
            s.decommissioned_at
        FROM magnet_parts mp
        JOIN parts   p  ON p.name  = mp.part_name
        JOIN magnets m  ON m.name  = mp.magnet_name
        JOIN site_magnets sm ON sm.magnet_name = m.name
        JOIN sites   s  ON s.name  = sm.site_name
        WHERE p.name = 'H15101601'
          AND p.type IN ('helix', 'bitter')
        ORDER BY s.commissioned_at ASC NULLS LAST
    """).df()
    print(part_history.to_string())

    con.close()
