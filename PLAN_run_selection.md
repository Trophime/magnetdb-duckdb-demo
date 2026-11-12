# Plan: select runs of a magnet by combinable criteria

**Status (2026-11-10).** Design discussion only, saved for later. **Not
approved; no code written.** The interface below is a draft. The open
questions at the end must be answered before a full implementation plan
(files, steps, tests) is written and submitted for approval.

---

## Goal

Select **experiments**, **operationaldata** and/or **overview records**
related to a magnet, by one or more criteria combined together. Examples
given (the list is not exhaustive):

- the longest "run" (longest duration);
- runs where the field exceeds a given value;
- runs with a plateau longer than a given duration, or above a given field;
- runs with the most defaults attached;
- runs in a from/to time range.

Two of these are **rankings**, not filters: "longest run" and "most
defaults" need a sort and a limit (`--sort duration --limit 1`), not a
threshold.

---

## What the database can answer today

Checked on `to_duckdb/magnetdb-2026-11-05.duckdb` (built before A24).

| Criterion | experiments | operationaldata | overview_records |
|---|---|---|---|
| magnet / part / assembly | ✅ `experiments view --magnet` | ✅ `operationaldata view` | ✅ `overview-records view` |
| from/to | ✅ time parsed from the file name (Paris local) | ✅ time parsed from the file name | ✅ `t0` (UTC) |
| duration [s] | ✅ `exp_run_scalars.duration_s`, `duration_field_on_s` (6,509 of 6,542 runs) | ⚠️ `op_run_scalars` for the 6,536 `Pupitre` rows only (same files as `experiments`); nothing for TDMS files | ✅ `duration` |
| maximum field [T] | ✅ `exp_run_scalars.field_max` (also mean, median, std) — **recorded FF×I field**, see below | ❌ | ❌ no field column, `metrics` empty |
| plateau duration / field | ❌ | ❌ | ❌ `plateaux` empty for all 1,833 records (roadmap S2, after S1) |
| number of defaults | ❌ (could be borrowed from overview records) | a `Default` row **is** one default (4,378 rows) | ✅ `len(sources_default)`: 561 records have at least one, max 190 |

**After A24** (code done, applied at the next build), each `operationaldata`
row also has:

- `t_start`, `t_end` in UTC, like `t0`. `Spike` / `Default` files are single
  events: `t_start = t_end` = the file-name time.
- `mode` for `Overview` rows.
- `teb_mean`, `bp_mean` for `Pupitre` rows (`op_run_scalars`).

So `operationaldata` could then be selected by exact time range, type, mode
and duration (`t_end − t_start`, now also for TDMS files). Still missing
after A24: the field of a TDMS file (needs a new build step) and a number of
defaults (only meaningful on overview records, or by counting `Default`
files in a time window).

`magnetdb-2026-11-09.duckdb` (68 MB) has the A24 columns but **no rows** in
`operationaldata` / `overview_records`: that build looks unfinished. Use the
2026-11-05 database for tests until a complete A24 build exists.

---

## Proposed interface (draft)

One new subcommand; every criterion is optional; criteria combine with AND.

```bash
python to_duckdb/magnetdb.py select experiments      --magnet M10Bitters --min-field 30 --from 2024-01-01 --sort duration --limit 5
python to_duckdb/magnetdb.py select overview-records --magnet M10Bitters --min-defaults 1 --sort defaults --limit 1
python to_duckdb/magnetdb.py select overview-records --magnet M10Bitters --sort duration --limit 1   # longest run
```

- **Criteria as a lookup table:** one entry per criterion, mapping a flag and
  a table to an SQL expression and a unit. Adding a criterion = adding one
  entry, not new query code.
- **Output:** one row per match with its name, assembly and date, plus the
  columns used by the criteria, so it is visible why each row was picked.
- **Where:** a new module `to_duckdb/run_selection.py` builds the query;
  `magnetdb.py` gets the `select` subcommand. The existing `* view` commands
  are left as they are (rebasing them on the new module would be a separate
  change).
- **Plateaux:** left out until S2 fills `overview_records.plateaux`.
  Detecting plateaux on the fly from the files would be far too slow for the
  whole database.
- **Alternative set aside:** a generic `--where "field_max > 30 AND
  duration_s > 600"`. More flexible, but the user must know the column
  names. Start with named flags; add `--where` only if criteria without a
  flag keep coming up.

---

## Facts the design depends on

### Time zones (verified 2026-11-10)

| Source | Time zone |
|---|---|
| pupitre / pigbrother file names, pupitre `Date`/`Time` rows | Paris local |
| TDMS `wf_start_time` (inside the file) | **UTC** |
| `overview_records.t0` | UTC (all 1,833 records convert exactly to their file-name time) |
| `operationaldata.t_start` / `t_end` (A24) | UTC |
| `experiments`, pre-A24 `operationaldata` | no time column; time from the file name (local) |
| assembly JSON dates → `assemblies.commissioned_at` / `decommissioned_at` | Paris local, stored **naive** |
| `users.hstart` / `hstop` | naive Paris |
| hybrid files | not checked |

