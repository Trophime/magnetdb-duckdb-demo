# Data

Raw datasets used by the `to_duckdb` / `stage` pipelines. This file
describes what each dataset contains, not how it is produced or consumed.

## Proposals

- **`proposals.csv`** — Older-schema proposals export.
  Columns: `Acronym, ProjectID, ResearchArea, Facility, ProposalType,
  accessMode, CallNumber, id, ExperimentState, Site, ShotsHourDone,
  EnergyUsed, Debut, Fin`.

- **`proposals_2026-07-22.csv`** — Current proposals export.
  Columns: `ID, Acronym, Research Area, Facility, Call Number, Type,
  Access Mode, Status, Energy Used (kWh), Magnet Sites, Experiment Start
  Date, Experiment End Date, Experiment Year`.
  Contains 47 duplicated `Acronym` values — see
  [`find_duplicate_acronyms.py`](#find_duplicate_acronymspy).

- **`proposals_2026-07-22_with_sites.csv`** — Same schema as
  `proposals_2026-07-22.csv`, with the `Magnet Sites` column filled in.

## Experiment logs

- **`EXPERIENCES_LOG.csv`** — Experiment session log.
  Columns: `timestamp, UserCode, Magnet, HStart, HStop, MinuteCount`.

- **`unmatched_users.csv`** — Leftovers from fuzzy-matching experience
  log users against proposal acronyms.
  Columns: `acronym, magnets, session_count, first_hstart, last_hstop,
  closest_proposal_acronym, fuzzy_score`.

## Time series

- **`bdd.csv`** — Time series of magnet temperatures.
  Columns: `timestamp, teb, tsb, ted, tsd`.

- **`temps.csv`** — Ambient/weather temperature time series.
  Columns: `time, temperature_2m [°C]`.

## Magnet run summaries

- **`M9_summary-{2022..2026}.json`**, **`M10_summary-{2022..2026}.json`**
  — Per-magnet (M9/M10), per-year lists of experiment run records. Each
  record has a `filename` and file-path fields for the corresponding
  overview/archive/pupitre/default/trigger/spike/hybrid_* recordings and
  runlogs, e.g. `overview`, `archive`, `pupitre`, `default`, `trigger`,
  `spike`, `hybrid_kHz`, `hybrid_rms`, `hybrid_trigger`,
  `hybrid_vprocess`, `pigbrother_runlog`, `pupitre_runlog`. Paths point
  into `LNCMIG-Data/records/...` (`.tdms` archives, pupitre `.txt` logs);
  fields are empty strings when that recording type is absent for a run.

## Scripts

- **`find_duplicate_acronyms.py`** — Finds `Acronym` values that appear
  more than once in a proposals CSV (defaults to
  `proposals_2026-07-22.csv`).

  ```
  python3 find_duplicate_acronyms.py [--rows] [csv_path]
  ```

  Without `--rows`, prints a summary (total/unique/duplicate counts and
  the list of duplicated acronyms). With `--rows`, also prints the full
  rows for each duplicated acronym.
