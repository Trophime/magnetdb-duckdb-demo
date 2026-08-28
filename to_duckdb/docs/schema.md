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
users                one row per EXPERIENCES_LOG acronym, joined (fuzzy) with proposal
                     data: research area, call number, access mode, housing used

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

## Lifecycle

`assemblies`, `magnets`, and `parts` each carry a rule-driven `status`, with
cascades keeping the three in sync as assemblies get commissioned and
disassembled. Solid arrows below are automatic cascades; dashed arrows are
explicit `... update-status` calls.

```{mermaid}
flowchart TB
    subgraph ASM["Assembly — status derived from decommissioned_at"]
        direction LR
        A_study(["in_study (opt-out)"])
        A_op(["in_operation"])
        A_dis(["disassembled"])
        A_op -->|"decommission_assembly()<br/>or auto-close on add"| A_dis
    end

    subgraph MAG["Magnet"]
        direction LR
        M_study(["in_study"])
        M_stock(["in_stock"])
        M_op(["in_operation"])
        M_ret(["retired"])
        M_dead(["dead"])
        M_stock -->|"linked to an active assembly"| M_op
        M_op -->|"assembly disassembled"| M_stock
        M_study -.->|"update-status"| M_stock
        M_stock -.->|"update-status"| M_ret
        M_stock -.->|"update-status"| M_dead
        M_op -.->|"update-status"| M_ret
        M_op -.->|"update-status"| M_dead
    end

    subgraph PRT["Part"]
        direction LR
        P_study(["in_study"])
        P_stock(["in_stock"])
        P_op(["in_operation"])
        P_ret(["retired"])
        P_dead(["dead"])
        P_stock -->|"parent magnet commissioned"| P_op
        P_op -->|"parent magnet → retired/dead"| P_stock
        P_study -.->|"update-status"| P_stock
        P_stock -.->|"update-status"| P_ret
        P_stock -.->|"update-status, or named as magnet's --dead-part"| P_dead
        P_op -.->|"update-status"| P_ret
        P_op -.->|"update-status"| P_dead
    end
```

Invariants not shown above:

- **Per-housing no-overlap**: two non-`in_study` assemblies on the same
  housing can't have overlapping `[commissioned_at, decommissioned_at)`
  windows. Adding a new assembly auto-closes a still-open predecessor on
  that housing (via `decommission_assembly()`) when it started first;
  otherwise the add is rejected.
- **One active assembly per magnet**: a magnet can't be openly linked
  (`assembly_magnets.decommissioned_at IS NULL`) to two assemblies at once.
- **Dead-part requirement**: `magnet update-status <name> --status dead`
  requires at least one `--dead-part PART` (repeatable) — each named part is
  set (or confirmed) dead in the same call, before the magnet itself.
- **`status_history`**: every entity has an append-only JSON log
  (`status`, `date`, `description`, `attachments`) recording each status
  change, viewable via `part view`/`magnet view`/`assembly view`.

### Status vocabularies

`assemblies.status` — `AssemblyStatus` (`to_duckdb/enums.py`), derived, not
free text:

| Value | Meaning |
|---|---|
| `in_study` | Explicit opt-out — assembly still being planned; skips the no-overlap/auto-close/derivation rules entirely. |
| `in_operation` | Derived: `decommissioned_at IS NULL`. |
| `disassembled` | Derived: `decommissioned_at` is set. |

`magnets.status` / `parts.status` — `LifecycleStatus` (`to_duckdb/enums.py`),
set directly (by insert, cascade, or `update-status`):

| Value | Meaning |
|---|---|
| `in_study` | Still being designed; not yet in stock. |
| `in_stock` | Available, not installed in an active assembly. Default for a newly-inserted part/magnet when no status is given. |
| `in_operation` | Installed in a currently active (non-`in_study`, `decommissioned_at IS NULL`) assembly. |
| `retired` | Taken out of service, not dead. |
| `dead` | Failed. For a magnet, requires at least one linked part already/simultaneously `dead` (see above). |

### `status_history` entry shape

Each `status_history` column (`assemblies`, `parts`, `magnets`) holds a JSON
array; every status change appends one entry:

```json
{
    "status":      "dead",
    "date":        "2026-08-14T10:32:05.123456",
    "description": "Coil burst during ramp-up — see incident report.",
    "attachments": [
        {"kind": "report", "path": "/mnt/incidents/2026-08-14-M9-coil-burst.pdf"}
    ]
}
```

`date` defaults to the current time if not given explicitly (e.g. via
`--changed-at`/`--decommissioned-at`); `attachments` defaults to `[]` and is
populated from repeated `--attachment KIND=PATH` CLI flags.

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
