# Database schema reference

## Table overview

```
materials            physical properties of conductor alloys (rpe in Pa)
parts                individual physical components (helix, ring, bitter, lead)
magnets              magnet assemblies (insert, bitters, hybrid, …)
magnet_parts         ordered parts within a magnet, with coil_index
housing_config       wiring layout for a magnet housing (GR1/GR2 coil assignment)
sites                operational configurations (housing, commissioning dates)
site_magnets         magnets active in a site — positional & temporal metadata
experiments          operational records (TSV files) attached to a site
operationaldata      discovered archive files (TDMS/TXT) linked to a site, with type tag
                     (IDs auto-assigned via sequence operationaldata_id_seq)
overview_records     processed overview file metadata (OverviewRecord, no raw data)

── Operational statistics ───────────────────────────────────────────────────
op_stats_processed   idempotency guard — which files have been ingested and with which bins
op_run_scalars       per-run scalar totals: energy (billing), heat extracted, duration
op_site_bin_stats    site-level field-bin distributions: Pmagnet, Ptot, tsb, teb, debitbrut
op_part_bin_stats    per-part field-bin distributions: Icoil, Ucoil, hoop_stress_proxy

── Hoop-stress statistics ───────────────────────────────────────────────────
hoop_stress_processed   idempotency guard — PK (experiment_id, bin_config); one row per
                        processed (experiment, bin edge set); warns if bin config changes
hoop_stress_bin_stats   per-part stress-bin distributions: n_samples, sum_dt, sum_x_dt,
                        sum_x2_dt, min_x, max_x — PK (experiment_id, part_name, stress_bin_low)
hoop_stress_fatigue     per-part rainflow cycle counts: n_cycles, sum_range3 (Miner proxy)
                        PK (experiment_id, part_name)
```

The authoritative DDL is in [`schema.py`](../schema.py).

---

## site_magnets columns

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `site_name` | VARCHAR | — | FK → sites |
| `magnet_name` | VARCHAR | — | FK → magnets |
| `z_offset` | DOUBLE | 0.0 | Axial offset of the magnet in the site (m) |
| `r_offset` | DOUBLE | 0.0 | Radial offset of the magnet in the site (m) |
| `parallax` | DOUBLE | 0.0 | Parallax angle |
| `commissioned_at` | TIMESTAMP | NULL | When this magnet was commissioned in this site |
| `decommissioned_at` | TIMESTAMP | NULL | When removed (NULL = still active) |
| `metadata` | JSON | `{}` | Free-form key/value store |

---

## coil_index

The `magnet_parts.coil_index` column maps each helix or bitter part to its `Icoil_N` column in the operational TSV records:

- Assigned 1-based, in the order parts appear in the magnet definition
- Only `helix` and `bitter` parts receive a coil_index
- `ring` and `lead` parts get `NULL`

Example query to retrieve the mapping:

```python
import duckdb
con = duckdb.connect("student_magnetdb.duckdb", read_only=True)

con.execute("""
    SELECT 'Icoil' || mp.coil_index AS column,
           p.name AS part,
           p.type,
           mat.nuance,
           mat.rpe / 1e6 AS rpe_MPa
    FROM magnet_parts mp
    JOIN parts     p   ON p.name   = mp.part_name
    JOIN magnets   m   ON m.name   = mp.magnet_name
    LEFT JOIN materials mat ON mat.name = p.material_name
    WHERE m.name = 'M19061901'
      AND mp.coil_index IS NOT NULL
    ORDER BY mp.coil_index
""").df()
```

---

## Site JSON format

The JSON expected by `magnetdb.py site add` matches the format produced by `python_magnetapi`. The minimal required fields are:

```json
{
    "name":              "M10_M19071101_13",
    "status":            "in_operation",
    "housing":           "M10",
    "commissioned_at":   "2025-11-12 00:00:00",
    "decommissioned_at": "None",
    "magnets": [
        "M19071101",
        "M10Bitters"
    ],
    "records": [
        {
            "name":        "M10_2025.11.13---09:14:21.txt",
            "description": "",
            "file":        "M10_2025.11.13---09:14:21.txt"
        }
    ]
}
```

Each entry in `magnets` is either a **plain string** (name only — positional fields default to `0.0`, metadata to `{}`) or a **dict** with the full `SiteMagnet` fields:

```json
"magnets": [
    "M19071101",
    {
        "name":               "M10Bitters",
        "z_offset":           0.0,
        "r_offset":           0.0,
        "parallax":           0.0,
        "commissioned_at":    "2025-11-12 00:00:00",
        "decommissioned_at":  null,
        "metadata":           {"current_max_A": 26000}
    }
]
```

Notes:
- `magnets` contains magnet **names** — magnets must already be in the DB (or resolvable from a JSON file in the same directory).
- `decommissioned_at` can be `"None"` or omitted for active sites.
- `records` is inserted into the `experiments` table automatically; it can be an empty list `[]`.

---

## Material JSON format

The JSON produced by `python_magnetapi` for a material record:

```json
{
    "name":                    "MA20072304",
    "description":             "",
    "nuance":                  "CuCrZr",
    "t_ref":                   293,
    "volumic_mass":            9000.0,
    "specific_heat":           385,
    "alpha":                   0.0036,
    "electrical_conductivity": 47200000.0,
    "thermal_conductivity":    380,
    "magnet_permeability":     1,
    "young":                   117000000000.0,
    "poisson":                 0.33,
    "expansion_coefficient":   1.8e-05,
    "rpe":                     324000000.0
}
```

All fields except `name` are optional. `rpe` is stored in Pa.
