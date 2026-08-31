# Demos

Standalone demo scripts for the student MagnetDB DuckDB.

---

## users_table_demo.py

Builds and populates the `users` table from `Data/EXPERIENCES_LOG.csv`,
fuzzy-matched against a proposals CSV (`Data/proposals.csv` by
default) to fill in `research_area`, `call_number`, `access_mode`, `country`,
and `local_contact`. By
default the table's contents are fully replaced; pass `--sync` to instead
add only new rows and correct mismatched existing ones in place (leaving
`experiments_ids`/`overview_records_ids` untouched). After (re)populating,
the script backfills `experiments_ids` by matching each row's housing and
`[hstart, hstop]` range against `experiments`' file-embedded timestamp, and
`overview_records_ids` the same way against `overview_records.t0` —
converted from UTC (its storage timezone) to Europe/Paris local time
before comparing, since `hstart`/`hstop` are naive Europe/Paris local
time — pass `--no-link` to skip both steps. Pass `--link-only` to skip
the CSV rebuild entirely and just re-run that backfill against the
table's current contents (e.g. after populating new
`experiments`/`overview_records` rows with nothing changed on the
users/sessions side) — mutually exclusive with `--sync` and `--no-link`.
Pass `--housing M9 M10` to restrict rebuilding to those housings; sessions
for any other housing are skipped, and in full-replace mode only the
listed housings' existing `users` rows are deleted before reinserting —
other housings' rows are left untouched. Mutually exclusive with
`--link-only`. Not wired into `magnetdb.py populate` yet — run standalone
from the repository root.

Linking prints a detailed coverage report: `users` records with
`hstop IS NULL` (unlinkable — only closed sessions are matched) per
housing; matched/unmatched `experiments_ids`/`overview_records_ids`
counts with a per-housing `matched / total (%)` breakdown; how many
*distinct* `experiments`/`overview_records` rows got linked at all, per
housing, against the total available; rows linked to neither table, per
housing; and how many `sources_pupitre` entries inside `overview_records`
are also reflected in `experiments`, per housing and year. Pass
`--no-rows` to keep the summary counts/breakdowns but suppress the full
per-row listings.

```bash
python to_duckdb/demos/users_table_demo.py
python to_duckdb/demos/users_table_demo.py --db to_duckdb/test-magnetdb.duckdb
python to_duckdb/demos/users_table_demo.py --from 2020-01-01
python to_duckdb/demos/users_table_demo.py --fuzzy-cutoff 0.8 --sample 10
python to_duckdb/demos/users_table_demo.py --housing M9 M10
python to_duckdb/demos/users_table_demo.py --sync
python to_duckdb/demos/users_table_demo.py --no-link
python to_duckdb/demos/users_table_demo.py --link-only
python to_duckdb/demos/users_table_demo.py --link-only --no-rows
```

| Flag | Default | Description |
|---|---|---|
| `--db` | `to_duckdb/test-magnetdb.duckdb` | Target DuckDB file |
| `--log` | `Data/EXPERIENCES_LOG.csv` | Input EXPERIENCES_LOG CSV |
| `--proposals` | `Data/proposals.csv` | Input proposals CSV |
| `--from` | none (no filtering) | Discard entries before this date (Europe/Paris local time), e.g. `2020-01-01` |
| `--fuzzy-cutoff` | `0.8` | `difflib` similarity cutoff for fuzzy acronym matching |
| `--sample` | `20` | Number of resulting `users` rows to print |
| `--housing` | `ALL` (no filtering) | Restrict rebuilding to these housings (e.g. `M9 M10`); other housings' existing rows are left untouched in full-replace mode. Mutually exclusive with `--link-only` |
| `--sync` | off (full replace) | Add new rows and fix mismatched existing rows instead of replacing the whole table's contents |
| `--no-link` | off (linking runs) | Skip backfilling `experiments_ids`/`overview_records_ids` after (re)populating |
| `--link-only` | off | Skip the CSV rebuild entirely; just re-run the `experiments_ids`/`overview_records_ids` backfill against the table's current contents. Mutually exclusive with `--sync`/`--no-link` |
| `--no-rows` | off (rows shown) | Skip the full per-row listings in the coverage/unlinked reports (summary counts and breakdowns are always printed) |

---

## find_research_area_candidates.py

Helps resolve `users` rows with `research_area IS NULL`. Splits them into
two buckets:

