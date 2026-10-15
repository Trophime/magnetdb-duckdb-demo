# Plan: self-hosted GitHub runner on calcul22 (part 1 of 3)

Status: **draft — not approved**. Part 1 of the Debian CI series:

1. this plan — runner on calcul22, registered on `MagnetDB/apt-depot`;
2. [PLAN_apt_ci_upload.md](PLAN_apt_ci_upload.md) — `apt-ci` upload path
   on euler and the generic build workflow in `apt-depot`;
3. [PLAN_freesteam_deb_ci.md](PLAN_freesteam_deb_ci.md) — first public
   source repo (`Trophime/freesteam`) wired to the builder.

Prerequisite for
[PLAN_magnettools_release_pipeline.md](PLAN_magnettools_release_pipeline.md),
which currently records "no self-hosted runner for now" (revised by step 9).

## Goal

A persistent self-hosted runner on calcul22, running as a dedicated local
`ghrunner` user, registered **only** on `MagnetDB/apt-depot` (private) with
labels `self-hosted, linux, x64, lncmi-lan`, running as a systemd service,
and proven by one green smoke workflow.

## Decisions (2026-10-13)

| Topic | Decision |
|---|---|
| Host | **calcul22** instead of calcul24: Debian trixie host, trixie cowbuilder base already present, `~/.pbuilderrc` already maps trixie → `stable` |
| Builder repo | **`MagnetDB/apt-depot`** (private) holds the runner and every workflow that runs on it. Public source repos never get the runner; they request a build (part 3) |
| Trigger | Public repo: `on: release: types: [published]` on a GitHub-hosted runner → calls `workflow_dispatch` on `apt-depot` with inputs `repo`, `tag` (token needs only *Actions: write*, not *Contents: write*) |
| Runner account | Dedicated **`ghrunner`** local user (former Q2, settled): the `apt-depot` CI workflow writes `~/.ssh/config` and `~/.dupload.conf`, which must not touch the maintainer's own |
| Public repo rule | The runner is **never** registered on a public repo. If `apt-depot` ever becomes public, remove the runner first |
| Upload path | Option (a) in part 2: one `apt-ci` deploy key, `ci-post-upload.sh` dispatches on `$SSH_ORIGINAL_COMMAND` |

## Findings (calcul22, 2026-10-13)

| Item | Value |
|---|---|
| OS / resources | Debian 13 trixie, x86_64, 40 cores, 62 GB RAM; shared machine (4 users logged in) |
| Disk | `/home` 94 % full (119 GB free) → runner home and `_work` go under `/srv` on `/` (59 %, 357 GB free; Docker root also there) |
| Cowbuilder bases | `/var/cache/pbuilder/trixie-amd64/base.cow` (updated 2026-10-12), `forky-amd64`, `trixie-arm64`, bookworm, noble, resolute, … |
| `~/.pbuilderrc` | `STABLE_CODENAME="trixie"`, `TESTING_CODENAME="forky"` → euler suite `stable` for trixie (former Q3, settled) |
| Docker | 29.9 + buildx 0.38 |
| Network | `api.github.com` 200, `ghcr.io` reachable, euler repo URL 200, no proxy |
| `gh` CLI | installed, **not logged in** |
| Passwordless sudo (maintainer) | `pbuilder`, `cowbuilder`, `singularity`, `lshw`; everything else needs the password |
| Old runner | `~/actions-runner/actions-runner/`: unconfigured runner 2.311.0 (2023), too old to register |
| `MagnetDB` | GitHub **organization**; `MagnetDB/apt-depot` returns 404 anonymously → private (to confirm with `gh` in step 3) |
| `Trophime/freesteam` | public, not a fork, default branch `main`, in-tree `debian/`, no workflows yet |

## Files affected

