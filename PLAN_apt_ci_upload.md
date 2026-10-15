# Plan: `apt-ci` upload path and build workflow (part 2 of 3)

Status: **draft — not approved**. Depends on
[PLAN_github_runner_setup.md](PLAN_github_runner_setup.md) (part 1: runner
`calcul22` as `ghrunner` on `MagnetDB/apt-depot`). Followed by
[PLAN_freesteam_deb_ci.md](PLAN_freesteam_deb_ci.md) (part 3).

## Goal

A release of an allow-listed source repo, requested through
`workflow_dispatch` on `MagnetDB/apt-depot`, is built in the trixie
cowbuilder on calcul22 and uploaded to euler as `apt-ci`; euler rebuilds and
signs the index with the CI subkey. No maintainer credential is used.

## Findings (2026-10-13, from `../apt-depot`)

- README "CI — GitHub Actions (private runner)" already designs: `apt-ci`
  system user on euler with ACL write on `*_pool` and `dists/*`, a deploy
  key restricted by `command="…/ci-post-upload.sh",no-pty,no-port-forwarding`,
  a CI signing subkey in `apt-ci`'s keyring, secrets `APT_DEPLOY_KEY` /
  `APT_SIGNING_KEY`, variables `APT_SERVER` / `APT_SIGNING_SUBKEY_FPR`.
- **Forced command breaks uploads**: dupload uses `scpb`; with `command=`
  forced, the remote `scp -t …` is replaced by `ci-post-upload.sh`.
- **Hardcoded login**: every `euler_<dist>` stanza in `.dupload.conf` sets
  `login => "christophe.trophime\@LNCMIG.local"`, and its `postupload` hook
  runs `ssh christophe.trophime\@LNCMIG.local\@euler… 'apt-ftparchive …;
  gpg -u <maintainer key> …'`. `dupload.conf(5)`: for scp/scpb/rsync, when
  `login` is omitted "the default is delegated to SSH and its own
  configuration".
- README asks to add the runner user to the **`sudo` group** — too broad;
  part 1 uses a sudoers entry limited to pbuilder/cowbuilder.
- README workflow **imports `APT_SIGNING_KEY` on the runner**, but signing
  happens on euler in `ci-post-upload.sh` → not needed on the runner.
- README workflow builds with `dpkg-buildpackage` **on the host**;
  `distro_tools.sh:build_package` uses `pdebuild` + cowbuilder.
- README label `lncmi` vs part 1 label `lncmi-lan`.

## Files affected (to be detailed when this plan is promoted)

| Path | Action |
|---|---|
| euler: `~/public_html/debian/scripts/ci-post-upload.sh` | edit: dispatch on `$SSH_ORIGINAL_COMMAND` (option a) |
| euler: `/home/apt-ci/.ssh/authorized_keys` | create/edit: deploy key with `command=` restriction |
| `../apt-depot/.dupload.conf` | edit: drop `login`, `postupload` → host alias |
| `../apt-depot/distro_tools.sh` | edit: `create_dupload_entry` generates the same shape |
| `../apt-depot/README.md` | edit: CI section (sudoers, no signing key on runner, cowbuilder build, `lncmi-lan`, option a) |
| `../apt-depot/.github/workflows/build-deb.yml` | create |
| `../apt-depot/ci/allowed-repos.txt` (name TBD) | create: allow-list |
| maintainer `~/.dupload.conf`, `~/.ssh/config` | edit: host alias with maintainer `User` |

## Approach (outline)

1. **`ci-post-upload.sh`, option (a).** One deploy key; the script reads
   `$SSH_ORIGINAL_COMMAND` and allows only:
   - `scp -t <REPO>/<dist>_pool/main` (also the `-d`/`-p` variants dupload
     sends) for an allowed `<dist>` → `exec` it;
   - `update <dist>` → `apt-ftparchive generate/release` + sign with the CI
     subkey (current script body);
   - anything else → refuse with exit 1.

   → verify: from calcul22 as `ghrunner` with the deploy key, an upload of a
   dummy file to the pool works; `ssh … whoami` and `scp -t /tmp` are refused.
2. **`.dupload.conf`.** Remove `login`; `postupload` runs
   `ssh euler-apt update <dist>` (host alias). Maintainer `~/.ssh/config`:
   `Host euler-apt` → `User christophe.trophime@LNCMIG.local` and a remote
   command path that still works interactively (TBD: keep the current inline
   script for the maintainer via a second alias, or install a small
   `update` wrapper on euler usable by both accounts).
   → verify: maintainer `distro.sh build trixie` still uploads and re-signs.
3. **`build-deb.yml` in `apt-depot`.** `on: workflow_dispatch` with inputs
   `repo` (owner/name), `tag`; `runs-on: [self-hosted, lncmi-lan]`;
   `concurrency` per repo. Steps:
   1. `repo` is in the allow-list, else fail;
   2. clone `https://github.com/<repo>`; `tag` exists as `refs/tags/<tag>`;
      its commit is reachable from `origin/<default branch>`
      (`git merge-base --is-ancestor`);
   3. `dpkg-parsechangelog -S Version` upstream part matches `tag`
      (rule for the `v` prefix TBD);
   4. version not already in `<dist>_pool/main` (query euler index over
      HTTP);
   5. write `~ghrunner/.ssh/config` (`Host euler-apt`, `User apt-ci`,
      `IdentityFile` from `APT_DEPLOY_KEY`), `known_hosts` pinned (not
      `ssh-keyscan` at run time), `~ghrunner/.dupload.conf` from the repo;
   6. `build_package trixie amd64` (cowbuilder) → dupload → `postupload`.

   → verify: dispatch on a known-good package/tag ends green and the package
   appears in `apt-cache policy` on a client.
4. **README** updated to match → verify: maintainer review.

## Assumptions & open questions

- **Pre-releases**: skip them (filter in part 3), or build them into a
  `testing` suite?
- **Known hosts**: commit euler's host key fingerprint to `apt-depot` rather
  than trusting `ssh-keyscan` on each run.
- **arm64**: `trixie-arm64` base exists on calcul22 (qemu); build both
  arches per release, or amd64 only at first?
- **Secret scope**: `APT_DEPLOY_KEY` as an `apt-depot` repo secret (only
  workflows in `apt-depot` can read it); `APT_SIGNING_KEY` not stored in
  GitHub at all if signing stays on euler.
- **Version-tag mapping**: freesteam and future repos may tag `v2.1`,
  `2.1`, or `release-2.1`; the matching rule may need a per-repo entry in
  the allow-list.
