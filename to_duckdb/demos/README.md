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
`overview_records_ids` the same way against `overview_records.t0` — pass
`--no-link` to skip both steps. Pass `--link-only` to skip the CSV rebuild
entirely and just re-run that backfill against the table's current
contents (e.g. after populating new `experiments`/`overview_records` rows
with nothing changed on the users/sessions side) — mutually exclusive with
`--sync` and `--no-link`. Not wired into `magnetdb.py populate` yet —
run standalone from the repository root.

```bash
python to_duckdb/demos/users_table_demo.py
python to_duckdb/demos/users_table_demo.py --db to_duckdb/test-magnetdb.duckdb
python to_duckdb/demos/users_table_demo.py --from 2020-01-01
python to_duckdb/demos/users_table_demo.py --fuzzy-cutoff 0.8 --sample 10
python to_duckdb/demos/users_table_demo.py --sync
python to_duckdb/demos/users_table_demo.py --no-link
python to_duckdb/demos/users_table_demo.py --link-only
```

| Flag | Default | Description |
|---|---|---|
| `--db` | `to_duckdb/test-magnetdb.duckdb` | Target DuckDB file |
| `--log` | `Data/EXPERIENCES_LOG.csv` | Input EXPERIENCES_LOG CSV |
| `--proposals` | `Data/proposals.csv` | Input proposals CSV |
| `--from` | none (no filtering) | Discard entries before this date (Europe/Paris local time), e.g. `2020-01-01` |
| `--fuzzy-cutoff` | `0.8` | `difflib` similarity cutoff for fuzzy acronym matching |
| `--sample` | `20` | Number of resulting `users` rows to print |
| `--sync` | off (full replace) | Add new rows and fix mismatched existing rows instead of replacing the whole table's contents |
| `--no-link` | off (linking runs) | Skip backfilling `experiments_ids`/`overview_records_ids` after (re)populating |
| `--link-only` | off | Skip the CSV rebuild entirely; just re-run the `experiments_ids`/`overview_records_ids` backfill against the table's current contents. Mutually exclusive with `--sync`/`--no-link` |

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

## Building `Data/unmatched_users.csv`

This file is a report of `EXPERIENCES_LOG` acronyms that `users_table_demo.py`
could not match to any proposal — useful for spotting genuine typos that fell
outside `--fuzzy-cutoff`, versus codes that were never real proposal acronyms
(test/maintenance codes, etc.). It's a manual recipe run against an existing
populated `users` table, not a saved script.

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
