# JNL-G use-case coverage: DuckDB demo vs. python_magnetdb

Every arrow-level bullet from the five JNL-G use-case slides (Operating, Incident
Analysis, User, Conception, Workshop), checked row by row against what the DuckDB
demonstrator dashboard (this repo) and the live `python_magnetdb` app actually do
today.

**Legend:** ✅ Implemented · 🟡 Partial · ⚪ Gap — not built · — N/A, out of scope for this tool

**Tallies (25 use cases each):**

| Tool | ✅ done | 🟡 partial | ⚪ gap | — n/a |
|---|---|---|---|---|
| DuckDB demo | 6 | 9 | 4 | 6 |
| python_magnetdb | 8 | 10 | 7 | 0 |

> **Note on scope** — `python_magnetdb` carries its own `to_duckdb/` folder: a
> vendored, earlier snapshot of the very same DuckDB tool evaluated in the
> left-hand column (older `sites`/`site_magnets` schema, no `status_history`).
> Fatigue statistics, energy totals and the material-limit overlay that live
> only in that snapshot are **not** credited to `python_magnetdb` below —
> crediting them there would count the same code twice.

Compiled from a read-only pass over `magnetdb-duckdb-demo` (branch
`msite_to_assembly`) and `python_magnetdb`, 2026-09-10. Source: LNCMI JNL-G
use-case slides.

---

## 01 · Operating use cases

*Modeling magnet outputs and cooling state during a run*

| Use case | DuckDB demo | python_magnetdb |
|---|---|---|
| Model magnet outputs (R, V) to flag slow drift / metastable states | ⚪ Gap — raw Ucoil/Icoil channels are viewable per part; no derived resistance channel or drift/metastable-state detector in the ETL or dashboard (`magnetdb_analysis.py`) | 🟡 Partial — Record visualisation exposes raw Ucoil/Icoil/ΔR-coil %; no modeled resistance or drift analysis (`record_visualization.py`) |
| Tell measurement anomalies apart from physical failures (e.g. wire break vs. short-circuit) | 🟡 Partial — trip subtypes get static, filename-derived hover labels ("hardware I_MAX trigger", "50 Hz network disturbance") — not a signal-based classifier (`magnetdb_plot.py`) | ⚪ Gap — no anomaly-classification logic found |
| Run global power analysis to infer cooling-system state (failure prevention, maintenance planning) | ⚪ Gap — only cumulative energy (kWh) is surfaced per housing/assembly/magnet; no cooling-state inference or degradation trend (`housing_stats.py`) | 🟡 Partial — raw cooling telemetry (Tin/Tout, Flow, HP/BP, Rpm) is viewable per record; the FEM side only models cooling as a boundary condition, not an operational diagnostic |

## 02 · Incident analysis use cases

*Pulling every sensor and event together for a post-incident review*

| Use case | DuckDB demo | python_magnetdb |
|---|---|---|
| Reach pupitre, pigbrother and hybrid sources from one place | 🟡 Partial — pupitre + pigbrother (overview/archive/default/spike/trigger) are fully wired; hybrid kHz/rms/trigger/vprocess columns exist in the schema but are never loaded or shown (`schema.py`) | 🟡 Partial — the Record model parses pupitre text files only; no pigbrother/hybrid ingestion in the live app |
| See all of a record's data in one place | ✅ Implemented — `overview_records.py` merges a record's overview + archive + pupitre sources into one grouped page | 🟡 Partial — per-record visualise (any column vs. time) exists, but isn't assembled into one multi-sensor overview |
| Group all figures by sensor category in the dashboard | ✅ Implemented — accordions per category (Magnetic_Field, Hydraulics, Tensions_Aimant, …), ordered via `group_order.json` | 🟡 Partial — generic column-vs-time plotting; no fixed sensor-category grouping |
| Interact with graphs: zoom, annotations | ✅ Implemented — native Plotly zoom/pan plus a click-to-pin cross-graph cursor sync (`file_viewer.py`) | 🟡 Partial — chart zoom is likely available via the charting library; no annotation or incident-overlay feature found |
| Overlay detected anomalies / log messages on the plots | ✅ Implemented — `_add_incident_overlays` draws dashed markers with hover labels for default/spike/trigger events directly on sensor plots (`magnetdb_plot.py`) | ⚪ Gap — no overlay mechanism found |
| Attach metadata to an incident (e.g. a report reference) | 🟡 Partial — `status_history` on parts/magnets/assemblies accepts a free-text description plus attachments (e.g. a report path) — CLI only, not in the dashboard UI (`crud.py`) | ⚪ Gap — no incident entity exists; `AuditLog` only records routine CRUD actions |
| Track incidents per magnet / assembly / housing | 🟡 Partial — `status_history` exists per entity; no aggregated "incidents per magnet/housing" view | ⚪ Gap — no incident model exists |