| Path | Action |
|---|---|
| `/srv/ghrunner/` (calcul22) | create: `ghrunner` home (**maintainer, sudo**) |
| `/etc/sudoers.d/ghrunner` | create (**maintainer, sudo**) |
| `/srv/ghrunner/actions-runner/` | create: runner binaries and config |
| `/etc/systemd/system/actions.runner.MagnetDB-apt-depot.calcul22.service` | create, via `svc.sh` (**maintainer, sudo**) |
| `~/actions-runner` → `~/actions-runner.old-2023` | rename |
| `../apt-depot/.github/workflows/runner-smoke.yml` | create, on a new branch `ci/runner-smoke` |
| `PLAN_magnettools_release_pipeline.md` | edit: replace the "no self-hosted runner" row, mark A2 true on calcul22, link this series |

## Steps

1. **Maintainer** creates the user:
   `sudo adduser --system --group --home /srv/ghrunner --shell /bin/bash ghrunner`
   → verify: `id ghrunner`; `ls -ld /srv/ghrunner` owned by `ghrunner`.
2. **Maintainer** creates `/etc/sudoers.d/ghrunner` (mode 0440):
   `ghrunner ALL=(root) SETENV: NOPASSWD: /usr/sbin/cowbuilder, /usr/sbin/pbuilder`
   → verify: `sudo visudo -c` passes; `sudo -u ghrunner sudo -n -l` lists
   only those two commands.
3. **Maintainer** runs `gh auth login` (scopes `repo`, `workflow`; account
   with admin on `MagnetDB/apt-depot`) → verify: `gh auth status`;
   `gh repo view MagnetDB/apt-depot --json visibility` shows `PRIVATE`.
4. As `ghrunner`, download the latest `actions/runner` linux-x64 release into
   `/srv/ghrunner/actions-runner` → verify: its sha256 matches the one in the
   release notes.
5. Register: get a token with
   `gh api -X POST repos/MagnetDB/apt-depot/actions/runners/registration-token`,
   then as `ghrunner`:
   `./config.sh --unattended --url https://github.com/MagnetDB/apt-depot --name calcul22 --labels lncmi-lan --work _work --token <token>`
   → verify: `gh api repos/MagnetDB/apt-depot/actions/runners` lists calcul22.
6. **Maintainer** runs, in `/srv/ghrunner/actions-runner`:
   `sudo ./svc.sh install ghrunner && sudo ./svc.sh start`
   → verify: `systemctl status actions.runner.*` is active and the runner is
   online on GitHub.
7. Rename `~/actions-runner` to `~/actions-runner.old-2023` → verify: `ls`;
   delete later once the new runner is proven.
8. Add `runner-smoke.yml` to `apt-depot` on branch `ci/runner-smoke`:
   triggers on `push` to that branch and `workflow_dispatch`,
   `runs-on: [self-hosted, lncmi-lan]`. It checks:
   - `id -un` is `ghrunner`;
   - `sudo -n /usr/sbin/cowbuilder --help` succeeds;
   - `/var/cache/pbuilder/trixie-amd64/base.cow` exists;
   - `curl -fsS` to the euler repo URL succeeds;
   - **negative checks**: no `~/.ssh/id_*` files, and
     `ssh -o BatchMode=yes euler.lncmig.local true` fails.

   → verify: after the push (**needs approval at that point**),
   `gh run watch` ends green.
9. Update `PLAN_magnettools_release_pipeline.md` → verify: maintainer review.

## Assumptions & open questions

- **Docker.** `ghrunner` is **not** added to the `docker` group: Debian
  builds go through cowbuilder. Add it if magnettools image builds move to
  CI.
- **Isolation limit.** Passwordless `sudo cowbuilder` with `SETENV` is
  root-equivalent in practice. `ghrunner` separates *credentials* (the
  maintainer's SSH keys, GPG keys, dupload config), not root. The actual
  protection is that only trusted code reaches the runner: private builder
  repo, release-only trigger, allow-list and tag checks (part 2).
- **Shared cowbuilder bases.** `base.cow` is shared with the maintainer's
  manual builds; a `cowbuilder --update` during a CI build could clash.
  Acceptable for now; revisit if CI volume grows.
- **Shared machine load.** Default runner = one job at a time. If builds
  disturb interactive users, add `Nice=` / `CPUQuota=` via a systemd
  drop-in.
- **`.pbuilderrc` for `ghrunner`.** How cowbuilder picks up a config under
  `sudo` (root's `HOME` vs `ghrunner`'s) is handled in part 2, where real
  builds start.
