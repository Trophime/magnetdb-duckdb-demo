# Plan: make magnettools optional (to_duckdb, dashboard, devcontainer)

Status (2026-10-26): steps 0–5 done; step 6 (devcontainer rebuild in VS Code) left to the user.

First slice of [Phase 2 of the magnettools release pipeline](PLAN_magnettools_release_pipeline.md#phase-2--magnetdb-duckdb-demo-this-repo):
the root `pyproject.toml`, `uv.lock`, `bump-magnettools.sh` and CI stay there.

## Goal

to_duckdb works without magnettools except for its hoop-stress commands; the
dashboard image has no magnettools; the devcontainer is `debian:trixie` with
magnettools from the local `magnettools-db:trixie-1.2.6` image; host and
container each have their own venvs, created by `setup-uv.sh`.

## Findings

- **Dashboard**: nothing in `apps/dashboards/magnetdb/src` imports magnettools,
  nor does python_magnetrun at import time. The only ties are the Docker base
  image (`trophime/magnettools:trixie`), the pyproject comment block and
  README l.27.
- **to_duckdb**: only `stress_map.py` imports magnettools at module level
  (l.44–45), plus `python_magnetsetup.ana` (l.56), which imports it in turn.
  `magnetdb.py` and `compute_hoop_stats.py` import `stress_map` lazily, inside
  the hoop-stress handlers only.
- **Tests without magnettools** (repo `.venv`): `test_stress_map.py` fails at
  collection; 10 tests of `test_compute_hoop_stats.py` error with
  `ModuleNotFoundError` although they monkeypatch the magnettools functions;
  `test_compute_hoop_stress_history_geometry_prep_failure_aborts` fails
  (assertion, to confirm whether related). Only 3 tests
  (`_section_index_at_z`) really build magnettools objects.
- **magnettools-db** (`../my-magnettools/docker/`): ships
  `/opt/magnettools/{debs,src,wheels,MANIFEST}`; install = local apt repo +
  `libmagnettools1` + the matching `cp3XX` wheel. Wheels are not
  self-contained (need `libmagnettools1`), Debian trixie only; never mix the
  wheel with `python3-magnettools` in one venv.
- **Python 3.15 is not usable yet** with the current pins: the latest
  `duckdb<2` (1.5.6) and `pyarrow<25` (24.0.0) have no cp315 wheels. Moving
  to 3.15 = bump to duckdb 2 / pyarrow 26, a separate decision.
- **Venvs cannot be shared** between host and devcontainer: the workspace is
  bind-mounted, and venvs record absolute paths (script shebangs, editable
  installs, base interpreter). Host: Ubuntu 26.04, Python 3.14.4, no uv, no
  magnettools.

## Decisions

- Devcontainer base **A**: `debian:trixie` + magnettools from
  `magnettools-db:trixie-1.2.6` (local image for now; `ghcr.io/feelpp/...`
  later). Default venv on Debian's `/usr/bin/python3` (3.13) + cp313 wheel
  (`VENV_PYTHON=/usr/bin/python3` in `containerEnv`; option B of step 4:
  under 3.14, `ruptures` 1.1.10 has no cp314 wheel and needs a C compiler);
  `.venv-systempackage` on the same Python + `python3-magnettools`. The host
  keeps 3.14 (`VENV_PYTHON` unset), where gcc is available.
- Dashboard image: `python:3.13-slim-trixie` + uv, no magnettools.
- `setup-uv.sh` is the default setup script from now on.
- Separate venvs (option 1): container venvs live outside the workspace, in
  `$VENV_DIR=/home/myuser/.venvs/magnetdb` (and `…-systempackage`); host venvs
  stay in the repo (`.venv`, `.venv-systempackage`). No Docker volume.
- Default venvs are created **without** `--system-site-packages`;
  `.venv-systempackage` is opt-in.
- uv on the host: Astral's installer, pinned to the same version as the
  images (0.13.5), per-user in `~/.local/bin`.

## Files affected

| # | File | Change |
|---|---|---|
| 1 | `to_duckdb/stress_map.py` | edit: guard the magnettools / `python_magnetsetup.ana` imports; `load_magnettools()` raises a clear `ImportError` when missing |
| 2 | `to_duckdb/tests/test_stress_map.py` | edit: optional `mt` import; `skipif` on the 3 `_section_index_at_z` tests |
| 3 | `to_duckdb/pyproject.toml` | edit comments: magnettools optional (hoop-stress only); install via `setup-uv.sh` / `magnettools-db` |
| 4 | `apps/dashboards/magnetdb/pyproject.toml` | edit: remove the magnettools comment block |
| 5 | `apps/dashboards/magnetdb/Dockerfile` | edit: `BASE_IMAGE=python:3.13-slim-trixie`; `COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/`; `uv venv` + `uv pip install` |
| 6 | `apps/dashboards/magnetdb/README.md` | edit: drop the magnettools pointer (l.27); `BASE_IMAGE` table and example (l.137, l.144) → `python:3.13-slim-trixie` |
| 7 | `.devcontainer/Dockerfile` | edit: `ARG MAGNETTOOLS_IMAGE=magnettools-db:trixie-1.2.6` + `FROM ${MAGNETTOOLS_IMAGE} AS magnettools` (`COPY --from` does not expand ARGs); `COPY --from=magnettools /opt/magnettools/`; local apt repo → `libmagnettools1 python3-magnettools python3-venv`; uv 0.13.5; keep user/sudo/texlive/git-lfs steps |
| 8 | `.devcontainer/devcontainer.json` | edit: `containerEnv.VENV_DIR=/home/myuser/.venvs/magnetdb`; `python.defaultInterpreterPath` → it; `postCreateCommand` / `postStartCommand` call `setup-uv.sh` (start test on `$VENV_DIR`) |
| 9 | `.devcontainer/local/devcontainer.json` | edit: same as #8; `BASE_IMAGE` arg → `debian:trixie` |
| 10 | `.devcontainer/setup-uv.sh` | edit: see below |
| 11 | `.devcontainer/motd` | edit: new base image; which venv to use in container vs host |
| 12 | `.gitignore` | edit: add `.venv-systempackage` |
| — | host `.venv` | **delete**, rebuild with `setup-uv.sh` |

### `setup-uv.sh` behaviour

- Venv path `${VENV_DIR:-.venv}`.
- Default mode: `uv venv --python "${VENV_PYTHON:-3.14}"`, no system site-packages; if
  `/opt/magnettools/wheels` exists, install the matching
  `magnettools-*-cp<XY>-*.whl` (container only).
- `--system-site-packages`: `uv venv --python /usr/bin/python3
  --system-site-packages` at `${VENV_DIR}-systempackage`; no wheel (magnettools
  from `python3-magnettools` in the container; none on the host).
- Each mode refuses an existing venv created in the other mode.
- Installs as `setup-basic.sh` does: Jupyter/Voila tools, the 4 submodules
  editable (`python_magnetrun[signal,dash,hybrid]`),
  `./to_duckdb[test,notebook,cli]`, `./apps/dashboards/magnetdb[test]`.

## Steps

0. ✅ **Rebuild `magnettools-db:trixie-1.2.6`** from my-magnettools `b5be231`
   (`docker/`, `MAGNETTOOLS_VERSION=1.2.6-1`, `lncmi_apt_key` secret) → done
   2026-10-26: image `7c8fe776d5f2`, label `1.2.6-1`, wheels cp313/cp314/cp315;
   cp313 checked in the build (python:3.13 3.13.17 and Debian python3 3.13.5;
   cp314/cp315 stages came from cache). Previous image kept as
   `magnettools-db:trixie-1.2.6-old` (`400f408e9d6c`).
1. ✅ Baseline to_duckdb + dashboard tests with the current `.venv` → verify: the
   10 magnettools errors, the collection error, the
   `geometry_prep_failure_aborts` failure; results saved for comparison.
   → done 2026-10-26:
   - to_duckdb (`--continue-on-collection-errors`): 513 passed, 1 failed
     (`geometry_prep_failure_aborts`), 10 errors + `test_stress_map.py`
     collection error, all `ModuleNotFoundError: magnettools`.
   - dashboard, one run per file (`timeout 300`): 15 files pass (147 tests);
     `hoop_test`, `lag_test` collect no tests; `mrun_test` timed out (it is a
     script loading a TDMS file from the records mount at import, which hung).
     Step 5 compares the other files only.
   - The records mount (rclone over SFTP, via VPN) hung from 17:02 (SFTP
     `i/o timeout`), then was left dead after a busy unmount at 17:29;
     remount: `fusermount3 -uz ~/LNCMIG-Data/records` +
     `systemctl --user restart rclone-mount.service`.
2. ✅ Edit #1–#2 → verify: `import stress_map` works without magnettools; no
   `ModuleNotFoundError`; 3 skips.
   → done 2026-10-26: `import stress_map` OK, `load_magnettools()` raises a
   clear `ImportError`; to_duckdb: 535 passed, 3 skipped (the
   `_section_index_at_z` tests). `geometry_prep_failure_aborts` now passes:
   its baseline failure was caused by the missing magnettools.
3. ✅ Edit #3–#6 → verify: `docker build -f apps/dashboards/magnetdb/Dockerfile
   -t magnetdb-dashboard .` succeeds; in the image, `python -V` is 3.13,
   `import magnetdb_app` works, `import magnettools` fails.
   → done 2026-10-26: image `c1007ea584c9` (~1.5 GB): Python 3.13.17 in
   `/app/venv`, `import magnetdb_app` OK, no magnettools (module, debs,
   `/opt/magnettools`), gunicorn 26.2.0, runs as `jovyan`. The slim base has
   no git, which uv needs for python_magnetrun's
   `nptdms @ git+https://github.com/Trophime/npTDMS.git`: `git git-lfs` are
   installed with apt in the root section of the Dockerfile. README l.14
   (`setup-basic.sh`) is left for step 4.
4. ✅ Edit #7–#12 → verify: devcontainer image builds; a throwaway container run
   as the host UID (`HOME` and `VENV_DIR` under `/tmp`) runs both
   `setup-uv.sh` modes: default venv imports magnettools 1.2.6 from the venv,
   systempackage venv from `/usr/lib/python3/dist-packages`; to_duckdb tests
   pass with nothing skipped.
   → done 2026-10-26:
   - Image: uv 0.13.5, Debian python3 3.13.5 + `python3-magnettools` 1.2.6,
     cp313/314/315 wheels in `/opt/magnettools/wheels`, git 2.47.3, `myuser`.
   - Default venv: 3.13.5, `include-system-site-packages = false`, cp313
     wheel, magnettools from the venv. Systempackage venv: 3.13.5, `= true`,
     magnettools from `/usr/lib/python3/dist-packages`. Reusing a venv in the
     wrong mode is refused.
   - to_duckdb: 523 passed, 13 skipped (all `test_material_db.py`, which
     needs the sibling `hifimagnet-projects` checkout, not mounted in the test
     container); the 3 magnettools tests run and pass.
   - Also: `setup-uv.sh` made executable (git mode 100644 → 100755); README
     l.14 → `setup-uv.sh`; `VENV_PYTHON` added (option B).
   - Harness note: the test container needs `USER` set, since the host UID
     has no passwd entry and `crud.py` calls `getpass.getuser()`.
5. ✅ Host: install uv 0.13.5 (Astral installer), `rm -rf .venv`,
   `.devcontainer/setup-uv.sh` → verify: `include-system-site-packages = false`;
   to_duckdb + dashboard tests show no new failures vs step 1, 3 skips.
   → done 2026-10-26: uv 0.13.5 in `~/.local/bin` (already on `PATH` via
   `~/.profile`); new `.venv` on Ubuntu's Python 3.14.4,
   `include-system-site-packages = false`, no magnettools; `ruptures` 1.1.10
   built with the host gcc. to_duckdb: 535 passed, 3 skipped. Dashboard (16
   files, `mrun_test` excluded): same counts as step 1.
   - New DeprecationWarnings (not failures), from numpy 2.5.4 (PyPI) instead
     of Ubuntu's 2.3.5 previously seen through system site-packages:
     `python_magnetrun/magnetdata_tdms.py:273` (`pd.Timedelta` from a bare
     number, "will raise an error in the future") and nptdms
     `base_segment.py:151` (setting an array's dtype). Out of scope; to fix
     separately.
6. User rebuilds the devcontainer in VS Code → verify: interpreter is
   `/home/myuser/.venvs/magnetdb/bin/python`; host `.venv` untouched.

## Assumptions & open points

- `.venv-systempackage` is not created on the host now; run
  `setup-uv.sh --system-site-packages` when needed.
- The devcontainer uses Debian's Python 3.13 for both venvs, so no Python
  download and no compiler are needed (option B, see Decisions).
- `setup-basic.sh` is kept, no longer the default.
- Out of scope: `apps/tutorials/stress_map.py`, `to_duckdb/demos/` (really
  need magnettools); dashboard help text mentioning
  `to_duckdb/venv-systempackages/bin/python3`.
- `magnettools-db:py313-test` and `magnettools-db:trixie-1.2.6-old` can be
  removed by the user once the new image is validated.