- **Tech Staff**: acronym is `"EXPLOIT."` or contains `"test"`
  (case-insensitive) — internal LNCMI exploitation/testing sessions, never
  backed by a real proposal. Reported only by default; pass
  `--apply-tech-staff` to write `research_area = "LNCMI Tech Staff"` for
  these rows (only `research_area` is touched).
- **Candidate search**: the remaining genuinely-unmatched acronyms
  (`research_area`/`call_number`/`access_mode` all `NULL`) are searched
  against `proposals.csv` for proposals whose date coverage (exact
  `Experiment Start/End Date`, or `Experiment Year` when dates are blank)
  overlaps that acronym's session `hstart`/`hstop`, ranked by acronym
  similarity (`difflib.SequenceMatcher` ratio). Read-only — prints
  candidates for manual review, never writes.

```bash
python to_duckdb/demos/find_research_area_candidates.py
python to_duckdb/demos/find_research_area_candidates.py --apply-tech-staff
python to_duckdb/demos/find_research_area_candidates.py --acronym GSO02
python to_duckdb/demos/find_research_area_candidates.py --top 5 --min-score 0.5
```

| Flag | Default | Description |
|---|---|---|
| `--db` | `to_duckdb/test-magnetdb.duckdb` | Target DuckDB file |
| `--proposals` | `Data/proposals.csv` | Input proposals CSV |
| `--top` | `10` | Maximum candidates printed per acronym |
| `--acronym` | none (all acronyms) | Restrict the candidate search to a single acronym |
| `--min-score` | `0.0` | Minimum acronym-similarity score for a candidate to be shown |
| `--apply-tech-staff` | off (dry run) | Write `research_area='LNCMI Tech Staff'` for the tech-staff bucket |

---

## find_linking_candidates.py

Companion to `find_research_area_candidates.py`. For `users` rows with no
`experiments_ids` (resp. no `overview_records_ids`), searches same-housing
`experiments` (resp. live `overview_records`) for the nearest file(s) by
the timestamp embedded in the filename, and scores them by proximity to
`[hstart, hstop]`. Both the pupitre filename
(`"YYYY.MM.DD - HH:MM:SS.txt"`) and the Overview filename
(`"<housing>_Overview_YYMMDD-HHMM"`) embed Europe/Paris local time
directly, same as `hstart`/`hstop` — this reads the raw filename rather
than the `overview_records.t0` column (which is stored in UTC), so no
timezone conversion is needed. Distance `0` means the candidate's
timestamp falls inside `[hstart, hstop]`; otherwise it's the time to the
nearer window edge, converted to a score (`1 / (1 + distance_hours)`).
Read-only — prints candidates for manual review, never writes.

```bash
python to_duckdb/demos/find_linking_candidates.py
python to_duckdb/demos/find_linking_candidates.py --acronym GIS0122
python to_duckdb/demos/find_linking_candidates.py --top 5 --max-distance-hours 6
```

| Flag | Default | Description |
|---|---|---|
| `--db` | `to_duckdb/test-magnetdb.duckdb` | Target DuckDB file |
| `--top` | `3` | Maximum candidates printed per row |
| `--max-distance-hours` | `24.0` | Only show candidates within this many hours of the session window |
| `--acronym` | none (all acronyms) | Restrict the search to a single acronym |

---

## list_users_unlinked.py

Prints `users` rows where both `experiments_ids` and `overview_records_ids`
are `NULL` — i.e. sessions that couldn't be linked to any `experiments` or
`overview_records` row.

```bash
python to_duckdb/demos/list_users_unlinked.py
python to_duckdb/demos/list_users_unlinked.py --db to_duckdb/test-magnetdb.duckdb
```

| Flag | Default | Description |
|---|---|---|
| `--db` | `to_duckdb/test-magnetdb.duckdb` | Target DuckDB file |

---

## retire_superseded_magnets.py

For every `helix`/`bitter`/`supra` part, builds that part's magnet-usage
history (`magnet_parts`, ordered by `assembled_at`) and flags every magnet
in that history except the most recently assembled one. The deduplicated
union of flagged magnets is set to `status='retired'` via
`update_magnet_status` (status_history logged, the magnet's own parts
cascaded to `in_stock`). A magnet with no `assembled_at` can't be ordered,
so it's skipped with a warning and left untouched; a magnet already
`retired` or `dead` is also left untouched, so re-running is a no-op once
every candidate has been processed.

