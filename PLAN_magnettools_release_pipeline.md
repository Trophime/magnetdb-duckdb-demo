# Plan: magnettools release pipeline (deb + wheel + public image)

Status: **draft — not approved**. Phase 1 targets `Trophime/magnettools`
(`../my-magnettools`); Phase 2 targets this repo.

## Problem

The magnettools Python binding (pybind11, private sources) is the weak point of
every downstream Python project:

- python_magnetdb rebuilds the wheel from the Debian source package in every
  image build — needs the LNCMI LAN/VPN and a `../apt-depot` clone.
- The wheel is not self-contained: it needs `libmagnettools1` (system apt
  package) installed at `/usr/lib/x86_64-linux-gnu/MagnetTools`.
- `uv.lock` points to `/opt/wheels` → `uv sync` only works inside that image.
- Versions drift: `debian/changelog` = 1.2.3-1, python_magnetdb pins
  `MAGNETTOOLS_VERSION=1.2.1-1`, its `uv.lock` records `magnettools-1.2.0`.
- This repo still relies on `--system-site-packages` + the `python3-magnettools`
  deb from `trophime/magnettools:trixie`.

## Goal

my-magnettools delivers, from one version in `debian/changelog`:

1. Debian packages → euler apt repo (apt users).
2. A wheel for uv → shipped inside **one public image**, built once and
   consumed by every downstream project.
3. A trigger that forces the CI of every Python project depending on magnettools.

## Decisions taken

| Topic | Decision |
|---|---|
| Method | **(b1)**: image = `debian:trixie` + `libmagnettools1` + matching wheel in `/opt/wheels` + uv (wheel not self-contained; auditwheel variant (a) under evaluation) |
| Source repo for CI | `Trophime/magnettools` |
| Registry | `ghcr.io/trophime/magnettools` (public package from a private repo) — *to confirm* |
| Version source | **`debian/changelog` only**: `DEB_VERSION` = `dpkg-parsechangelog -S Version` (e.g. `1.2.3-1`), `UPSTREAM_VERSION` = `DEB_VERSION` without the Debian revision (e.g. `1.2.3`). Every other version is derived from or checked against it |
| Tags | image `<DEB_VERSION>-trixie` (e.g. `1.2.3-1-trixie`, immutable, never rebuilt) + `trixie` (moving); git/GitHub release `v<DEB_VERSION>`; wheel version = `UPSTREAM_VERSION` (PEP 440 has no Debian revision). A packaging-only bump (`1.2.3-2`) gets its own image tag |
| Architectures | amd64 only at first |
| Runner | **no self-hosted runner for now** → release from the maintainer's machine with `scripts/release.sh` (same Dockerfile/bake a future CI would use) |
| Downstream trigger | `repository_dispatch` sent with the maintainer's own `gh` auth (no token secret needed while releasing locally) |
| Downstream reaction | **(a) test only** for now; **(b) bump PR** + GitHub App later |
| `magnettools` CLI package in image | not needed |

## Constraints found

- Build-deps `fadbad++`, `libexpokit-dev`, `libfreesteam-dev` are only in the
  LNCMI repo → building needs the LAN (hence local release).
- `apt-depot/distro_tools.sh:build_package` chains `pdebuild` + `dupload`;
  the release must upload only after the image smoke test, so `release.sh`
  calls `pdebuild` itself (apt-depot unchanged).
