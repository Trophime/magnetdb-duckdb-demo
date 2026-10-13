# Plan: self-hosted GitHub runner for magnettools

Status: **draft — not approved**. Prerequisite for
[PLAN_magnettools_release_pipeline.md](PLAN_magnettools_release_pipeline.md),
which currently records "no self-hosted runner for now" (to be revised by
step 6).

## Goal

A persistent self-hosted runner on calcul24, registered only to
`Trophime/magnettools` with labels `self-hosted, linux, x64, lncmi-lan`,
running as a systemd service, and proven by one green test workflow that
reaches Docker, euler and cowbuilder.

## Findings (calcul24, 2026-10-13)

| Item | Value |
|---|---|
| Account type | `Trophime` is a **personal account**, not an organization → runner registered per repo, on `Trophime/magnettools` (private) only |
| Public repo | `Trophime/magnetdb-duckdb-demo` is **public** → the runner must **never** be attached to it (fork PRs could run code on calcul24). Phase 2 already uses GitHub-hosted runners there |
| Network | `api.github.com` and `ghcr.io` reachable, no proxy |
| Resources | Ubuntu 26.04.1, x86_64, 22 cores, 61 GB RAM, Docker 29.9 + buildx 0.38; disk 83 % full (152 GB free) — watch it |
| Debian builds | **never run on this host**: no cowbuilder `trixie-amd64` base in `/var/cache/pbuilder/` → A2 of the pipeline plan is false here; no build job can run until the base exists |
| `~/.pbuilderrc` | still maps trixie → `testing` (`TESTING_CODENAME="trixie"`), so the euler repo line uses suite `testing`; trixie is Debian stable since August 2025 |
| Passwordless already | sudo for `pbuilder`/`cowbuilder`; `~/.ssh/id_rsa` (no passphrase → `dupload` to euler could run unattended); Docker (user in `docker` group) |
| Needs sudo password | everything else (`apt install`, `svc.sh install`) |
| `gh` CLI | not installed |
| Existing runner | none (`~/actions-runner*`, `/opt/actions-runner*`, `actions.runner.*` units absent); `my-magnettools` has no `.github/workflows` |

## Files affected

| Path | Action |
|---|---|
| `~/actions-runner/` (calcul24) | create: runner binaries and config |
| `/etc/systemd/system/actions.runner.Trophime-magnettools.calcul24.service` | create, via `svc.sh` (**maintainer runs it, needs sudo**) |
| `../my-magnettools/.github/workflows/runner-smoke.yml` | create, on a new branch `ci/runner-smoke` |
| `PLAN_magnettools_release_pipeline.md` | edit: replace the "no self-hosted runner" row in the decisions table, mark A2 as false on calcul24, add the public-repo rule |

## Steps

1. **Maintainer** runs `sudo apt install gh`, then `gh auth login` (scopes
   `repo`, `workflow`) → verify: `gh auth status` shows Trophime.
2. Download the latest `actions/runner` linux-x64 release into
   `~/actions-runner` → verify: its sha256 matches the one in the release
   notes.
3. Register the runner: get a registration token with
   `gh api -X POST repos/Trophime/magnettools/actions/runners/registration-token`,
   then
   `./config.sh --unattended --url https://github.com/Trophime/magnettools --name calcul24 --labels lncmi-lan --work _work`
   → verify: `gh api repos/Trophime/magnettools/actions/runners` lists
   calcul24.
4. **Maintainer** runs
   `sudo ./svc.sh install christophe.trophime@LNCMIG.local && sudo ./svc.sh start`
   → verify: `systemctl status actions.runner.*` is active and the runner
   shows as online on GitHub.
5. Add `runner-smoke.yml`: triggers on `push` to `ci/runner-smoke` and on
   `workflow_dispatch` (`workflow_dispatch` alone only works once the file
   is on the default branch), `runs-on: [self-hosted, lncmi-lan]`. It
   checks `docker buildx version`, `curl` to the euler repo URL,
   `sudo -n cowbuilder --help` and `dpkg-parsechangelog -S Version` →
   verify: after the push (**needs approval at that point**),
   `gh run watch` ends green.
6. Update `PLAN_magnettools_release_pipeline.md` → verify: maintainer
   review.

### Separate prerequisite (not in this plan)

Cowbuilder base for build jobs: `sudo DIST=trixie cowbuilder --create`.
Depends on Q3 (which euler suite the trixie base points to).

## Assumptions & open questions

- **Q1 — host.** Recommended: calcul24 (on the LAN, Docker already set up).
  Alternative: another machine (euler, a dedicated VM).
- **Q2 — runner account.** Recommended: the maintainer's own account,
  because dupload, the euler repo under `~christophe.trophime` and the SSH
  keys are tied to it. Trade-off: any workflow in `Trophime/magnettools`
  runs with Docker (root-equivalent) and those SSH keys — acceptable while
  the maintainer is the only person with write access; revisit before
  adding collaborators. Alternative: a dedicated local `ghrunner` user,
  needing its own `docker` group membership, a sudoers entry for
  cowbuilder, and an SSH key accepted on euler.
- **Q3 — `~/.pbuilderrc`.** Should trixie use the euler suite `stable` now,
  or are trixie packages still published under `testing` on euler? Decides
  how the cowbuilder base is created.
- **Q4 — runner scope.** Recommended: build and test only for now;
  `release.sh --publish` stays manual. Publishing from CI would need a token
  for `repository_dispatch` (the default `GITHUB_TOKEN` cannot trigger
  workflows in other repos) and a ghcr push setup.
