# Plan: magnettools release pipeline (deb + wheel + public image)

Status: **draft — not approved**. Phase 1 targets `Trophime/magnettools`
(`../my-magnettools`); Phase 2 targets this repo; Phase 3 python_magnetdb.
Both downstream projects follow the same
[consumption pattern](#downstream-consumption-pattern-common-to-all-consumers).

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
  (Aligned again on 2026-10-19: changelog, python_magnetdb `Dockerfile(-dev)`
  and `uv.lock` all at 1.2.4 — but only by hand, nothing enforces it.)
- This repo still relies on `--system-site-packages` + the `python3-magnettools`
  deb from `trophime/magnettools:trixie` — a **moving** tag, so a rebuild
  silently changes the magnettools version.
- The two consumers use two different patterns (this repo: system
  site-packages; python_magnetdb: own wheel build + `uv.lock`), hence two bump
  procedures to remember.

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
| `python3-magnettools` in image | **yes**, for ad-hoc use (notebooks, scripts, `python3 -m venv --system-site-packages`). Downstream *projects* never use it: an isolated venv does not see `dist-packages`, so both copies coexist without conflict |
| Downstream consumption | **one pattern for every consumer** (this repo, python_magnetdb, later python_magnetapi): `FROM` the pinned image tag, `magnettools` declared in `pyproject.toml` and locked in `uv.lock` from the `/opt/wheels` flat index, isolated venv, `uv sync --frozen` — see [pattern](#downstream-consumption-pattern-common-to-all-consumers). No `--system-site-packages` in projects |
| Bump procedure | the same `scripts/bump-magnettools.sh <DEB_VERSION>` in every consumer: rewrite the image tag + `uv lock --upgrade-package magnettools` run inside the new image |
| Source repo for CI | `Trophime/magnettools` |
| Registry | **Docker Hub** `trophime/magnettools`, **public** as today (decided 2026-10-19). ghcr.io may be revisited later |
| Version source | **`debian/changelog` only**: `DEB_VERSION` = `dpkg-parsechangelog -S Version` (e.g. `1.2.4-1`), `UPSTREAM_VERSION` = `DEB_VERSION` without the Debian revision (e.g. `1.2.4`). Every other version is derived from or checked against it |
| Tags | image `<DEB_VERSION>-trixie` (e.g. `1.2.4-1-trixie`, immutable, never rebuilt) + `trixie` (moving); git/GitHub release `v<DEB_VERSION>`; wheel version = `UPSTREAM_VERSION` (PEP 440 has no Debian revision). A packaging-only bump (`1.2.4-2`) gets its own image tag |
| Architectures | amd64 only at first ([arm64 later](#later)). From the start, `/opt/wheels` in each platform's image holds the wheels of **all** released architectures: consumers' `uv.lock` records only the wheels it sees, so a single-arch `/opt/wheels` would make `uv sync --frozen` fail on the other arch (e.g. a devcontainer on Apple Silicon) |
| Runner | **no self-hosted runner for now** → release from the maintainer's machine with `scripts/release.sh` (same Dockerfile/bake a future CI would use) |
| Downstream trigger | `repository_dispatch` sent with the maintainer's own `gh` auth (no token secret needed while releasing locally) |
| Downstream reaction | **(a) test only** for now: CI runs `bump-magnettools.sh` on the dispatched version (no commit) then `uv sync --frozen` + `pytest`; **(b) bump PR** + GitHub App later (same script, committed) |
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
  VERSION 1.2.3)` → **match**. Re-checked 2026-10-19 (HEAD `01f589a`):
  `1.2.4-1` / `VERSION 1.2.4` → **match**; a test build of `1.2.4-1` gives
  a python module RUNPATH including `…/MagnetTools`. History shows the past drift: changelog
  `1.2.1-1` (commit `e7b6ff4`) was released with CMake still at `1.2.0` —
  hence the published deb `1.2.1-1` whose module reports `1.2.0`. Matching
  since 1.2.2. The wheel takes its version from CMake (`PROJECT_VERSION`
  via `pyproject.toml.in`), so the CMake/changelog check is what keeps the
  wheel on the changelog version.
- The Docker Hub repository is public: everything in the final stage's layers
  and `docker history` is public, and a pushed tag cannot be recalled from
  whoever already pulled it — hence the public-safety check before pushing.
  This includes the compiled binaries of the private sources (already the
  case for today's `trophime/magnettools:trixie`).
- The `runtime` image must not contain the LNCMI apt source
  (`/etc/apt/sources.list.d/lncmi.list`), public or not: downstream
  Dockerfiles run `apt-get update`, which fails wherever euler is unreachable
  (GitHub-hosted runners, outside the LAN). Local debs are installed with
  `apt-get install ./*.deb` against the Debian archive only — which also
  requires A3.
- `python3-magnettools` pulls `python3-numpy`, `-scipy`, `-matplotlib`,
  `-tabulate` from Debian (≈ +150 MB). Accepted for the ad-hoc mode; projects
  get their own versions in their venv.
- `uv.lock` records the wheel's hash. Image tags are immutable (never
  rebuilt), so a given tag always carries the same wheel and the lock stays
  valid; `SOURCE_DATE_EPOCH=0` in the `builder` stage (as python_magnetdb does
  today) keeps the hash reproducible should a rebuild ever be needed.

## Pipeline

```
my-magnettools (maintainer machine, on LAN)            scripts/release.sh [--publish]
 ├─ 1. deb          pdebuild (cowbuilder trixie-amd64) → libmagnettools1, -dev, python3-magnettools, …
 ├─ 2. wheel+image  docker buildx bake, debs as named build context:
 │                    target "wheel"   → magnettools-<UPSTREAM_VERSION>-cp313-linux_x86_64.whl
 │                    target "runtime" → debian:trixie + libmagnettools1 + python3-magnettools
 │                                       + /opt/wheels + uv (no LNCMI apt source)
 ├─ 3. checks       version consistency; smoke import test (venv + system); public-safety check on the image
 └─ 4. publish      dupload → euler · push trophime/magnettools:<DEB_VERSION>-trixie (+ :trixie)
    (--publish)     gh release v<DEB_VERSION> (wheel + debs) · repository_dispatch → downstream repos
                                                         │
     downstream (GitHub-hosted runners) ◀────────────────┘
       this repo, python_magnetdb — same workflow, same script:
       scripts/bump-magnettools.sh <DEB_VERSION>   (image tag + uv lock, in the new image)
       → uv sync --frozen → pytest                 (test only; bump PR later)
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
| `docker/Dockerfile-DB` | **edit (rewrite)** — stages: `lncmi` (LNCMI repo, apt key as BuildKit secret, as today) → `builder` (install local `libmagnettools1` + `libmagnettools-dev` debs, `cmake -S Python`, `uv build --wheel`) → `wheel` (`FROM scratch`, wheel only) → `runtime` (`debian:trixie` + `python3` + local `libmagnettools1` and `python3-magnettools` debs + `/opt/wheels/*.whl` (wheels of all released architectures) + `uv`; ENV `UV_PYTHON=/usr/bin/python3`, `UV_PYTHON_DOWNLOADS=never`, `LANG=C.UTF-8`, `LC_ALL=C.UTF-8`, `DEBIAN_FRONTEND=noninteractive` (consumers rely on them, see Phase 3), OCI `source`/`version` labels; no `jovyan`, no LNCMI repo, no `LD_LIBRARY_PATH`) |
| `docker/docker-bake.hcl` | **edit** (currently untracked WIP) — `REGISTRY=docker.io/trophime`, `DEB_VERSION` variable (passed by `release.sh`, no default version in the file), `debs` named context, targets `wheel` (local output) and `runtime` (`linux/amd64`, tags `${DEB_VERSION}-trixie`, `trixie`); drop arm64 targets |
| `scripts/release.sh` | **create** — steps below; default = build + test only, `--publish` = publish after a y/N prompt |
| `docker/README.md` | **edit** — new build/release flow (Docker Hub login, tags) |

### `release.sh` sequence

1. Preconditions (abort on any mismatch):
   - `DEB_VERSION` = `dpkg-parsechangelog -S Version`; `UPSTREAM_VERSION` =
     `DEB_VERSION` minus the `-<revision>` suffix.
   - `project(magnettools VERSION x.y.z)` in `CMakeLists.txt` == `UPSTREAM_VERSION`.
   - clean tree; image tag `trophime/magnettools:<DEB_VERSION>-trixie`
     and git tag `v<DEB_VERSION>` do **not** exist yet.
2. `pdebuild` in cowbuilder `trixie-amd64` → copy debs to `build/release/debs/`;
   check the `.changes` file is `magnettools_<DEB_VERSION>_amd64.changes`.
3. `docker buildx bake wheel runtime` with `DEB_VERSION` (debs context) →
   wheel to `build/release/wheels/`; check the wheel file is
   `magnettools-<UPSTREAM_VERSION>-cp313-…whl` (exactly one).
4. Smoke test in `runtime`, both modes:
   - project mode: `uv venv` (isolated) → `uv pip install --find-links /opt/wheels magnettools`
     → `python -c "import magnettools.magnettools, magnettools.Bmap"`; check
     `magnettools.__file__` is inside the venv (the wheel, not `dist-packages`);
   - ad-hoc mode: `/usr/bin/python3 -c "import magnettools"` (deb module);
   - version checks: `importlib.metadata.version("magnettools")` and
     `magnettools/__version.py` == `UPSTREAM_VERSION`;
     `dpkg-query -W libmagnettools1 python3-magnettools` == `DEB_VERSION`.
5. Public-safety check: fail if `docker history` mentions `euler`/`lncmig`,
   the image contains `/etc/apt/sources.list.d/lncmi.list`, or sources/`/src`.
6. *(`--publish`, after y/N)*: `dupload` the `.changes` → `bake runtime --push`
   → `gh release create v<DEB_VERSION>` with wheel + debs → `gh api …/dispatches`
   (`event_type=magnettools-release`, payload `{deb_version, version, image}`) to
   `DOWNSTREAM_REPOS` (default: `Trophime/magnetdb-duckdb-demo`;
   `Trophime/python_magnetdb` added in Phase 3).

### Steps

0. Remove the committed `Python/pyproject.toml` (single version source):
   `git rm Python/pyproject.toml`; create `Python/pytest.ini` with its
   `[tool.pytest.ini_options]`; fix `install_python_bindings-pip.sh` to build
   from `$BUILD_DIR`; add `Python/pyproject.toml` to `.gitignore`; update
   `VERSIONING.md` / `README.md` → verify:
   - `git ls-files Python/pyproject.toml` is empty; `git check-ignore Python/pyproject.toml` matches;
   - `bash Python/install_python_bindings-pip.sh` (wheel option) produces
     `$BUILD_DIR/dist/magnettools-1.2.4-…whl` (version from CMake, not 1.2.0);
   - `Python/Dockerfile-test-python-bindings` builds and its `pytest` run
     passes with the same collected tests as before (compare
     `pytest --collect-only -q` before/after).
1. Rewrite `Dockerfile-DB` + bake → verify: `bake wheel runtime` with
   `DEB_VERSION=1.2.4-1` succeeds from existing 1.2.4-1 debs; wheel is
   `magnettools-1.2.4-cp313-…whl`; image tagged `1.2.4-1-trixie`; smoke test
   and version checks pass.
2. RUNPATH check on the wheel built in the image (already verified for the
   deb-installed module) → verify: `readelf -d` on the wheel's module shows a
   RUNPATH including `…/MagnetTools`; smoke test passes with
   `LD_LIBRARY_PATH` unset.
3. `release.sh` → verify: `shellcheck` clean; run without `--publish`
   performs steps 1–5 and publishes nothing; a deliberate mismatch (temporarily
   edit the CMake version in a scratch copy) makes step 1 abort.
4. README → verify: review.
5. Maintainer runs `release.sh --publish` the first time (needs `docker login`
   to Docker Hub as `trophime`, with an access token, and `gh` auth for the
   release and dispatch) → verify: `apt policy libmagnettools1` shows 1.2.4-1
   from euler; anonymous `docker pull trophime/magnettools:1.2.4-1-trixie`
   works; the moving `trixie` tag points to the same digest; release
   `v1.2.4-1` has wheel + debs.

### Assumptions & open questions

- **A1** *(resolved 2026-10-19)* Docker Hub `trophime/magnettools`, public as
  today: no pull credentials needed in any consumer, cross-organization
  included. Today's moving `trixie` tag keeps working for current users
  until they move to pinned `<DEB_VERSION>-trixie` tags.
- **A2** Cowbuilder `trixie-amd64` exists locally; public key at
  `../apt-depot/lncmi-repo-ci-public-key.asc`.
- **A3** All `libmagnettools1` and `python3-magnettools` runtime deps
  (`shlibs:Depends`, `python3:Depends`) are in standard Debian trixie (check
  with `dpkg -I`). If one is LNCMI-only, add its deb to the `debs` context so
  `runtime` never references euler (→ re-plan).
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

## Downstream consumption pattern (common to all consumers)

Every project that imports magnettools (this repo, python_magnetdb, later
python_magnetapi) does exactly the same, so maintenance is one procedure.
python_magnetrun does not import the binding (it only has a stub reader for
magnettools *output files*) and stays independent of it — if it ever needs
the binding, make it an optional extra with a lazy import.

1. **Image tag in one place per Dockerfile**: every Dockerfile / devcontainer
   of the project starts from
   `trophime/magnettools:<DEB_VERSION>-trixie` — never the moving `trixie`
   tag. All of them carry the same tag. The tag lives wherever the image is
   chosen: a literal `FROM`, an `ARG BASE_IMAGE` default, **and**
   `build.args.BASE_IMAGE` in `devcontainer.json`, which overrides the
   Dockerfile default (this repo's devcontainers choose their image there).
2. **`pyproject.toml`** declares magnettools like python_magnetdb does today:
   ```toml
   [project]
   requires-python = ">=3.13,<3.14"     # cp313 wheel = trixie Python
   dependencies = ["magnettools", ...]

   [[tool.uv.index]]
   name = "magnettools"
   url = "/opt/wheels"                  # inside the image
   format = "flat"
   explicit = true

   [tool.uv.sources]
   magnettools = { index = "magnettools" }
   ```
3. **Isolated venv** + `uv sync --frozen`, in image builds and CI. Never
   `--system-site-packages`.
4. **Guard**: if the image tag and `uv.lock` disagree, `uv sync --frozen` fails
   (missing file / hash mismatch) — intended: a half-done bump cannot pass CI.
5. **`scripts/bump-magnettools.sh <DEB_VERSION>`**, the same file in every
   consumer:
   - rewrite the image tag in every place of item 1 (`FROM`, `ARG BASE_IMAGE`
     defaults, `devcontainer.json` `build.args`), and fail if they did not all
     carry the same tag before;
   - `uv lock --upgrade-package magnettools` — run directly when `/opt/wheels`
     exists (already inside the image, as in CI), else through
     `docker run --rm -v "$PWD":/w -w /w <image>`;
   - check the `magnettools` version in `uv.lock` == `UPSTREAM_VERSION`.
6. **`.github/workflows/ci.yml`** on `push`, `pull_request` and
   `repository_dispatch` (`magnettools-release`): job `container:` = the
   pinned image (push/PR) or `client_payload.image` (dispatch); on dispatch run
   `bump-magnettools.sh` first, without committing; then `uv sync --frozen` +
   `pytest`. The image is public (A1), so no pull credentials; logging in to
   Docker Hub (`container.credentials` with a read-only token) is only useful
   against anonymous pull rate limits.

## Phase 2 — magnetdb-duckdb-demo (this repo)

> **Note (2026-10-26):** the devcontainer, dashboard image and `setup-uv.sh`
> parts are now covered by [PLAN_magnettools_optional.md](PLAN_magnettools_optional.md),
> which departs from this section: magnettools is optional in to_duckdb
> (hoop-stress only); the dashboard image is `python:3.13-slim-trixie`
> without magnettools; the devcontainer is `debian:trixie` +
> `COPY --from=magnettools-db:trixie-1.2.6`; `setup-uv.sh` uses
> `uv pip install` (`setup-basic.sh` kept); venvs live in
> `$VENV_DIR=/home/myuser/.venvs/magnetdb` (+ `.venv-systempackage`).
> The root `pyproject.toml`, `uv.lock`, `bump-magnettools.sh` and CI below
> remain to do.

uv migration onto the [common pattern](#downstream-consumption-pattern-common-to-all-consumers):

- Devcontainer image: `.devcontainer/Dockerfile` takes `ARG BASE_IMAGE`, and
  the image is actually chosen by `build.args.BASE_IMAGE` in the two
  `devcontainer.json` files — today `debian:trixie` (default variant, no
  magnettools) and `trophime/magnettools:trixie` (`local/`, moving tag).
  Both pass `trophime/magnettools:<DEB_VERSION>-trixie`; the Dockerfile
  default too (keep texlive, motd, `myuser`).
- Merge the two variants into `.devcontainer/devcontainer.json`, delete
  `local/`: the default variant presumably used `debian:trixie` because the
  current image carries the LNCMI apt source (`apt-get update` fails outside
  the LAN); the new image has none, so one variant works everywhere. Keep
  `local/` only if a variant without magnettools is really wanted (e.g.
  Codespaces) — to confirm.
- Dashboard `Dockerfile` (`apps/dashboards/magnetdb/Dockerfile`, today
  `ARG BASE_IMAGE=trophime/magnettools:trixie`) starts from the same pinned
  tag.
- Root `pyproject.toml` (`package = false`): all deps from the old
  `setup-basic.sh` + `magnettools` declared as in the pattern; editable path
  sources for the 4 submodules, `to_duckdb`, the dashboard.
- `uv.lock` committed; venv in `/home/myuser/.venv` (`UV_PROJECT_ENVIRONMENT`
  set in `.devcontainer/Dockerfile`), no `--system-site-packages`:
  - `setup-uv.sh` = submodules + `uv sync --frozen`; drop its check that
    *requires* `include-system-site-packages = true` and any uv install (uv
    comes from the base image);
  - `devcontainer.json`: `postCreateCommand` / `postStartCommand` call
    `setup-uv.sh` (the `.venv` test becomes a test on
    `/home/myuser/.venv`); `python.defaultInterpreterPath` →
    `/home/myuser/.venv/bin/python` (today `${workspaceFolder}/.venv`);
  - delete `setup-basic.sh`; update READMEs, motd, pyproject comment headers.
- Cleanups: the stale `jovyan` comments in `.devcontainer/Dockerfile` and both
  `devcontainer.json`; consider dropping `apt-get -y upgrade` (makes each
  rebuild differ; does not touch magnettools, which has no apt source in the
  image).
- Dashboard `Dockerfile`: the three `pip install` lines → a locked install
  from the root `uv.lock` (so the dashboard image gets the same magnettools as
  the devcontainer).
- `scripts/bump-magnettools.sh` + `.github/workflows/ci.yml` from the pattern
  → verify: dispatch from `release.sh` yields a green `pytest` run on a
  GitHub-hosted runner.

Detailed plan to be presented separately.

## Phase 3 — python_magnetdb

Move onto the same pattern; its `pyproject.toml` index/source config already
matches it.

- `Dockerfile` (107 → ~30 lines): replace the `uv`, `lncmi-key`, `lncmi` and
  `magnettools` stages with `FROM trophime/magnettools:<DEB_VERSION>-trixie`;
  drop `ARG MAGNETTOOLS_VERSION`, `ARG DEBIAN_DIST`, `SOURCE_DATE_EPOCH` and
  `ENV LD_LIBRARY_PATH` (redundant, see Constraints, and hard-coded x86_64).
  This drops the LAN requirement, the `apt-depot` build context and the
  `lncmi_apt_auth` secret. What remains:
  ```dockerfile
  # MagnetDB api/worker image, on the magnettools base image
  # (libmagnettools1, magnettools wheels in /opt/wheels, uv: see my-magnettools)
  FROM trophime/magnettools:1.2.4-1-trixie

  ARG USERNAME=feelpp
  ARG USER_UID=1000
  ARG USER_GID=$USER_UID

  RUN apt-get update \
      && apt-get install -y --no-install-recommends \
          ca-certificates curl git openssh-client sudo \
          iputils-ping vim-nox emacs-nox wait-for-it debconf-utils libpq-dev \
      && rm -rf /var/lib/apt/lists/*

  # local user matching the host user id and group id (-l: no lastlog entry, large uids)
  RUN if ! getent group ${USER_GID} >/dev/null; then groupadd -g ${USER_GID} ${USERNAME}; fi \
      && useradd -l -m -s /bin/bash -u ${USER_UID} -g ${USER_GID} -G sudo,video ${USERNAME} \
      && echo "${USERNAME} ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
      && chmod 0440 /etc/sudoers.d/${USERNAME} \
      && mkdir -p /home/${USERNAME}/.ssh /home/${USERNAME}/.cache \
      && ssh-keyscan github.com >> /home/${USERNAME}/.ssh/known_hosts \
      && chown -R ${USER_UID}:${USER_GID} /home/${USERNAME}

  # venv outside the bind-mounted sources; copy mode (uv cache volume on another fs)
  ENV UV_PROJECT_ENVIRONMENT=/home/${USERNAME}/.venv \
      UV_LINK_MODE=copy

  USER $USERNAME
  WORKDIR /home/$USERNAME
  ```
- `Dockerfile-dev`: **delete** — identical to `Dockerfile` except for a
  comment. The `web-api` and `web-worker` services switch
  `dockerfile: Dockerfile-dev` to `dockerfile: Dockerfile` in
  `docker-compose-dev-traefik-ssl.yml` and
  `.devcontainer/docker-compose-dev-traefik-ssl.yml`. Not `web-app`: its `Dockerfile-dev` is `web/Dockerfile-dev`
  (`context: web`), a different file that stays. The `.devcontainer` compose
  file has no `apt-depot` context, so today it presumably cannot build the
  current `Dockerfile-dev` (`COPY --from=apt-depot`); the simplified
  `Dockerfile` fixes that.
- Compose: remove the `apt-depot` build context from `web-api` and
  `web-worker` (2 lines each) in `docker-compose-traefik-ssl.yml` (lines
  28-29, 87-88) and `docker-compose-dev-traefik-ssl.yml` (lines 27-28,
  89-90):
  ```yaml
        additional_contexts:
          apt-depot: ../apt-depot  # LNCMI apt repository public key
  ```
  Left in place, they would force an `../apt-depot` checkout next to
  python_magnetdb for every build. Nothing else in compose is
  magnettools-related: no `secrets:` entry (`lncmi_apt_auth` is optional in
  the Dockerfile and only shown as an example in `README-dev.md`, lines
  113-116, removed with it); `USER_UID`/`USER_GID` args stay.
- `Dockerfile-env`: **delete** — legacy Poetry-era image
  (`FROM trophime/magnettools:bookworm-poetry-new`), referenced by no compose
  file.
- Choices to make when implementing:
  - **uv version**: from the base image by default, so it follows magnettools
    releases; to pin it independently, keep
    `COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /uvx /usr/local/bin/`.
  - **ENV from the base image**: `UV_PYTHON`, `UV_PYTHON_DOWNLOADS=never`,
    `LANG`/`LC_ALL`, `DEBIAN_FRONTEND` are set by the Phase 1 `runtime`
    stage; verify they are there before dropping them from this file.
  - **Digest pinning** (optional): today the build checks the LNCMI key
    fingerprint and trusts the euler repo; afterwards trust sits in the
    Docker Hub tag. `FROM trophime/magnettools:1.2.4-1-trixie@sha256:…` makes
    it as strict; `bump-magnettools.sh` then rewrites the digest too.
- Copy `scripts/bump-magnettools.sh`; it replaces the manual procedure in
  `README-dev.md` (edit `MAGNETTOOLS_VERSION`, then `uv lock` in the api
  container).
- `ci.yml` from the pattern; add `Trophime/python_magnetdb` to
  `DOWNSTREAM_REPOS` in `release.sh`.

## Later

- python_magnetapi: same pattern.
- **arm64 image** (arm64 debs 1.2.4-1 already on euler, checked 2026-10-20):
  - debs: `distro.sh build trixie arm64` (arch-dependent packages only) in a
    `trixie-arm64` cowbuilder — under QEMU ≈ 5–20× the amd64 build, or
    `DEB_BUILD_OPTIONS=nocheck`, or a native arm64 machine;
  - bake: `platforms = ["linux/amd64", "linux/arm64"]` → one manifest per tag
    on Docker Hub; the `runtime` stage installs the debs of `$TARGETARCH`;
    the `builder` stage compiles one wheel per platform (`x86_64`,
    `aarch64`), and both go into `/opt/wheels` of both images (see
    Architectures);
  - release machine, one-time: a qemu `aarch64` binfmt handler with the `F`
    flag (`qemu-user-binfmt`), and a buildx builder able to build
    multi-platform images (`docker buildx create --driver docker-container
    --use`) — the default `docker` driver cannot;
  - `release.sh`: arm64 `.changes` uploaded with the amd64 one; smoke test
    run per platform (arm64 under QEMU).
- Optional: public build-deps image so magnettools itself can build on
  GitHub-hosted runners (debs still uploaded to euler from the LAN).
- GitHub App (Contents + Pull requests write, installed on `Trophime` and
  `MagnetDB`) → bump PRs on release: the dispatch job runs the same
  `bump-magnettools.sh` and commits its result (PRs opened with
  `GITHUB_TOKEN` would not trigger CI, hence the App).

## Limits to keep in mind

- Public Docker Hub repository: anonymous pulls are rate-limited per IP, and
  GitHub-hosted runners share IPs. If CI hits the limit, log in with a
  read-only Docker Hub token (see pattern item 6).
- Actions minutes for private repos (2000/month on Free, per owner) — the only
  real budget; local release uses none.
