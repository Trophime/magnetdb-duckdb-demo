# Plan: freesteam Debian package on release (part 3 of 3)

Status: **draft — not approved**. Depends on
[PLAN_github_runner_setup.md](PLAN_github_runner_setup.md) (part 1) and
[PLAN_apt_ci_upload.md](PLAN_apt_ci_upload.md) (part 2).

## Goal

Publishing a GitHub Release on `Trophime/freesteam` (public) triggers, via
`workflow_dispatch` on `MagnetDB/apt-depot`, a cowbuilder build on calcul22
and an upload of the resulting packages to the LNCMI apt depot — with no
code from the public repo deciding what runs on calcul22.

## Findings (2026-10-13)

- `Trophime/freesteam`: public, not a fork, default branch `main` (also
  `modernize-cmake-build`), no `.github/workflows`.
- In-tree `debian/`: `changelog`, `compat`, `control`, `rules`, `patches/`,
  `source/`, `watch`, and `.install` files including
  `python-freesteam.install` (Python 2 era) and `freesteam-ascend.install`
  → packaging may be dated for trixie.
- `Trophime/freesteam` is under the personal account, `apt-depot` under the
  `MagnetDB` org → the dispatch token cannot be an org secret here; it is a
  freesteam repo secret.

## `on: release` — what it implies

- Use `on: release: types: [published]`; other types (`created`, `edited`,
  `deleted`, …) would trigger extra runs.
- Fires on publishing a Release (UI, `gh release create`, API); **not** on a
  bare tag push nor on saving a draft.
- Pre-releases also fire `published`; filter with
  `if: ${{ !github.event.release.prerelease }}` unless part 2 decides to
  build them into `testing`.
- The workflow file is read from the tagged commit → only releases created
  after the workflow is committed can trigger it.
- A Release created by another workflow using the default `GITHUB_TOKEN`
  does not trigger `on: release`.
- Only users with write access can publish a Release; forks cannot.
- A Release can create its tag on any branch (`target_commitish`) → the
  reachability check in part 2 stays necessary.
- Deleting and re-publishing a Release fires again → part 2 refuses an
  already-published version.
- Payload: `github.event.release.tag_name`, `github.event.release.prerelease`.

## Files affected (to be detailed when this plan is promoted)

| Path | Action |
|---|---|
| `freesteam/debian/*` | edit as needed after the local build test |
| `freesteam/.github/workflows/deb-release.yml` | create |
| `freesteam` repo secret `APT_DEPOT_DISPATCH_TOKEN` | create (maintainer) |
| `../apt-depot` allow-list | edit: add `Trophime/freesteam` |

## Approach (outline)

1. **Local build first.** On calcul22, as the maintainer:
   `./distro.sh build`-equivalent without upload (`pdebuild` into the
   `trixie-amd64` base) from a clean freesteam checkout → verify: `.deb`
   files produced, `lintian` reviewed. Fix `debian/` (compat level, Python 3
   only, drop obsolete binary packages) on a branch, merged to `main` before
   the first release.
2. **Token.** Fine-grained PAT, resource owner `MagnetDB` (org must allow
   fine-grained PATs), repository `apt-depot` only, permission
   **Actions: write** only, expiry set; stored as `APT_DEPOT_DISPATCH_TOKEN`
   in freesteam secrets → verify: `gh workflow run` with it succeeds; a
   `git push` to `apt-depot` with it is refused.
3. **`deb-release.yml`.** `on: release: types: [published]`,
   `runs-on: ubuntu-latest`, `permissions: {}`, pre-release filter; one step:
   `gh workflow run build-deb.yml -R MagnetDB/apt-depot -f repo=Trophime/freesteam -f tag=${{ github.event.release.tag_name }}`
   with `GH_TOKEN` from the secret → verify: run appears in `apt-depot`.
4. **Allow-list.** Add `Trophime/freesteam` in `apt-depot` → verify:
   dispatch for a non-listed repo still fails.
5. **First release.** Publish a release on freesteam → verify: green run in
   freesteam and in `apt-depot`; `apt-cache policy libfreesteam1` on a
   client shows the new version from euler.

## Assumptions & open questions

- **Tag/version format** used by freesteam (`v2.1`? `2.1`?) and how it maps
  to `debian/changelog` (part 2 rule).
- **Which branch** carries the packaging fixes (`main` vs
  `modernize-cmake-build`).
- **Token rotation**: expiry date and reminder, same as the CI signing
  subkey rotation in `apt-depot`.