The rule is per-part and literal: a magnet is retired if it is not the
latest holder of *any* shared coil part, even if it is still the latest
holder of a different one.

Writes by default; pass `--dry-run` to preview.

```bash
python to_duckdb/demos/retire_superseded_magnets.py --dry-run
python to_duckdb/demos/retire_superseded_magnets.py --db to_duckdb/test-magnetdb.duckdb
```

| Flag | Default | Description |
|---|---|---|
| `--db` | `to_duckdb/test-magnetdb.duckdb` | Target DuckDB file |
| `--dry-run` | off (writes) | Preview changes without writing anything |

---

## plot_magnet_stress.py

Plots magnetic field and hoop stress for a magnet across a given list of
experiments. For each `--experiments` entry: loads the raw pupitre file via
`python_magnetrun.MagnetRun.load_mrun()` (same call the dashboard's File
Viewer page uses) and plots its `Field` [T] channel, then looks up
`hoop_stress_processed.parquet_path` for that experiment and, **only if the
Parquet file already exists on disk**, loads it and plots the hoop-stress
[MPa] columns for the magnet's parts (`magnet_parts`/`parts`). No hoop-stress
computation is performed — if the Parquet is missing (recorded or not), that
panel is skipped with a hint pointing at `magnetdb.py hoop-stress compute`.
Missing experiments, missing pupitre files, or a magnet with no parts are all
skipped with a warning rather than raising. One PNG (Field on top, hoop
stress on bottom, sharing the time axis) is saved per experiment.

```bash
python to_duckdb/demos/plot_magnet_stress.py --magnet M19061901 \
    --experiments "2019.06.19 - 17:00:45" "2019.06.19 - 17:04:21"
python to_duckdb/demos/plot_magnet_stress.py --magnet M19061901 \
    --experiments "2019.06.20 - 14:36:30" --db to_duckdb/test-magnetdb.duckdb \
    --output-dir stage/
```

| Flag | Default | Description |
|---|---|---|
| `--magnet` | *(required)* | Magnet name (`magnets.name`) |
| `--experiments` | *(required)* | One or more experiment names (`experiments.name`) |
| `--db` | `test-magnetdb.duckdb` | Target DuckDB file |
| `--output-dir` | `.` | Directory to save PNG figures into |

---

## plot_magnet_fatigue.py

Plots rainflow fatigue cycles for a magnet's parts across a given list of
experiments, reading the already-persisted `hoop_stress_fatigue` (per-part
cycle totals) and `hoop_stress_fatigue_bins` (per-part rainflow range-bin
matrix) tables written by `magnetdb.py hoop-stress compute`. No fatigue
computation is performed here — pairs with no rows in either table are
skipped with a hint pointing at that command.

`--parts` is optional: when omitted (or empty), it defaults to every part of
`--magnet` whose type is `helix`, `bitter`, or `supra`; when given
explicitly, the same type filter is applied and anything else (wrong type,
or not found in `parts`) is dropped with a warning.

For each part, three PNGs are produced (all given experiments combined onto
a single figure each): `fatigue_cycles_<magnet>_<part>.png` (cycle count per
experiment), `fatigue_histogram_<magnet>_<part>.png` (cycle histogram over
stress-range bins, grouped by experiment), and
`fatigue_combined_<magnet>_<part>.png` (the same histogram summed across the
whole experiment list). A cycle-count table (experiments x parts, with
row/column totals and a grand-total `TOTAL` row) is printed to stdout.

```bash
python to_duckdb/demos/plot_magnet_fatigue.py --magnet M9Bitters \
    --experiments "2023.06.09 - 09:43:40" "2023.06.09 - 10:21:37"
python to_duckdb/demos/plot_magnet_fatigue.py --magnet M9Bitters \
    --parts M9Be --experiments "2023.06.09 - 09:43:40" \
    --db to_duckdb/test-magnetdb.duckdb --output-dir stage/
```

| Flag | Default | Description |
|---|---|---|
| `--magnet` | *(required)* | Magnet name (`magnets.name`) |
| `--experiments` | *(required)* | One or more experiment names (`experiments.name`) |
| `--parts` | all `helix`/`bitter`/`supra` parts of `--magnet` | Part names (`parts.name`) to analyze, restricted to `helix`/`bitter`/`supra` types |
| `--db` | `test-magnetdb.duckdb` | Target DuckDB file |
| `--output-dir` | `.` | Directory to save PNG figures into |

