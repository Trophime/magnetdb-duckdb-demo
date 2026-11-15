# Hybrid viewer page

Status: **awaiting approval, not implemented** (drafted 2026-11-03).

## Original ask

> I would like to add a dashboard for hybrid data.
> Some like file_viewer.py
> Start by loading a pupitre file.
> From pupitre timestart and end, select the proper data from HYBRID_DATA_DIR
> -- see python_magnetrun/examples

## Goal

A new `/hybrid_viewer` page that works like File viewer
(`apps/dashboards/magnetdb/src/pages/file_viewer.py`): pick an assembly and a
Pupitre file, take its UTC start/end, load only the matching days/hours of
Hybrid data from `HYBRID_DATA_DIR`, and plot the selected Hybrid channels on the
same time axis as chosen Pupitre fields.

## Findings

- `HYBRID_DATA_DIR` = `~/LNCMIG-Data/records/CEA`. kHz data is stored per day,
  per FEPC system, one file per **UTC** hour:
  `kHz/2026-11-02/FEPC-LNCMI/00HOST_1_LIST_0.bin`. RMS data uses the same
  per-day layout: `rms/<date>/<system>/*.rms`.
- `HybridRun.getData(key, hours=...)` returns `(data, t)`, where `t` counts
  seconds from HH:00 UTC of the **first hour file actually read**
  (`compute_hour_t0` in `hybrid/kHz/fepc_reader.py`).
- Archived days (`kHz/2024/<date>/`, `kHz/2025-04-24.tar.gz`) can't be read by
  `HybridData`, which only looks in `kHz/<date>/`.
- `overview_records.sources_hybrid_kHz` is empty in
  `magnetdb-2026-10-08.duckdb`, so the page finds Hybrid data on disk from the
  Pupitre time range, not through a DB link.
- Reference example: `python_magnetrun/examples/plot_hybrid_with_pupitre_tdms.py`
  (maps `kHz/FEPC-AUX-LNCMI/ALIM1_J1` to Pupitre `Idcct1`, etc. for M8).

## Files affected

| Path | Action |
|---|---|
| `apps/dashboards/magnetdb/src/pages/hybrid_viewer.py` | create |
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | edit: append helpers only (the file has unrelated uncommitted changes, left untouched) |
| `apps/dashboards/magnetdb/tests/hybrid_viewer_test.py` | create |

## Approach

1. **Write the tests first** in `hybrid_viewer_test.py`, covering:
   - `hybrid_day_hours(start, end)`: within one hour, across several hours, and
     across UTC midnight (gives two `(date, hours)` entries).
   - Anchoring: the first hour actually available is used as t0 when the
     requested start hour has no file (fake directory in `tmp_path` holding
     empty `HHHOST_…` files).

   → verify: the tests fail because the helpers don't exist yet.
2. **Add helpers to `magnetdb_analysis.py`** (NumPy docstrings):
   - `hybrid_day_hours(start, end) -> list[tuple[str, list[int]]]`: splits a
     naive-UTC range into UTC days and their hours.
   - `list_hybrid_keys(date_str, fepc_system, data_type) -> list[str]`: the
     channel list from `HybridRun.getKeys()`, filtered by `kHz/` or `rms/` and
     by system.
   - `load_hybrid_series(key, housing, assembly, start, end, n_out) ->
     DataFrame[timestamp, value]`: for each day, keeps only the requested
     hours that have a file, anchors on the first of those, crops to
     `[start, end]`, then downsamples with `getData(downsample=n_out)`.
     Cached with `functools.lru_cache(maxsize=8)`.

   → verify: the step-1 tests pass.
3. **Create `pages/hybrid_viewer.py`** (`order=12`, ids prefixed `hv-`),
   reusing `dash_selectors` the same way `file_viewer` does:
   1. Housing, year and status filters, then the assembly selector.
   2. Pupitre file dropdown: only `.txt` files from `get_files_for_assembly`.
   3. Info banner: Pupitre time range in local time, plus which Hybrid days and
      hours were found for each FEPC system. If none were found: "no Hybrid
      data (archived or missing)".
   4. FEPC system (`FEPC-LNCMI` / `FEPC-AUX-LNCMI`) and data type (`kHz` /
      `rms`).
   5. Hybrid channel multi-select, filled from `list_hybrid_keys`.
   6. Pupitre field multi-select for the overlay (e.g. `Idcct1`, `Field`).
   7. Point budget for downsampling (default 20 000 per trace).
   8. One figure with two rows sharing the x axis (Hybrid on top, Pupitre
      below), using the same local-time display as `file_viewer`; zooming one
      row zooms both.

   → verify: the page imports cleanly, and `pytest` from
   `apps/dashboards/magnetdb --ignore=tests/mrun_test.py` still passes 159
   tests plus the new ones.
4. **Manual check:** run the dashboard on one M8 Pupitre file whose date has an
   uncompressed `kHz/<date>/` directory (picked read-only from the DB and the
   mount).

   → verify: Hybrid `ALIM1_J1` lines up in time with Pupitre `Idcct1`, as in
   `plot_hybrid_with_pupitre_tdms.py`'s mapping.

## Open questions

1. **Scope of assemblies:** default the housing filter to **M8**, with every
   housing still selectable? Or show M8 only?
2. **Archived days** (`kHz/<year>/…`, `.tar.gz`): show "not available" rather
   than adding archive support to the dashboard?
3. **Data types:** kHz and RMS only for now; trigger and vprocess left out?
4. **Downsampling:** fixed point budget at load time, no full-resolution reload
   on zoom (possible follow-up).
5. **Translations:** new strings go through `i18n._()` but get no French
   entries in `locales/`. Add them?

## Noticed but not touching

- `HybridRun.getData` writes `hours` into `self.default_options`, so it carries
  over to later calls on the same object (python_magnetrun). The helper avoids
  this by creating a new `HybridRun` for each load.
- `load_hybrid_supra_current` uses `range(start.hour, end.hour + 1)`, which
  breaks when a run crosses UTC midnight.
