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
# No Restart= — failures are surfaced via OnFailure= (see "Failure
# notification" below), not retried automatically.
WorkingDirectory=/path/to/2026-m1-hifimagnet
ExecStart=/path/to/2026-m1-hifimagnet/to_duckdb/venv-systempackages/bin/python3 \
    to_duckdb/magnetdb.py populate all --all \
    --db /path/to/magnetdb.duckdb --settle-seconds 120
OnFailure=magnetdb-populate-notify.service
StandardOutput=append:/var/log/magnetdb-populate.log
StandardError=append:/var/log/magnetdb-populate.log
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

`populate all` runs `experiments` → `overview-records` →
`overview-records-infer` (which includes the pupitre-dedup merge sweep)
sequentially in one process per timer tick, so there is no separate
service/timer for the merge sweep and no offset/race to configure — see
`PLAN_populate_all.md` for the composite subcommand's own design.

## Failure notification

No automatic retry: the service has no `Restart=`, so a failed run just
fails — `populate all` is fail-fast (see `PLAN_populate_all.md`), and the
next attempt is whatever the timer's next tick brings.

On failure, `OnFailure=magnetdb-populate-notify.service` (set on the main
service, see unit sketch above) fires a second oneshot unit that emails an
admin with the run's log attached:

```ini
# /etc/systemd/system/magnetdb-populate-notify.service
[Unit]
Description=Notify admin of a failed magnetdb-populate run

[Service]
Type=oneshot
ExecStart=/path/to/2026-m1-hifimagnet/to_duckdb/systemd/notify_failure.sh
```

The main service's `StandardOutput=`/`StandardError=` append to a fixed
logfile (`/var/log/magnetdb-populate.log`, see unit sketch) rather than
relying on `journalctl` scraping, so the notify script has a concrete file
to attach — journalctl would need the failed run's `InvocationID` to scope
to just that tick, which is fiddlier than a plain append-only file.

### Mail transport — two schematic options, choice left open

*Option A: postfix "null client" relay + `mutt`*

```ini
# /etc/postfix/main.cf — relay-only, no local delivery
myhostname = magnetdb-host.lncmi.fr
relayhost = [smtp-relay.lncmi.fr]:587
inet_interfaces = loopback-only
mydestination =
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd
smtp_tls_security_level = encrypt
```

```
# /etc/postfix/sasl_passwd (root-only; `postmap` after editing)
[smtp-relay.lncmi.fr]:587  populate-notify@lncmi.fr:APP_PASSWORD
```

```bash
#!/bin/sh
# notify_failure.sh — hands off to postfix's local sendmail-compatible socket
mutt -a /var/log/magnetdb-populate.log \
     -s "populate all FAILED on $(hostname) - $(date -Iseconds)" \
     -- admin@lncmi.fr < /dev/null
```

Trade-off: a real MTA daemon to install/maintain on the host, but
`mutt`/anything expecting `/usr/sbin/sendmail` just works afterward, and
credentials live in one place (`sasl_passwd`, root-only).

*Option B: direct SMTP via Python stdlib, no local MTA*

```python
# notify_failure.py — smtplib + email, stdlib only
import os, smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg["Subject"] = f"populate all FAILED on {os.uname().nodename}"
msg["From"] = "populate-notify@lncmi.fr"
msg["To"] = "admin@lncmi.fr"
msg.set_content("populate all failed — see attached log.")
with open("/var/log/magnetdb-populate.log", "rb") as f:
    msg.add_attachment(f.read(), maintype="text", subtype="plain",
                        filename="magnetdb-populate.log")

with smtplib.SMTP("smtp-relay.lncmi.fr", 587) as s:
    s.starttls()
    s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    s.send_message(msg)
```

```ini
# notify unit — credentials via root-only EnvironmentFile, not in the script
[Service]
Type=oneshot
EnvironmentFile=/etc/magnetdb-populate/smtp.env
ExecStart=/path/to/venv/bin/python3 notify_failure.py
```

Trade-off: no MTA daemon needed, self-contained, stdlib-only — but
credential/relay management moves into this script's config instead of a
centralized postfix setup, and it's less "standard sysadmin toolbox" than
`mutt`.

**Open question:** which of A or B — depends on whether the LNCMI-G host
already runs postfix / has a smarthost relay configured, which is not yet
known.

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
- Mail transport: postfix null-client + `mutt` vs. direct SMTP via Python
  stdlib (see "Failure notification" above) — depends on whether the
  target host already runs postfix / has a smarthost relay configured.
- Admin recipient address for failure notifications — not yet decided.
- Where the timer/service units (and the notify script) should live in
  this repo (e.g. a `to_duckdb/systemd/` directory checked into git) vs.
  deployed by hand on the target machine.
