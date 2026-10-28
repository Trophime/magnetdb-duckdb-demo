# Plan 1: test the MagnetDB dashboard on the dev machine

Status (2026-10-27): **plan 1 in progress on the laptop**, now on a wired
LNCMI socket without the VPN — steps 0–5, 7, 10, 11 passed; steps 6, 8, 9
left (see [Results](#results-2026-10-27)). The VPN explained the first
read timeouts, but the File viewer hang itself was a deadlock in rclone
1.60, fixed with rclone 1.75.2 (see
[File viewer hang](#file-viewer-hang-rclone-160)); **plan 1b** (`calcul22`)
is not needed.

This is the first of three plans:

1. **Local** (this plan): dashboard only, Docker, read-only snapshot,
   `127.0.0.1:8050`, plus a short test from another machine through Traefik.
2. **Server**: the same dashboard on an LNCMI server, rootless Podman +
   Quadlet, Traefik with a DNS name, an institutional certificate and login.
3. **Writer**: a side container running `to_duckdb` with magnettools to
   modify the database.

Plans 2 and 3 are draft notes in
[PLAN_dashboard_server_deployment.md](PLAN_dashboard_server_deployment.md)
(not approved).

## Goal

The dashboard runs on the dev machine in a container on `127.0.0.1:8050`,
built from the current tree with the translations compiled in, reading a
checkpointed snapshot of the database through a read-only mount; every page
works, nothing is written on the host, and another LNCMI user can load it
through Traefik (HTTPS + login) on `:8443`.

## Decisions (2026-10-27)

| Topic | Decision |
|---|---|
| Role of the dashboard | Read-only: it computes stats, nothing else. Every table change goes through `to_duckdb`, run elsewhere with magnettools (plan 3) |
| Runtime | **Docker** on the dev machine: Podman is not installed and the AD account has no `/etc/subuid` entry. Rootless Podman + Quadlet are tested on the server (plan 2) |
| Image | `magnetdb-dashboard:local`, built from the working tree, not pushed |
| Database | Snapshot of `to_duckdb/magnetdb-2026-10-08.duckdb`, checkpointed copy in `~/magnetdb-local/duckdb/` |
| Hoop stress | None in this test (0 `hoop_stress_processed` rows, no `hoop_parquet/`); `run_docker.sh` warns |
| Access from another machine | **Option B**: Traefik container on `:8443` in front of the dashboard, `basicAuth`, Traefik's built-in self-signed certificate (the tester accepts a warning once; it comes back after each Traefik restart). Dashboard itself stays on `127.0.0.1:8050` |
| Traefik config | File provider only, no `docker.sock`, API/dashboard off. Plan 2 reuses the same files |

## Findings (2026-10-27)

| Item | Value |
|---|---|
| Image | `python:3.13-slim-trixie` + uv, no magnettools (`33099cc`, `1e58ba9`); runs as `1000:100`, `HOME=/home/app` (mode 1777); local `magnetdb-dashboard:dev` is 1.5 GB |
| Runtime data read | `MAGNETDB_DB_PATH`; `<db dir>/hoop_parquet/parts/*.parquet` (`magnetdb_analysis.py:779`); `bdd.csv` via `MAGNETDB_SUPERVISION_BDD_CSV`; records via `MAGNETDB_RECORDS_DIR`; `~/.config/magnetdb/{style,group_order}.json` as a read-only site override |
| UI config | Style in browser localStorage (`998158d`), selected database in a cookie (`99065fe`): the dashboard writes nothing on the host |
| Database dropdown | `glob("*.duckdb")` in `MAGNETDB_DB_DIR`, top level only |
| Translations | Only `.po` files in `src/locales/`; `*.mo` gitignored (`.gitignore:55`), `i18n.py` uses `fallback=True`: the image is English-only with no error (P3). `Babel` is a dependency, so `pybabel` is in the image venv |
| Build context | `.dockerignore` sends `Data/` (157 MB) and `Data-csv.tgz` (13 MB); `**/.envrc` already excluded |
| Submodules | HEAD points to `python_magnetrun` `b3344bd` (`spike/tdms-polars-benchmark`) and `python_magnetsetup` `cf9718a` (`msite_to_assembly`, committed on another machine with `16fb501`). Both are on GitHub since 2026-10-27 and the checkouts are synced (step 0) |
| Database | `to_duckdb/magnetdb-2026-10-08.duckdb` still modified today (10:47); a copy of the same size exists in `~/duckdb/` |
| Network | Laptop first on eduroam `147.173.90.37/24` + VPN `tun0`, since 2026-10-27 afternoon on a wired LNCMI socket `147.173.83.78/22` (DHCP), VPN off; no sshd, so no SSH tunnel; ufw active but Docker-published ports bypass it |

### `scripts/run_docker.sh` review

| # | Problem | Fix in this plan |
|---|---|---|
| R1 | Container uid vs host uid | Dropped: all mounts read-only, `HOME` world-writable |
| R2 | No check that `hoop_parquet/` sits next to the database | Warn when missing |
| R3 | `--rm`, no `--name` | `--name magnetdb-dashboard` |
| R4 | `-p 8050:8050` listens on every interface | `-p 127.0.0.1:8050:8050` |
| R5 | Database and records mounted read-write | Both `:ro` |
| R6 | Checks `SUPERVISION_DATA_DIR`, not `bdd.csv` | Test the file |
| R7 | Default image `:dev` | Done (`1f2c019`): image as first argument |
| R8 | A missing `~/.config/magnetdb` gets created root-owned by Docker | Mount it only if it exists |
| R9 | Hard requirement on `rclone-mount.service` | Skip rclone when `$RECORDS_MOUNT` is already a mountpoint |
| R10 | `SUPERVISION_DATA_DIR` default | Kept (repo `Data/`, fine locally) |

## Files affected

| Path | Action |
|---|---|
| `apps/dashboards/magnetdb/Dockerfile` | edit: `pybabel compile -d locales -D magnetdb` after copying `src/` |
| `.dockerignore` | edit: exclude `Data/`, `*.tgz`, `*.duckdb*` |
| `scripts/run_docker.sh` | edit: R2–R6, R8, R9; `--network magnetdb` (created if missing) |
| `scripts/traefik/traefik.yml` | create: entry point `websecure` on `:8443`, file provider, API/dashboard off, access log |
| `scripts/traefik/dynamic.yml` | create: router `PathPrefix(`/`)` (no DNS name yet), `basicAuth` middleware reading `/etc/traefik/htpasswd`, service `http://magnetdb-dashboard:8050` |
| `scripts/run_traefik.sh` | create: creates the `magnetdb` network if missing; runs `traefik:v3.6.7` as `magnetdb-traefik`, `-p 8443:8443`, config and htpasswd `:ro`; fails if `scripts/traefik/htpasswd` is missing |
| `.gitignore` | edit: ignore `scripts/traefik/htpasswd` |
| `scripts/README.md` | edit: new `run_docker.sh` behaviour; access from another machine (htpasswd, start, stop) |

No commit or push: the maintainer commits.

## Approach

0. **Done 2026-10-27** (maintainer): `git submodule update python_magnetrun python_magnetsetup`
   → verified: `git submodule status` shows no `+`; `python_magnetrun` at `b3344bd`, `python_magnetsetup` at `cf9718a`
1. Baseline: dashboard tests on the unchanged code
   → verify: `.venv/bin/python -m pytest apps/dashboards/magnetdb/tests` passes (tests reading the records need the VPN)
2. Snapshot: copy `to_duckdb/magnetdb-2026-10-08.duckdb` (and its `.wal`, if any) to `~/magnetdb-local/duckdb/`, `CHECKPOINT` **the copy**
   → verify: no `.wal` there; a read-only open gives non-zero counts for `experiments`, `magnets`, `assemblies`
3. Dockerfile: compile the translations
   → verify: `docker build -f apps/dashboards/magnetdb/Dockerfile -t magnetdb-dashboard:local .` succeeds; `/app/src/locales/fr/LC_MESSAGES/magnetdb.mo` exists in the image
4. `.dockerignore`
   → verify: "transferring context" in the build log under about 30 MB
5. `run_docker.sh`
   → verify: `bash -n` passes; `DUCKDB_DIR=~/magnetdb-local/duckdb DUCKDB_NAME=magnetdb-2026-10-08.duckdb scripts/run_docker.sh magnetdb-dashboard:local` starts; `ss -ltn` shows only `127.0.0.1:8050`; `docker inspect` shows the database and records mounts with `RW=false`; the `hoop_parquet` warning is printed. If DuckDB cannot open the database on the `:ro` mount, stop and re-plan
6. Local smoke test
   → verify (Claude): `curl -sf http://127.0.0.1:8050/` returns 200; `docker logs magnetdb-dashboard` shows no traceback
   → verify (maintainer, browser): assembly/magnet/part/housing stats, Overview records, File viewer (one pupitre, one TDMS, one archive file), Defaults & Spikes, Research area, About, switch to French, database dropdown, a style change through the gear icon that survives a reload while `~/.config/magnetdb` stays unchanged
7. Traefik: create a test account in `scripts/traefik/htpasswd` (`htpasswd -nB`, or `openssl passwd -apr1` if `apache2-utils` is missing), run `scripts/run_traefik.sh`
   → verify: `curl -k -o /dev/null -w '%{http_code}' https://<laptop IP>:8443/` returns `401`, and `200` with `-u user:pass`; `curl http://<laptop IP>:8050/` is refused; `docker logs magnetdb-traefik` shows no errors
8. External test: the other user opens `https://<laptop's wired IP>:8443/` (2026-10-27: `147.173.83.78`), accepts the warning, logs in, loads a few pages including a File viewer plot and the language switch
   → verify: pages load on their side; the Traefik access log shows their IP; nothing new in `docker logs magnetdb-dashboard`. If it fails, first `nc -z <IP> 8443` from their machine (Wi-Fi/VLAN firewall)
9. Shut down: `docker stop magnetdb-traefik`
   → verify: `ss -ltn` no longer shows `:8443`
10. Tests after the changes
    → verify: same result as step 1
11. `scripts/README.md`
    → verify: variable table and options match the scripts

## Assumptions

- The tester is an LNCMI colleague on the internal network; someone outside LNCMI cannot reach the laptop (plan 2).
- The laptop is on a wired LNCMI socket with the VPN off; its DHCP address is given to the tester on the day of the test (`calcul24` is probably not in DNS).
- DuckDB's `read_only=True` works on a `:ro` mount (checked in step 5).
- The image uses python_magnetrun `b3344bd`, the commit HEAD records.

## Results (2026-10-27)

| Step | Result |
|---|---|
| 0 | Passed (maintainer): submodules at `b3344bd` / `cf9718a` |
| 1 | Passed: 145 tests, run from `apps/dashboards/magnetdb` with `--ignore=tests/mrun_test.py` (that script calls `load_mrun` at import, so collection hangs on the rclone mount) |
| 2 | Passed: `~/magnetdb-local/duckdb/magnetdb-2026-10-08.duckdb`, no `.wal`, 6483 experiments, 23 magnets, 58 assemblies, 0 `hoop_stress_processed` |
| 3 | Passed: `magnetdb-dashboard:local` built, `.mo` compiled for de, en, fr, nl. Rebuilt the same way after a Docker image cleanup (context then 12 MB) |
| 4 | Passed: build context 472 kB |
| 5 | Passed: only `127.0.0.1:8050`; all mounts `RW=false`; DuckDB `read_only=True` works on the `:ro` mount, writes refused |
| 6 | Partial: `/` and `/_dash-layout` 200, no traceback. Over the VPN the File viewer failed (`FileNotFoundError` for pupitre files, then hanging reads — see below); on the wired network `load_mrun("2026.10.07 - 19:07:03.txt", "M10")` works in the container (3 s), but switching to a second file still hung (rclone 1.60, see below). After the rclone fix, image rebuilt with the `file_viewer` zoom-sync fix (17:40) and restarted: `/` 200, mounts `RW=false`, no traceback. Maintainer's browser checks left |
| 7 | Passed (eduroam, then again wired on `147.173.83.78`, and again after the rebuild): `401` without login / wrong password, `200` with the account; `:8050` refused from the LAN; `CN=TRAEFIK DEFAULT CERT`; 2 expected warnings (no domain in `PathPrefix`, encoded characters) |
| 8, 9 | Not done |
| 10 | Passed: 145 tests |
| 11 | Done: `run_docker.sh` behaviour, `run_traefik.sh` section |

### Records over the VPN

- The laptop is on **eduroam** (`147.173.90.37`, DHCP) with the **LNCMI VPN**; every route, including the one to `147.173.88.250`, goes through `tun0` (`147.173.91.150`).
- rclone logged `Discarding closed SSH connection: … i/o timeout` (12:41, 12:58); reads then hang in `request_wait_answer` (processes in `D` state, unkillable, `docker stop` fails).
- A stop of `rclone-mount.service` while a container bind-mounts the FUSE mount fails to unmount (`Device or resource busy`); rclone then loops on `directory already mounted` and the mount reports `Transport endpoint is not connected`. Recovery: stop rclone (fails pending requests), stop the container, `fusermount3 -uz`, start rclone, then the container.
- After a clean restart, listing `srv-data-install/M10` works but reading a 616 kB file still times out on the host: the link does not deliver file contents.
- The eduroam address is probably not reachable from the wired LNCMI network either, so step 8 would fail from the laptop.
- **Confirmed**: with the laptop on a wired LNCMI socket (`147.173.83.78/22`, VPN off, route to `147.173.88.250` over Ethernet), full reads (`cat`) take 0.04–0.18 s (616 kB and 1.3 MB pupitre files, 7.3 MB TDMS archive). The VPN link was the cause of these timeouts; records access needs a wired LNCMI connection (or the server of plan 2). It was not the cause of the File viewer hang below.

### File viewer hang: rclone 1.60

- On the wired network, the File viewer still hung on the second pupitre file, with every image (`:local`, `:dev`). All gunicorn threads waited in `D` state on the file; a plain `head` on the host hung too.
- Cause: the distro rclone **1.60.1** (Ubuntu 26.04 and Debian trixie) deadlocks with `--vfs-cache-mode full` when a file is closed and reopened while its cache download is still running. `python_magnetrun` does exactly that (encoding probe, `_parse_header`, then `pl.read_csv(path)`). rclone's `-vv` log stops at `openPending:`, with no error.
- Reproduced outside the dashboard with a test mount: `cat`, two parallel readers and a plain `mmap` read work; header read + close + `pl.read_csv` hangs on the first uncached file with 1.60 (twice), and works on 3/3 files with **1.75.2**.
- Fix on the laptop: official `rclone-v1.75.2-linux-amd64.deb` (`sudo apt install`, checksum checked), and `ExecStop=/bin/fusermount3 -uz` in `rclone-mount.service`, so a busy mount no longer survives a restart. `calcul22` runs the same 1.60 and needs the same fix before plan 1b or plan 2 reuse it.
- Unrelated fix found on the way: `sync_zoom_home` in `file_viewer.py` ignored double-click resets (and wiped other graphs' range on other events); fixed, with `tests/file_viewer_sync_zoom_test.py`.

## Plan 1b: same test on `calcul22`, wired, without the VPN

Status: **not needed** (2026-10-27): the laptop on a wired socket gave the
same conditions. Kept as an alternative; never approved, never run.

### Goal

The plan-1 dashboard and Traefik setup runs on `calcul22`
(`calcul22.LNCMIG.LOCAL`, `147.173.82.62`, wired, no VPN), where the File
viewer plots records files and an LNCMI colleague can load
`https://calcul22.LNCMIG.LOCAL:8443/`.

### Decisions

| Topic | Decision |
|---|---|
| Machine | `calcul22` (its own home; the laptop's home is local) |
| Code | **(a)**: the maintainer commits and pushes the plan-1 changes; new `git clone --recursive -b msite_to_assembly` in `~/magnetdb-test/` on `calcul22`, image built there. Also checks that a clone from GitHub works (plan 2, P1). Reusing an existing checkout on `calcul22` instead: open, decided after step 0 |
| Records credential | The maintainer's own `srv-data-install` remote, for this test only (the server gets its own read-only one, plan 2) |
| Commands on `calcul22` | Run by Claude over `ssh calcul22` from the laptop — **open, needs the maintainer's OK** |

### Files affected

| Path | Action |
|---|---|
| `PLAN_dashboard_local_deployment.md` | edit: results of each step |

No repo file changes. On `calcul22` (maintainer's account): `~/magnetdb-test/`
(clone), image `magnetdb-dashboard:local`, `~/magnetdb-local/duckdb/`,
`~/magnetdb-test/Data/bdd.csv`, the `srv-data-install` rclone remote,
`~/.config/systemd/user/rclone-mount.service`,
`~/magnetdb-test/scripts/traefik/htpasswd`.

Prerequisite (maintainer): commit and push `apps/dashboards/magnetdb/Dockerfile`,
`.dockerignore`, `.gitignore`, `scripts/run_docker.sh`, `scripts/README.md`,
`scripts/run_traefik.sh`, `scripts/traefik/traefik.yml`,
`scripts/traefik/dynamic.yml`. `scripts/traefik/htpasswd` stays out of git.

### Approach

0. Inventory of `calcul22` (read-only, `ssh calcul22`): `hostname -I`, `docker version`, `groups` (`docker`), `rclone version`, `grep user_allow_other /etc/fuse.conf`, `ip route get 147.173.88.250`, ports 8050/8443 free, `df -h ~`, existing `~/github/magnetdb-duckdb-demo`, `~/.config/rclone/rclone.conf`
   → verify: all present; route to `147.173.88.250` on a wired interface. Missing Docker or `user_allow_other`: stop and re-plan
1. VPN hypothesis: on `calcul22`, time an `sftp` `get "/mnt/pve/DATA/srv-data-install/M10/2026.10.07 - 19:07:03.txt"`
   → verify: done in a few seconds. If it stalls too, the VPN is not the cause: stop and re-plan
2. Stop Traefik on the laptop: `docker stop magnetdb-traefik`
   → verify: no `:8443` in `ss -ltn`
3. Clone and build on `calcul22`: `git clone --recursive -b msite_to_assembly https://github.com/Trophime/magnetdb-duckdb-demo.git ~/magnetdb-test`, `docker build -f apps/dashboards/magnetdb/Dockerfile -t magnetdb-dashboard:local .`
   → verify: `git submodule status` shows no `+`/`-`, `python_magnetrun` at `b3344bd`; build succeeds; 4 `.mo` files in the image
4. Data: rsync `~/magnetdb-local/duckdb/` (120 MB) and `Data/bdd.csv` (157 MB) to `calcul22`
   → verify: same `sha256sum` on both sides; no `.wal`
5. rclone on `calcul22`: `srv-data-install` remote and the same `rclone-mount.service` user unit, then start it
   → verify: `mountpoint ~/LNCMIG-Data/records`; `wc -c` of the test file in a few seconds
6. Copy `scripts/traefik/htpasswd` (mode 600)
   → verify: `run_traefik.sh` no longer reports it missing
7. Start, detached (`setsid nohup … > log`): `DUCKDB_DIR=~/magnetdb-local/duckdb DUCKDB_NAME=magnetdb-2026-10-08.duckdb SUPERVISION_DATA_DIR=~/magnetdb-test/Data scripts/run_docker.sh magnetdb-dashboard:local`, then `scripts/run_traefik.sh`
   → verify: on `calcul22`, `curl http://127.0.0.1:8050/` 200; from the laptop, `https://calcul22.LNCMIG.LOCAL:8443/` `401`, `200` with the account; `http://calcul22.LNCMIG.LOCAL:8050/` refused
8. Smoke test (maintainer's browser, `https://calcul22.LNCMIG.LOCAL:8443/`): checklist of plan 1 step 6, plus one pupitre, one TDMS and one archive file in the File viewer
   → verify: plots shown; no traceback in `docker logs magnetdb-dashboard` on `calcul22`
9. External test: the colleague opens `https://calcul22.LNCMIG.LOCAL:8443/` with the `tester` account
   → verify: pages and one File viewer plot load on their side; their IP in Traefik's access log
10. Shut down on `calcul22`: `docker stop magnetdb-traefik magnetdb-dashboard`, `systemctl --user stop rclone-mount.service`
    → verify: no `:8050`/`:8443` in `ss -ltn`; `mount | grep LNCMIG` empty
11. Record results in this file
    → verify: every step has a pass/fail note

### Assumptions

- `calcul22` is on the wired LNCMI network and reaches `147.173.88.250` without the VPN (checked in steps 0–1).
- Nothing between the wired VLANs blocks `calcul22:8443` (checked in steps 7 and 9).
- The SSH session from the laptop to `calcul22` goes through the VPN; that is fine for commands, the records traffic stays on `calcul22`.
- Alternative not chosen: the laptop on a wired LNCMI socket with the VPN off.