Rules for `select`: the database stores UTC; the CLI reads and prints
**Paris local time**. `--from/--to` are converted to UTC before comparing
with `t0` / `t_start`, and compared directly with file-name times. The
repeated autumn hour uses `fold=0` (`local_to_utc_naive`). Assembly dates are
treated as Paris time, whichever fix is chosen (open question 7).

Readers of assembly dates disagree today: `etl_spec._assembly_window` reads
them as Paris; `populate._assembly_window`, `impact.py:254` and
`demos/archive_magnet_data.py` read them as `--db-tz` (default UTC, never set
by the build). Measured impact on the 2026-11-05 database: 0 of 1,833
overview records and 0 of 6,542 experiments would change assembly (nothing
runs during the 07:00–10:00 handover).

### Field

- pupitre `Field` [T] and pigbrother `Courants_Alimentations/Champ_magn` [mT]
  are **not measurements**: both are recomputed as B = FF1·I₁ + FF2·I₂ with
  each system's own configured field factors, which may differ between
  pupitre and pigbrother. A field criterion therefore means "**recorded
  field (FF×I)**" and is only as reliable as the configured factors.
- The currents (`Idcct*`, `Courant_GR*`) **are** measurements; a maximum
  current per circuit would be a more robust criterion, but is not stored
  (`exp_run_scalars` has no current channel).
- The only physical field measurement is the commissioning **pickup-coil**
  step; those data are not available yet
  ([PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md) §Field factor).
- TDMS layout:
  - Overview / Archive / Default / Spike: `Courants_Alimentations/Champ_magn`,
    unit `millitesla` → /1000 for T.
  - ManuelTrig: spelled `Champ magn` (with a space), unit `Volts`.
  - SignalStats, new format `M<n>_Stats_…` (from mid-2021):
    `Stats_moy/moy_Champ_magn` (+ `sig_`, `lowf_`, `midf_`, `highf_`); unit
    string says `Volts` but values are mT.
  - SignalStats, old format `M<n>_Stats__…` (until mid-2021): no field
    channel.
- Reading cost: Overview files open quickly (≈ 0.1 s metadata, a few seconds
  per channel); Archive files take 7–42 s each (no index).

### Duplicates

24 pupitre files are stored under two housings (data issue #16 in
[PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md)): each is an
experiment, and an `operationaldata` Pupitre row, twice. A selection by
magnet can return the wrong copy, and comparing a pupitre run with the
pigbrother files of the same housing can pair two different magnets.

---

## Open questions

| # | Question | Options (recommendation in bold where one was given) |
|---|---|---|
| 1 | Criteria for `operationaldata` | time range, type, mode, duration after A24 — enough? Or a TDMS field step in the build (see #3)? |
| 2 | Which field counts for "field above X" | recorded FF×I field, labelled as such / maximum current per circuit (new scalars in the stats step) / both |
| 3 | Field step for Overview files | store `field_max` / mean [T] per Overview file from `Champ_magn`/1000 (extension of A24) / keep field experiments-only for now |
| 4 | Field for overview records without #3 | borrow `field_max` from the experiments in `sources_pupitre` / no field criterion on overview records |
| 5 | Output | screen only / also CSV / JSON (e.g. to feed `demos/archive_magnet_data.py` or the dashboard) |
| 6 | Time-zone bug in `overview-records view --from/--to` ([crud.py:2667-2672](to_duckdb/crud.py#L2667-L2672)): local input compared with UTC `t0`, off by 1 h (winter) / 2 h (summer) | fix in the `select` plan / separate plan |
| 7 | Assembly dates (Paris-naive, read as UTC by some readers) | A: store in UTC (convert JSON on insert, migrate rows, convert back in `etl export` and displays) / **B: declare them Paris local, fix the three UTC readers, document in the schema** (no migration); now or later |
| 8 | Per-file FF fit (least squares of recorded field on circuit currents) as a source of **configured** factors | worth planning? Fails when the two currents are proportional; one factor per circuit |
| 9 | Duplicate pupitre copies (data issue #16) | skip them in the build before cross-source selection (explicit list, or header magnet vs assembly check) and recompute stats / leave for a separate cleanup |

---

## Related

- [ROADMAP.md](ROADMAP.md): A24 (operationaldata metadata), S1 (signature
  study), S2 (plateaux).
- [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md): §Field factor,
  §Commissioning measurements, data issue #16, open questions #24/#25.
- [PLAN_session_records.md](PLAN_session_records.md): clocks and time zones.
- [to_duckdb/select_experiments_by_time.py](to_duckdb/select_experiments_by_time.py):
  existing selector with the 08:00 → 07:00 Paris operational day.
- [to_duckdb/demos/magnet-assembly-history.py](to_duckdb/demos/magnet-assembly-history.py):
  a magnet's assemblies (dates via `COALESCE(link, assembly)`).
- `crud.view_experiments` / `view_operationaldata` / `view_overview_records`:
  existing filters by assembly, magnet, part and from/to.
