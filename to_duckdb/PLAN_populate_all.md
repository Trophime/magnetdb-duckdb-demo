# Plan — `populate all` composite subcommand

Status: not implemented — design sketch for future work

## Goal

One `populate all` subcommand that runs `experiments` → `overview-records`
→ `overview-records-infer` (which includes the pupitre-dedup merge sweep)
sequentially in a single process invocation, so a scheduler only needs to
trigger one command per tick instead of coordinating multiple commands (or
timers) in the right order. See `PLAN_scheduled_populate.md` for the
systemd timer that will call this.

## Context

Today the pipeline for ingesting new overview_records is two manual steps:
`populate overview-records` (or `overview-records-from-json`), then
`populate overview-records-infer` to resolve `site_name`/`t0`/`teb`/`bp`
for any row still missing them and run the pupitre-dedup merge sweep
(`merge_duplicate_pupitre_records`, `to_duckdb/crud.py:2282`) — which must
see rows with `housing`/`site_name`/`t0` already resolved, table-wide, so
it cannot run at insert time (see that function's docstring).
`populate experiments` (`to_duckdb/magnetdb.py:748`) is a separate,
unrelated scan of the same records tree for pupitre TXT files.

For unattended/scheduled runs there's no user around to remember the
second step, so the sequencing needs to live in one command.

## Design

- New subparser `pop_sub.add_parser("all", ...)` in `to_duckdb/magnetdb.py`
  (alongside the other `populate` subparsers, ~line 1529), taking the
  union of flags already defined for the three commands it wraps:
  `_db_arg`, `_sites_arg` (`--site`/`--all`), `--records-base`,
  `--srv-subdir`, `--pbsurv`, `--db-tz`, `--reprocess`,
  `--max-gap-seconds`, `--dry-run`.
- New handler `cmd_populate_all(args)` in `to_duckdb/magnetdb.py` (near
  the other populate handlers, after `cmd_populate_overview_records_infer`
  ~line 936) that calls, in order:
  1. `cmd_populate_experiments(args)`
  2. `cmd_populate_overview_records(args)`
  3. `cmd_populate_overview_records_infer(args)`

  All three already use matching `args` attribute names (`db`, `site`,
  `all`, `records_base`, `srv_subdir`, `pbsurv`, `db_tz`, `reprocess`,
  `dry_run`), so one parsed `args` namespace can be passed to all three
  calls unchanged — no translation layer needed.
- New dispatch entry `("populate", "all"): cmd_populate_all` in the
  command-dispatch dict (`to_duckdb/magnetdb.py:1092`).
- Out of scope: `--settle-seconds` — tracked separately in
  `PLAN_scheduled_populate.md`, not yet implemented for any populate
  command.

## Fail-fast semantics

`populate all` is fail-fast at the granularity that already exists today:

- Structural errors (missing `--db`, bad `--db-tz`) already call
  `sys.exit(1)` inside each `cmd_populate_*` function, which — called
  in-process, in sequence — already aborts any later step for free. No
  new code needed for this case.
- Per-file errors inside the scan/insert loops (e.g. one unreadable TDMS
  file) are currently caught and printed as `[ERROR] ...` without raising
  or exiting non-zero. `populate all` inherits this as-is: those stay
  warnings in the log, and do not by themselves fail the run or trigger
  the `OnFailure=` email in `PLAN_scheduled_populate.md`.

This matches current behavior with no code changes to the per-file error
handling — flagged here because it directly determines how often the
admin gets emailed under the scheduled setup; open to revisiting if
per-file errors should also be promoted to a hard failure.

## Verification

- `populate all --dry-run --db <dev.duckdb> --all` → prints matches from
  all three phases (experiments scan, overview-records scan,
  overview-records-infer candidates) in order, writes nothing.
- `populate all --db <scratch-copy.duckdb> --site <site>` against a
  scratch copy of the dev DB → confirms rows land in `experiments`,
  `overview_records`, and that `overview_records.site_name`/`merged_into`
  are populated as expected afterward.
- `populate all --db /nonexistent.duckdb; echo $?` → non-zero exit,
  confirms structural failures still abort the whole chain.

## Open questions

- Should per-file errors (see "Fail-fast semantics") be promoted to a
  hard failure for the scheduled/email-notification use case, or left as
  log-only warnings as they are today?
- Should `--reprocess` apply uniformly across all three phases (today's
  behavior if `args.reprocess` is reused as-is), or does any phase need
  independent control?