## 03 · User use cases

*What a facility user can see about their own experiment*

| Use case | DuckDB demo | python_magnetdb |
|---|---|---|
| Pull up B(t) from pupitre / pigbrother | ✅ Implemented — `file_viewer.py` auto-plots `Field` (pupitre) / `Champ_magn` (pigbrother) by default | 🟡 Partial — Record visualise plots the pupitre `Field` column; no pigbrother source |
| Show the magnetic field profile | 🟡 Partial — a separate Voila notebook (`voila-Bmap*.ipynb`) computes an axial profile with current sliders — outside the main dashboard | ✅ Implemented — `compute_bmap_chart` computes Bz/Br/B and renders them via the bmap visualisation pages |
| Show field gradients and homogeneity | ⚪ Gap — no gradient or homogeneity metric found in the dashboard or notebook | ✅ Implemented — same bmap pipeline adds dBr/dr, dBz/dz gradients and a "G" homogeneity index |
| Estimate power consumption / energy cost | 🟡 Partial — energy is computed and shown in kWh per housing/assembly/magnet; no € tariff conversion (`compute_op_stats.py`) | ⚪ Gap — live app shows only raw Ptot/Pmagnet; no aggregation or cost logic (only the vendored `to_duckdb` copy has this — see scope note above) |
| Compare realized vs. expected B profile | ⚪ Gap — a regime "signature" is extracted and stored per record, but is CLI-only and has no "expected" profile to compare against (`signature.py`) | ⚪ Gap — bmap gives a simulated/expected profile in isolation; nothing joins it to a measured, realized one |

## 04 · Conception use cases

*Material requirements and stress estimates for the next magnet generation*

| Use case | DuckDB demo | python_magnetdb |
|---|---|---|
| Simulate new-design scenarios (highest field, new helix geometry) | — N/A — this tool only analyses already-built, operating assemblies, no geometry/FEM solver | ✅ Implemented — `Simulation` model + Celery worker drive `python_magnetsetup`/Feel++ for parts and magnets of any status, including "in_study" |
| Estimate mechanical and thermal stress per helix | 🟡 Partial — retrospective hoop (mechanical) stress from measured currents, CLI only, no thermal term (`stress_map.py`) | ✅ Implemented — `thmagel`/`thmqsel` FEM toolboxes return per-helix Stress/VonMises/T (`magnetsetup.json`) |
| Compare stress estimates against the material database | 🟡 Partial — `annotate_with_rpe` compares hoop stress to `materials.rpe` — CLI only (`stress_map.py`) | 🟡 Partial — stress measures are shown; no automatic Rpe-limit overlay in the live UI |
| Fatigue-stress statistics for different science experiments | ✅ Implemented — rainflow cycle counting populates `hoop_stress_fatigue`, shown in the part page's Fatigue results panel (`compute_hoop_stats.py`) | ⚪ Gap — only exists in the vendored `to_duckdb` copy — excluded here, see scope note above |
| Mechanical analysis of materials | 🟡 Partial — Rpe-limit checks are retrospective, from measured data, not a forward materials simulation | ✅ Implemented — FEM elastic toolbox consumes Young's modulus / Poisson ratio / expansion coefficient to produce displacement and stress fields (`generate_simulation_config.py`) |

## 05 · Workshop use cases

*Defining and assembling the parts for a new or replacement magnet*

| Use case | DuckDB demo | python_magnetdb |
|---|---|---|
| Define the parts for a new magnet | — N/A — read-only over a populated warehouse, no part-authoring workflow | ✅ Implemented — Part + Material models, REST CRUD, and a "new part" form (`routes/api/parts.py`, `views/parts/new.vue`) |
| Simulate the new magnet's intended use | — N/A — no simulation capability in this tool | ✅ Implemented — same `Simulation` pipeline as the Conception cases above |
| Compare simulation results to the parts database | — N/A — no simulation capability in this tool | 🟡 Partial — per-part measures are retrievable and shown; no automatic pass/fail against part or material limits in the live app |
| Select existing parts to assemble the new magnet | — N/A — read-only, no assembly-authoring workflow | ✅ Implemented — `magnet_parts` API attaches an existing Part to a Magnet, with type compatibility enforced (`routes/api/magnet_parts.py`) |
| Describe the expected material values when a part is missing | — N/A — read-only, no part-authoring workflow | 🟡 Partial — materials/parts can be fully specified ahead of physical existence via "in_study" status; no dedicated missing-part placeholder workflow |
