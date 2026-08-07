# Plan — scheduled run of the populate commands (systemd timer + settle-time check)

Status: not implemented — design sketch for future work

## Goal

Run `magnetdb.py populate overview-records` (and friends) unattended on a
regular interval against the live TDMS acquisition directory, without ever
ingesting a file that the acquisition system is still in the middle of
writing.

## Context

`find_and_register_tdms` (`to_duckdb/populate.py:306`) scans a live
acquisition directory tree and `scan_tdms_subdir` (`to_duckdb/populate.py:284`)
matches files purely by parsing a timestamp out of the filename — there is
currently no check on whether a matched file has finished being written.
Running this on a schedule against a directory that's actively being
populated by the acquisition system risks reading a partial file.

Related open TODO: `to_duckdb/TODOs.md` — "add a scheduler to run the above
scripts on a regular basis (cron job or similar)".

## Scheduler: systemd timer, not cron

Recommendation: **systemd timer**. Reasons specific to this job:

- `Persistent=true` — if the machine is down or the service fails during a
  run, the next boot/timer tick catches up automatically. Cron just misses
  the window silently.
- Idempotency plays well with retries: `populate overview-records` already
  skips filenames it has already ingested (see
  `PLAN_overview_records_pupitre_dedup.md`'s idempotency notes), so a
  systemd `OnFailure=` unit can retry safely without double-inserting.
- `journalctl -u magnetdb-populate` gives structured logs/history for free,
  instead of a cron mail spool or hand-rolled log file.

### Unit sketch

```ini
# /etc/systemd/system/magnetdb-populate.service
[Unit]
Description=Populate magnetdb overview-records from live TDMS drop

[Service]
Type=oneshot
WorkingDirectory=/path/to/2026-m1-hifimagnet
ExecStart=/path/to/2026-m1-hifimagnet/to_duckdb/venv-systempackages/bin/python3 \
    to_duckdb/magnetdb.py populate overview-records --all \
    --db /path/to/magnetdb.duckdb --settle-seconds 120
```

```ini
# /etc/systemd/system/magnetdb-populate.timer
[Unit]
Description=Run magnetdb-populate every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=true
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
```

`populate overview-records-infer` (the merge sweep) would get its own
service/timer pair, offset a few minutes after ingestion so it always sees
a stable batch (open question below — see "offset" bullet).

## Settle-time check: where it goes

`scan_tdms_subdir` is the right spot — it's the only place that already
touches each candidate file individually (`fpath.glob("*.tdms")`), before
the timestamp-window filter:

```python
def scan_tdms_subdir(subdir, file_type, t_start, t_end, settle_seconds=0):
    ...
    for fpath in sorted(subdir.glob("*.tdms")):
        if settle_seconds and (time.time() - fpath.stat().st_mtime) < settle_seconds:
            continue  # still being written; picked up on next timer tick
        ts = parse_tdms_file_ts(fpath.name, file_type)
        ...
```

Threading needed: `settle_seconds` param through `scan_tdms_subdir` →
`find_and_register_tdms` → `cmd_populate_overview_records`'s argparse
(new `--settle-seconds` flag).

Key point: **no new state needed.** A file that fails the settle check is
simply skipped this run — since it hasn't been inserted yet, it stays a
candidate and gets picked up on the next timer tick once its mtime ages
past the threshold. This relies on the existing idempotent
skip-if-filename-exists behavior in the insert functions.

## Open questions

- Default value for `--settle-seconds` — needs to be long enough to
  outlast the acquisition system's write/flush pattern for a TDMS file;
  not yet measured.
- Should `populate experiments` / `populate operationaldata` (which also
  scan for TDMS files via `find_and_register_tdms`) get the same
  `--settle-seconds` flag, or is the risk only relevant to
  `overview-records`?
- Exact offset between the ingestion timer and the
  `overview-records-infer` merge-sweep timer, so the sweep never races a
  still-running ingestion pass.
- Where the timer/service units should live in this repo (e.g. a
  `to_duckdb/systemd/` directory checked into git) vs. deployed by hand on
  the target machine.
