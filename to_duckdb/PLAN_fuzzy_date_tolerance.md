# Plan — days-based date tolerance for fuzzy-match compatibility check

Status: pending approval (not yet implemented)

## Goal

Loosen `_acronym_date_compatible()` (added to `to_duckdb/demos/users_table_demo.py`
to date-check fuzzy acronym matches — see git history) by a configurable
**days** margin, so a session that starts/ends a few days outside a
proposal's recorded `Experiment Start/End Date` window still counts as
compatible, instead of requiring exact calendar-day overlap.

## Files affected

- `to_duckdb/demos/users_table_demo.py` — edit only.

## Approach

1. Add `from datetime import timedelta` to the existing `datetime` import.
2. Add `tolerance_days: int = 3` to `_acronym_date_compatible()`. Change the
   overlap test from:

   ```python
   start_date <= e and end_date >= s
   ```

   to:

   ```python
   (start_date - timedelta(days=tolerance_days)) <= e and (end_date + timedelta(days=tolerance_days)) >= s
   ```

   — padding the proposal's window on both the start and stop side before
   checking overlap against the session's `[s, e]` range. `.date()`-level
   comparison stays as-is (day-granularity timedelta arithmetic on `date`
   objects works correctly, unlike sub-day units). The `Experiment
   Year`-only fallback branch (no exact dates) is left untouched.
3. Thread `tolerance_days` through `find_proposal_rows()` → `build_users()`
   → `build_users_from_csv()`.
4. Add a `--date-tolerance-days` CLI flag (default `3`) in `main()`, passed
   through to `build_users_from_csv()`.

## Scope assumptions

- Only affects the fuzzy-candidate compatibility check — not
  `resolve_proposal_row()`'s exact-session-in-range check (used to pick
  among an *already-matched* acronym's own multiple rows) and not
  `load_proposals()`'s `--from` cutoff filter.
- One shared margin applied to both the start and stop side (not
  independently configurable start-tolerance vs. stop-tolerance).
- Default of `3` days is a starting guess — easy to change.

## Verification

1. Scratch-copy `to_duckdb/test-magnetdb.duckdb`; run with
   `--date-tolerance-days 0` and confirm it exactly reproduces the current
   shipped baseline (`580 exact, 131 fuzzy, 640 unmatched`).
2. Run with the default (`3`) and diff — spot-check 2-3 newly-accepted
   fuzzy candidates against the raw CSVs (`Data/EXPERIENCES_LOG.csv`,
   `Data/proposals.csv`) to confirm the day gap is plausible, not masking a
   real mismatch.
3. `ruff check to_duckdb/demos/users_table_demo.py` stays at the same 5
   pre-existing findings (shebang not executable, two unused `noqa`
   directives, one `DTZ007`, one `PLR1730`) — none introduced by this
   change.
