# Demos

Standalone demo scripts for the student MagnetDB DuckDB.

---

## users_table_demo.py

Builds and populates the `users` table from `Data/EXPERIENCES_LOG.csv`,
fuzzy-matched against a proposals CSV (`Data/proposals_2026-07-22.csv` by
default) to fill in `research_area`, `call_number`, and `access_mode`.
Not wired into `magnetdb.py populate` yet — run standalone from the
repository root.

```bash
python to_duckdb/demos/users_table_demo.py
python to_duckdb/demos/users_table_demo.py --db to_duckdb/test-magnetdb.duckdb
python to_duckdb/demos/users_table_demo.py --from 2020-01-01
python to_duckdb/demos/users_table_demo.py --fuzzy-cutoff 0.8 --sample 10
```

| Flag | Default | Description |
|---|---|---|
| `--db` | `to_duckdb/test-magnetdb.duckdb` | Target DuckDB file |
| `--log` | `Data/EXPERIENCES_LOG.csv` | Input EXPERIENCES_LOG CSV |
| `--proposals` | `Data/proposals_2026-07-22.csv` | Input proposals CSV |
| `--from` | none (no filtering) | Discard entries before this date (Europe/Paris local time), e.g. `2020-01-01` |
| `--fuzzy-cutoff` | `0.8` | `difflib` similarity cutoff for fuzzy acronym matching |
| `--sample` | `20` | Number of resulting `users` rows to print |

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

with open("Data/proposals_2026-07-22.csv", newline="", encoding="utf-8-sig") as f:
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