---

## Building `Data/unmatched_users.csv`

This file is a report of `EXPERIENCES_LOG` acronyms that `users_table_demo.py`
could not match to any proposal — useful for spotting genuine typos that fell
outside `--fuzzy-cutoff`, versus codes that were never real proposal acronyms
(test/maintenance codes, etc.). It's a manual recipe run against an existing
populated `users` table, not a saved script.

Note: `find_research_area_candidates.py` above automates finding candidates
for this same unmatched set (same base query as step 1, and the same
fuzzy-score technique as step 3), but does date/year-based proposal matching
rather than producing a flat CSV. Use this recipe instead when you
specifically want a standalone `Data/unmatched_users.csv` file (e.g. to share
or filter further by hand).

**1. Base report** — one row per unmatched acronym, with the magnets used,
session count, and session date range:

```python
import csv
import re
from datetime import datetime

import duckdb

HLOG_TS_RE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2})\s+(\d{1,2}:\d{2}:\d{2}\.\d+)\s*(AM|PM)?$")


def parse_hlog_ts(raw: str):
    """Parse HStart/HStop: 24h time with a spurious trailing AM/PM tag."""
    raw = raw.strip()
    m = HLOG_TS_RE.match(raw)
    if not m:
        return None
    date_part, time_part, _ampm = m.groups()
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%m/%d/%y %H:%M:%S.%f")
    except ValueError:
        return None


con = duckdb.connect("to_duckdb/test-magnetdb.duckdb", read_only=True)
rows = con.execute(
    "SELECT acronym, housing FROM users "
    "WHERE research_area IS NULL AND call_number IS NULL AND access_mode IS NULL"
).fetchall()
con.close()

unmatched = {acronym: housing for acronym, housing in rows}
session_count = {a: 0 for a in unmatched}
first_hstart = {a: None for a in unmatched}
last_hstop = {a: None for a in unmatched}

with open("Data/EXPERIENCES_LOG.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        acronym = row["UserCode"].strip()
        if acronym not in unmatched:
            continue
        session_count[acronym] += 1

        ts = datetime.fromisoformat(row["timestamp"].strip())
        if first_hstart[acronym] is None or ts < first_hstart[acronym]:
            first_hstart[acronym] = ts

        hstop = parse_hlog_ts(row["HStop"])
        if hstop is not None and (last_hstop[acronym] is None or hstop > last_hstop[acronym]):
            last_hstop[acronym] = hstop

with open("Data/unmatched_users.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["acronym", "magnets", "session_count", "first_hstart", "last_hstop"])
    for acronym in sorted(unmatched):
        writer.writerow(
            [
                acronym,
                ";".join(unmatched[acronym]),
                session_count[acronym],
                first_hstart[acronym].isoformat(sep=" ") if first_hstart[acronym] else "",
                last_hstop[acronym].isoformat(sep=" ") if last_hstop[acronym] else "",
            ]
        )
```

**2. Date filter** — keep only rows with `first_hstart` on or after a cutoff
(e.g. `2018-01-01`):

```python
import csv

cutoff = "2018-01-01"
with open("Data/unmatched_users.csv", newline="", encoding="utf-8") as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = [r for r in reader if r[3] >= cutoff]

with open("Data/unmatched_users.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(rows)
```

**3. Fuzzy-score enrichment** — add `closest_proposal_acronym`/`fuzzy_score`
(no cutoff this time) to show how close each unmatched acronym came to a real
proposal acronym:

```python
import csv
import difflib

with open("Data/proposals.csv", newline="", encoding="utf-8-sig") as f:
    candidates = sorted({row["Acronym"].strip() for row in csv.DictReader(f) if row["Acronym"].strip()})

with open("Data/unmatched_users.csv", newline="", encoding="utf-8") as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = list(reader)

out_rows = []
for row in rows:
    acronym = row[0]
    close = difflib.get_close_matches(acronym, candidates, n=1, cutoff=0.0)
    best = close[0] if close else ""
    score = difflib.SequenceMatcher(None, acronym, best).ratio() if best else 0.0
    out_rows.append(row + [best, f"{score:.3f}"])

with open("Data/unmatched_users.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(header + ["closest_proposal_acronym", "fuzzy_score"])
    writer.writerows(out_rows)
```