- `LD_LIBRARY_PATH` is **not needed** (verified 2026-10-13 in
  `trophime/magnettools:trixie` with it unset: `ldd` resolves everything,
  import + `BitterMagnet` computation OK). The Python module
  (`Python/CMakeLists.txt:94-101`) **and** every `libmagnettools1` library
  (top-level `CMakeLists.txt:129`) carry an absolute RUNPATH including
  `/usr/lib/x86_64-linux-gnu/MagnetTools`, so transitive deps
  (`libmagnetfield` → `libutils`) resolve too. The `ENV LD_LIBRARY_PATH` in
  `Dockerfile-DB` (and python_magnetdb's Dockerfiles) is redundant. Paths
  are absolute: libraries must sit where the deb installs them (always true
  for (b1)); `$ORIGIN` would make them relocatable — not needed here.
- Version check (2026-10-13, HEAD `19b5e2a` on `trixie-update`):
  `debian/changelog` = `1.2.3-1`, `CMakeLists.txt` `project(magnettools
  VERSION 1.2.3)` → **match**. History shows the past drift: changelog
  `1.2.1-1` (commit `e7b6ff4`) was released with CMake still at `1.2.0` —
  hence the published deb `1.2.1-1` whose module reports `1.2.0`. Matching
  since 1.2.2. The wheel takes its version from CMake (`PROJECT_VERSION`
  via `pyproject.toml.in`), so the CMake/changelog check is what keeps the
  wheel on the changelog version.
- Making a ghcr package public is **irreversible**; everything in the final
  stage's layers and `docker history` becomes public.

## Pipeline

```
my-magnettools (maintainer machine, on LAN)            scripts/release.sh [--publish]
 ├─ 1. deb          pdebuild (cowbuilder trixie-amd64) → libmagnettools1, -dev, python3-magnettools, …
 ├─ 2. wheel+image  docker buildx bake, debs as named build context:
 │                    target "wheel"   → magnettools-<UPSTREAM_VERSION>-cp313-linux_x86_64.whl
 │                    target "runtime" → debian:trixie + libmagnettools1 + /opt/wheels + uv
 ├─ 3. checks       version consistency; smoke import test; public-safety check on the image
 └─ 4. publish      dupload → euler · push ghcr.io/trophime/magnettools:<DEB_VERSION>-trixie (+ :trixie)
    (--publish)     gh release v<DEB_VERSION> (wheel + debs) · repository_dispatch → downstream repos
                                                         │
     downstream (GitHub-hosted runners) ◀────────────────┘
       container: ghcr.io/trophime/magnettools:<DEB_VERSION>-trixie
       uv lock --upgrade-package magnettools → uv sync → pytest
```

## Phase 1 — my-magnettools

### Files affected

| Path | Action |
|---|---|
| `Python/pyproject.toml` | **delete** (`git rm`) — step 0; `Python/pyproject.toml.in` becomes the single source of Python packaging metadata |
| `Python/install_python_bindings-pip.sh` | **edit** — step 0: build the wheel from the CMake build dir (`pip wheel "$BUILD_DIR" --no-deps -w "$BUILD_DIR/dist"`, where the generated `pyproject.toml` lives) instead of `cd $SCRIPT_DIR; pip wheel . -w dist/` (lines 125-126); also fixes the existing mismatch with the upload step that looks in `$BUILD_DIR/dist` |
| `Python/pytest.ini` | **create** — step 0: carries the current `[tool.pytest.ini_options]` (`testpaths`, `python_files`, `plots` marker) so `pytest` run from `Python/` or `Python/tests` keeps its config |
| `.gitignore` | **edit** — step 0: add `Python/pyproject.toml` so an in-source configure (build dir = `Python/`) cannot recommit the generated file |
| `Python/VERSIONING.md`, `Python/README.md` | **edit** — step 0: describe the generated-only `pyproject.toml` |
| `docker/Dockerfile-DB` | **edit (rewrite)** — stages: `lncmi` (LNCMI repo, apt key as BuildKit secret, as today) → `builder` (install local `libmagnettools1` + `libmagnettools-dev` debs, `cmake -S Python`, `uv build --wheel`) → `wheel` (`FROM scratch`, wheel only) → `runtime` (`debian:trixie` + `python3` + local `libmagnettools1` deb + `/opt/wheels/*.whl` + `uv`, `UV_PYTHON` set, OCI `source`/`version` labels; no `jovyan`, no LNCMI repo, no `LD_LIBRARY_PATH`) |
| `docker/docker-bake.hcl` | **edit** (currently untracked WIP) — `REGISTRY=ghcr.io/trophime`, `DEB_VERSION` variable (passed by `release.sh`, no default version in the file), `debs` named context, targets `wheel` (local output) and `runtime` (`linux/amd64`, tags `${DEB_VERSION}-trixie`, `trixie`); drop arm64 targets |
| `scripts/release.sh` | **create** — steps below; default = build + test only, `--publish` = publish after a y/N prompt |
| `docker/README.md` | **edit** — new build/release flow, one-time "make package public" step |

### `release.sh` sequence

1. Preconditions (abort on any mismatch):
   - `DEB_VERSION` = `dpkg-parsechangelog -S Version`; `UPSTREAM_VERSION` =
     `DEB_VERSION` minus the `-<revision>` suffix.
   - `project(magnettools VERSION x.y.z)` in `CMakeLists.txt` == `UPSTREAM_VERSION`.
   - clean tree; image tag `ghcr.io/trophime/magnettools:<DEB_VERSION>-trixie`
     and git tag `v<DEB_VERSION>` do **not** exist yet.
2. `pdebuild` in cowbuilder `trixie-amd64` → copy debs to `build/release/debs/`;
   check the `.changes` file is `magnettools_<DEB_VERSION>_amd64.changes`.
3. `docker buildx bake wheel runtime` with `DEB_VERSION` (debs context) →
   wheel to `build/release/wheels/`; check the wheel file is
   `magnettools-<UPSTREAM_VERSION>-cp313-…whl` (exactly one).
4. Smoke test in `runtime`: `uv venv` → `uv pip install --find-links /opt/wheels magnettools`
   → `python -c "import magnettools.magnettools, magnettools.Bmap"`, plus
   version checks: `importlib.metadata.version("magnettools")` and
   `magnettools/__version.py` == `UPSTREAM_VERSION`;
   `dpkg-query -W libmagnettools1` == `DEB_VERSION`.
5. Public-safety check: fail if `docker history` mentions `euler`/`lncmig`, or
   the image contains sources/`/src`.
6. *(`--publish`, after y/N)*: `dupload` the `.changes` → `bake runtime --push`
   → `gh release create v<DEB_VERSION>` with wheel + debs → `gh api …/dispatches`
   (`event_type=magnettools-release`, payload `{deb_version, version, image}`) to
   `DOWNSTREAM_REPOS` (default: `Trophime/magnetdb-duckdb-demo`).

### Steps

0. Remove the committed `Python/pyproject.toml` (single version source):
   `git rm Python/pyproject.toml`; create `Python/pytest.ini` with its
   `[tool.pytest.ini_options]`; fix `install_python_bindings-pip.sh` to build
   from `$BUILD_DIR`; add `Python/pyproject.toml` to `.gitignore`; update
   `VERSIONING.md` / `README.md` → verify:
   - `git ls-files Python/pyproject.toml` is empty; `git check-ignore Python/pyproject.toml` matches;
   - `bash Python/install_python_bindings-pip.sh` (wheel option) produces
     `$BUILD_DIR/dist/magnettools-1.2.3-…whl` (version from CMake, not 1.2.0);
   - `Python/Dockerfile-test-python-bindings` builds and its `pytest` run
     passes with the same collected tests as before (compare
     `pytest --collect-only -q` before/after).
1. Rewrite `Dockerfile-DB` + bake → verify: `bake wheel runtime` with
   `DEB_VERSION=1.2.3-1` succeeds from existing 1.2.3-1 debs; wheel is
   `magnettools-1.2.3-cp313-…whl`; image tagged `1.2.3-1-trixie`; smoke test
   and version checks pass.
2. RUNPATH check on the wheel built in the image (already verified for the
   deb-installed module) → verify: `readelf -d` on the wheel's module shows a
   RUNPATH including `…/MagnetTools`; smoke test passes with
   `LD_LIBRARY_PATH` unset.
3. `release.sh` → verify: `shellcheck` clean; run without `--publish`
   performs steps 1–5 and publishes nothing; a deliberate mismatch (temporarily
   edit the CMake version in a scratch copy) makes step 1 abort.
4. README → verify: review.
5. Maintainer runs `release.sh --publish` the first time (needs
   `gh auth refresh -s write:packages` + `docker login ghcr.io`) → verify:
   `apt policy libmagnettools1` shows 1.2.3-1 from euler; package visible
   under github.com/Trophime?tab=packages → set **public** once; anonymous
   `docker pull ghcr.io/trophime/magnettools:1.2.3-1-trixie` works; release
   `v1.2.3-1` has wheel + debs.

### Assumptions & open questions

- **A1** Registry `ghcr.io/trophime/magnettools` — to confirm.
- **A2** Cowbuilder `trixie-amd64` exists locally; public key at
  `../apt-depot/lncmi-repo-ci-public-key.asc`.
- **A3** All `libmagnettools1` runtime deps (`shlibs:Depends`) are in standard
  Debian trixie (check with `dpkg -I`). If one is LNCMI-only, add its deb to
  the `debs` context so `runtime` never references euler (→ re-plan).
- **A4** cp313 only (trixie system Python); uv 0.12.23 as in python_magnetdb.
- **A5** `gh release create` creates tag `v<DEB_VERSION>` on current HEAD; the
  maintainer commits/pushes before publishing.
- **Wheel metadata source**: the `builder` stage builds the wheel only from the
  `pyproject.toml` that CMake generates from `Python/pyproject.toml.in` in the
  build directory (`cmake -S Python -B build` → `uv build --wheel build`),
  never from the `Python/` source folder. The generated file carries the CMake
  version, already checked against `debian/changelog`; the wheel filename check
  (step 3) catches any slip.
- **A6** (step 0) The git-tracked `Python/pyproject.toml` hardcodes
  `version = "1.2.0"` (despite `Python/VERSIONING.md` describing a dynamic
  version) and is read by `install_python_bindings-pip.sh` (`pip wheel .` in
  `Python/`, likely origin of stray 1.2.0 wheels) and by pytest (config) when
  run from `Python/tests` (as `Python/Dockerfile-test-python-bindings` does).
  It does not affect the release build itself (excluded from source archives
  by `archive.sh`). Removing it requires the step 0 companion changes;
  no other consumer found (`start-venv.sh` only installs other packages).

## Phase 2 — magnetdb-duckdb-demo (this repo)

uv migration, consuming the image:

- Both devcontainer variants `FROM ghcr.io/trophime/magnettools:<DEB_VERSION>-trixie`
  (keep texlive, motd, `myuser`).
- Root `pyproject.toml` (`package = false`): all deps from the old
  `setup-basic.sh` + `magnettools`; editable path sources for the 4 submodules,
  `to_duckdb`, the dashboard; flat index `/opt/wheels` (`explicit = true`);
  `requires-python = ">=3.13,<3.14"`.
- `uv.lock` committed; venv in `/home/myuser/.venv` (`UV_PROJECT_ENVIRONMENT`),
  no `--system-site-packages`; `setup-uv.sh` = submodules + `uv sync --frozen`;
  delete `setup-basic.sh`; update READMEs, motd, pyproject comment headers;
  dashboard `Dockerfile` pip → `uv pip`.
- `.github/workflows/ci.yml` on `push`, `pull_request`, `repository_dispatch`
  (`magnettools-release`) → verify: dispatch from `release.sh` yields a green
  `pytest` run on a GitHub-hosted runner.

Detailed plan to be presented separately.

## Phase 3 — later

- python_magnetdb, python_magnetapi: replace build stages with
  `FROM ghcr.io/trophime/magnettools:<DEB_VERSION>-trixie` + dispatch-triggered CI.
- Optional: public build-deps image so magnettools itself can build on
  GitHub-hosted runners (debs still uploaded to euler from the LAN).
- GitHub App (Contents + Pull requests write, installed on `Trophime` and
  `MagnetDB`) → bump PRs (image tag + `uv.lock`) on release.

## Limits to keep in mind

- Public ghcr package: free storage and transfer, anonymous pulls.
- Actions minutes for private repos (2000/month on Free, per owner) — the only
  real budget; local release uses none.
