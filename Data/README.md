# Data

Raw datasets used by the `to_duckdb` / `stage` pipelines. This file
describes what each dataset contains; how the magnet run summaries are
produced is noted in their section.

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

- **`EXPERIENCES_LOG.csv`** — Experiment session log (SUPERVISION), one row
  per coil (`Magnet`: `M9i`, `M9e`, …) and session.
  Columns: `timestamp, UserCode, UserName, OperatorName, Magnet, ElecGroup,
  HStart, HStop, MinuteCount, Paimant, Pmax, Phydraulique, Ptotale,
  dDepassement, nDepassement, Cout, Qtotale, QCout`.
  `HStart`/`HStop` are Paris local time with a spurious AM/PM marker
  (`8/31/06  14:50:56.078 PM`); `HStop` is blank for unclosed sessions.
  Do not use `timestamp`: it drifts from `HStart` since 2020 (≈7.5 h in
  2025–26). `EXPLOIT.` and `EXPLOIT` are the same operator account.
  See [Producing a sessions file](#producing-a-sessions-file).

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

### Producing a summary file

A summary covers one housing and one year. It is written by the
`python_magnetrun` analysis command from that year's Overview TDMS files:

```bash
source .venv/bin/activate
magnetrun analysis 'M9_Overview_25*.tdms' --housing M9 --output-dir /tmp/M9_2025 > M9_2025.log
mv /tmp/M9_2025/summary.json Data/M9_summary-2025.json
```

- A pattern without a directory is looked up in the current directory, then
  in the pigbrother data directory under `<housing>/Overview`.
- The command always names its output `summary.json` (in `--output-dir`,
  default: the current directory). Rename it `<housing>_summary-<YYYY>.json`:
  `scripts/build_from_scratch.sh` only loads `Data/M*_summary-YYYY.json` files
  (step `overview-json`).

### Producing a sessions file

`magnetrun sessions` builds one record per `EXPERIENCES_LOG.csv` session of a
housing and lists the files recorded during its window, whether or not an
Overview file exists (it covers 2018 → now, including M10 in 2019, which has
only pupitre files). Files claimed by no session are grouped into unlogged
records (`logged: false`).

```bash
source .venv/bin/activate
magnetrun sessions --log Data/EXPERIENCES_LOG.csv --housing M9 \
    --from 2018-01-01 --to 2019-01-01 --output-dir /tmp/M9_2018
```

The output is always named `sessions.json` (in `--output-dir`). It is not
loaded by `scripts/build_from_scratch.sh` yet. Record fields are described in
`python_magnetrun/python_magnetrun/analysis/README.md` (section `sessions.py`).

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
