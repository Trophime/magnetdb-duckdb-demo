# Plan: plot defaults & spikes over a magnet's lifetime

**Status:** awaiting approval

## Goal

A standalone helper script that, given `--magnet`, plots the number of
defaults and spikes recorded over its whole life (across every assembly it
has been part of) and saves a PNG.

## Data findings

- **Magnet → assemblies:** `assembly_magnets(assembly_name, magnet_name)`.
  Its `commissioned_at` is always NULL and its `decommissioned_at` is the
  same as the assembly's. So once the magnet's assemblies are known, every
  overview record of those assemblies belongs to the magnet. No extra date
  filtering is needed.
- **Assembly → records:** `overview_records.assembly_name`. Each record has
  `t0` plus two lists of files, `sources_default` and `sources_spike`.
  Counting the files in those lists gives the defaults and spikes.
- **Duplicates:** 4 default files appear in two different records (2240
  references, 2236 distinct files). Count each file only once.
- **Sanity reference (`magnetdb-2026-10-08.duckdb`):** `M10Bitters` has
  37 assemblies, 891 records, about 917 default references (slightly fewer
  after removing duplicates) and 3136 spikes, from 2022-02 to 2026-05.
  `M9Bitters` has 241 defaults and 0 spikes.

## Files affected

| Path | Action |
|---|---|
| `to_duckdb/demos/plot_magnet_incidents.py` | create |
| `to_duckdb/demos/README.md` | edit (add a section in the same format as `plot_magnet_fatigue.py`) |

## Approach

1. `_get_magnet_assemblies(con, magnet)` reads the magnet's assemblies from
   `assembly_magnets` joined to `assemblies`, with commissioned/decommissioned
   dates, sorted by date. If the magnet is unknown or has no assemblies, the
   script exits with a message.
   → verify: unknown magnet name exits cleanly.
2. `_get_incidents(con, assemblies)` builds one row per distinct default or
   spike file: `(file, type, assembly_name, t0)`. It unnests
   `sources_default` and `sources_spike` from `overview_records` where
   `assembly_name IN (...)` and `merged_into IS NULL`.
   → verify: counts match an independent SQL `COUNT(DISTINCT ...)`.
3. Count the rows per month, separately for defaults and spikes. There are
   about 10× more spikes than defaults, so each type gets its own panel:
   - two stacked subplots sharing the time axis (defaults on top, spikes
     below), as monthly bars;
   - a cumulative line on a second y-axis in each panel;
   - thin vertical lines at assembly changes, so the bars can be read per
     assembly.

   → verify: open the PNG; the time span and assembly markers are where
   expected.
4. Print a per-assembly table to stdout: assembly, period, number of
   records, defaults, spikes, plus a `TOTAL` row.
   → verify: `TOTAL` matches step 2's SQL cross-check.
5. Command line, modelled on `plot_magnet_fatigue.py`:

   | Flag | Default | Description |
   |---|---|---|
   | `--magnet` | required | Magnet name |
   | `--db` | `DEFAULT_DB` | DuckDB file (opened read-only) |
   | `--output-dir` | `.` | Directory for `incidents_<magnet>.png` |

6. Add the README section with usage examples.

## Verification

1. Run:
   ```bash
   .venv/bin/python to_duckdb/demos/plot_magnet_incidents.py \
       --magnet M10Bitters --db to_duckdb/magnetdb-2026-10-08.duckdb \
       --output-dir <scratchpad>
   ```
   The `TOTAL` row should match an independent SQL count of distinct files
   (about 913 defaults, 3136 spikes).
2. Open the PNG and check that the time span is 2022-02 to 2026-05 and that
   the assembly markers are where expected.
3. Run with `--magnet M9Bitters`, which has 0 spikes: the spikes panel should
   be empty without crashing.
4. Run with an unknown magnet name: it should exit cleanly with a message.

## Assumptions & open questions

1. **Time position:** each default or spike is placed at its record's `t0`.
   The time in the file name is more precise, but that only matters at
   less-than-a-day resolution, and monthly bins don't need it. Use per-event
   timestamps instead?
2. **Binning:** monthly by default. Add a `--freq` option (week/month/year),
   or use per-assembly bars instead of calendar bins?
3. **Default subtypes:** default files carry a fault subtype in their name,
   such as `Courants50Hz`. Counts are not broken down by subtype unless
   wanted.
4. **Output and location:** a static matplotlib PNG in `to_duckdb/demos/`,
   like the other plot helpers, rather than a page in the Dash app.
5. **Tests:** no automated test. This is a demo script, and pytest isn't
   installed in `.venv` yet. Verification is the manual SQL cross-check
   above. A fixture-based test for `_get_incidents` in `to_duckdb/tests/`
   can be added if wanted.
