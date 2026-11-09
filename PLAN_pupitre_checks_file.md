# Plan: keep the pupitre checks (tags, rules, wirings) across rebuilds

**Status (2026-11-07): done.** First version (`etl import` / `etl dump`,
build step `etl-config`) and
[revision 2](#revision-2-2026-11-07-simplified-model) (insert wiring derived
from the helix count, global rules) implemented; see
[Results of revision 2](#results-of-revision-2-2026-11-07).

Related:
- [PLAN_file_check_rules.md](PLAN_file_check_rules.md): tags, check rules
  and `record_tags`; step 5 (2026-11-07) defined the first M9 rules on a
  scratch copy only.
- [PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md): magnet wirings in
  `pupitre_etl_magnet`; decision D1 = a (validity windows) changes the
  wiring key later.

## Problem

Tags (`tags`), check rules (`check_rules`) and magnet wirings
(`pupitre_etl_magnet`) are entered with the CLI (`tag add`, `rule add`,
`etl set-magnet`) and live only in the DuckDB file.
`scripts/build_from_scratch.sh` rebuilds the DB from
`hifimagnet-projects/magnetdb.json/` (assemblies) and `magnet_status.json`
(statuses); nothing reloads the checks, so every rebuild starts with them
empty.

## Goal

Tags, check rules and magnet wirings live in a versioned JSON file, reloaded
by every rebuild; changes made with the CLI can be written back to it.

## Decisions (approved 2026-11-07)

| Topic | Decision |
|---|---|
| Location | `~/github/hifimagnet-projects/magnetdb.json/pupitre_checks.json`, next to `magnet_status.json`. `scripts/list_assembly_configs.sh` only lists `*_AYYMMDD_NN.json`, so the file is never taken for an assembly |
| Content | `{"kind": "pupitre-checks", "version": 1, "tags": [...], "rules": [...], "wirings": [...]}`. `tags`: `name`, `color`, `severity`, `description` (the seeded `check:channel_not_empty` is left out). `rules`: `name`, `housing` / `assembly` / `magnet`, `version` (housing version or null), `expr`, `stat`, `tol`, `unit`, `tag`, `description`. `wirings`: `assembly`, `magnet`, `housing_version`, `wiring` (`channels`, `remove`, `add`). When the D1 = a code lands, wirings get `valid_from` / `valid_to` instead of `housing_version` and the file `version` goes up |
| Commands | `magnetdb.py etl import FILE [--dry-run]`, `magnetdb.py etl dump FILE` |
| Import | All or nothing (one transaction): on an error nothing is written, a `failed` row goes to `operation_log`, exit 1. Adds or replaces what the file holds, **never deletes** rows absent from it. Goes through `add_tag` / `update_tag`, `add_rule` (after removing a rule of the same name and scope) and `set_magnet_wiring`, so the CLI validation applies. One summary row in `operation_log` per import. `--dry-run` validates and rolls back |
| Dump | Read-only; writes every tag (but the seeded one), rule and wiring, sorted, so that dump → import on an empty DB gives the same tables |
| Build | New step `etl-config` after `statuses` in `build_from_scratch.sh`; skipped with a note when the file is missing. `check_experiment_files.py --etl` stays out of the build (≈ 2 s per file × 6542 files ≈ 3.6 h; its own decision) |
| First content | The step 5 decisions of PLAN_file_check_rules.md: tags `check:current_mismatch`, `check:dcct_mismatch`; rules `IH_vs_Icoil2` (3 assembly/insert pairs), `A1_vs_A2`, `A3_vs_A4`; wirings of `M25032101` (`M9_A260602_00`, `M9_A260707_00`) and `M19071101` (`M9_A260505_00`) |

## Files affected

| File | Action |
|---|---|
| `PLAN_pupitre_checks_file.md` | create: this plan |
| `to_duckdb/etl_spec.py` | edit: `import_pupitre_checks`, `dump_pupitre_checks` |
| `to_duckdb/magnetdb.py` | edit: `etl import`, `etl dump` |
| `to_duckdb/tests/test_tags.py` | edit: import / dump tests |
| `to_duckdb/tests/test_magnetdb.py` | edit: `etl import` logged, `etl dump` read-only |
| `scripts/build_from_scratch.sh` | edit: `etl-config` step |
| `to_duckdb/README.md` | edit: ETL section |
| `ROADMAP.md` | edit: A25 row, A22 note |
| `hifimagnet-projects/magnetdb.json/pupitre_checks.json` | create (other repo; committed only after the user confirms) |

## Steps

1. Save this plan, add the ROADMAP rows → verify: links resolve; commit.
2. Tests first: dump → import on a fresh DB gives the same `tags`,
   `check_rules`, `pupitre_etl_magnet`; a second import changes nothing; one
   bad entry (unknown tag, unknown assembly, colour in use) → nothing
   written, a `failed` row, error; `--dry-run` writes nothing; rows absent
   from the file are kept → verify: they fail.
3. Implement (NumPy docstrings) → verify: new tests pass; full `to_duckdb`
   suite 755 passed + the new ones.
4. `etl dump` of the step 5 scratch copy → `pupitre_checks.json` → verify:
   the user reviews it.
5. Build step → verify: on a new scratch copy of
   `magnetdb-2026-11-05.duckdb`, `--from etl-config --to etl-config` gives
   the same `tag list`, `rule show --housing M9`, `etl show M9_A260707_00`
   as step 5; `--help` lists the step.
6. Commit in this repo → verify: `git show --stat`. The
   `hifimagnet-projects` commit only after the user's confirmation.

## Not in this plan

- Loading the file into `magnetdb-2026-11-05.duckdb` (the DB to deploy,
  F7): one `etl import` once this is done, with A22.
- A `--replace` import that makes the DB match the file exactly.

### Results of the first version (2026-11-07, uncommitted)

- Steps 2–3: `dump_pupitre_checks`, `import_pupitre_checks` (`etl_spec.py`),
  `etl import FILE [--dry-run]`, `etl dump FILE` (`magnetdb.py`); 15 new
  tests; `to_duckdb` 770 passed, 3 skipped.
- Step 4: `pupitre_checks.json` dumped from the step 5 scratch copy of
  PLAN_file_check_rules.md (2 tags, 5 rules, 3 wirings), uncommitted in
  `hifimagnet-projects` (branch `magnetgeo-1.0.0`).
- Step 5: build step `etl-config` after `statuses`; on a new copy of
  `magnetdb-2026-11-05.duckdb`, `tag list`, `rule show --housing M9` and
  `etl show M9_A260707_00` are identical to the step 5 copy. The "file
  missing → skipped" branch was not run.
- Deviations: each imported item also writes its own `operation_log` row
  (the reused functions do), then the summary row; a failed import leaves
  one `error` row. `to_duckdb/README.md` had no ETL section: one row added
  to its quick reference.

---

## Revision 2 (2026-11-07): simplified model

**Status: approved and implemented 2026-11-07.** Replaces the per-assembly wirings and
per-assembly current rules of the first version.

### Why

The insert's voltage taps follow from its helix count (magnet description
`14 Helices`, … and its helix parts in DuckDB) under the pair layout of the
digital twin plan (L2 section mapping rule 2, `Ucoil7` = outermost pair):
14 helices → `Ucoil1–7`, 12 → `Ucoil2–7`, 6 → `Ucoil5–7`. Every file checked
so far agrees (M9 `M25032101`, `M19071101`; M10 `M20092801`, `M19020601`).
Storing the wiring per assembly repeats that, and the per-assembly
`IH_vs_Icoil<n>` rules repeat the first tap. The assembly is kept only to
override the derived layout; housing-version changes (e.g. `M8-260305`:
`UB = Ucoil14`) stay in the bundled housing config.

### Decisions

| Topic | Decision |
|---|---|
| Derived insert wiring | Taps `Ucoil(8 − N/2)` … `Ucoil7` for N helices (pair layout). `remove` = the **insert group's voltage channels in the housing version at `at`** minus the taps (M8 `M8-260305`: `Ucoil14` stays for `UB`). `UH` = sum of the taps, field definition of the housing default (label `GR1` / `GR2 Voltage (UH)`). Built in `build_pupitre_etl_spec` (to_duckdb); python_magnetrun is unchanged (standalone `from_housing` keeps the housing defaults; exported spec files carry the derived wiring) |
| When it applies | An `insert` magnet without a `pupitre_etl_magnet` row for (assembly, magnet, version), with an even helix count from 2 to 14 (its helix parts); otherwise the housing defaults apply, as today |
| Overrides | An explicit row (`etl set-magnet`, file `wirings`) still wins: per-helix layout, unusual cabling of one assembly. Still keyed by housing version (D1 = b) |
| Global rules | `check_rules` rows with `housing` and `assembly_name` both NULL apply to every housing. Merge order: global < housing < assembly < magnet; at each level, version-specific over all versions. `rule add/remove/show` without `--housing` / `--assembly` act on a global rule. No schema change |
| Current rule | One global `IH_vs_Icoil7` = `p99_abs(IH - Icoil7)` ≤ 5 A → `check:current_mismatch`. `Ucoil7` is the outermost tap of every insert layout (`Icoil1` is empty for `M25032101` since 2025-05-09). Without an insert `IH` is not added: `ok: None` |
| DCCT rules | Global `A1_vs_A2` (`Idcct1 - Idcct2`) and `A3_vs_A4` (`Idcct3 - Idcct4`), `p99_abs`, tagged `check:dcct_mismatch`, with housing values for **M7, M8, M9, M10** (tolerances: open question 1). In M9 and M7 `A1_vs_A2` is the insert group, in M8 and M10 the Bitters group |
| File | Format version 1 kept (no file committed yet); `rules` entries may omit `housing` and `assembly`; `wirings` holds overrides only (the 12 current entries go if they match the derived wiring) |
| Housing versions | Stay in the bundled housing config, not in the file |

### Files affected

| File | Change |
|---|---|
| `to_duckdb/etl_spec.py` | `_derived_insert_wiring`, used in `build_pupitre_etl_spec`; global level in `add_rule`, `remove_rule`, `list_rules`, `_merged_rules`, `_rule_record`; import / dump of global rules |
| `to_duckdb/magnetdb.py` | `rule add/remove/show`: scope optional; usage lines |
| `to_duckdb/tests/test_etl_spec.py` | derived wiring tests (helix parts added to the fixture where needed) |
| `to_duckdb/tests/test_tags.py` | global rules: merge order, CLI, dump / import |
| `PLAN_pupitre_checks_file.md` | this revision, then its results |
| `PLAN_pupitre_etl_spec.md`, `PLAN_file_check_rules.md` | short notes: derived wiring (a slice of cross-plan step 3, ETL spec v2), global rule level, D1 = a revisited |
| `ROADMAP.md`, `to_duckdb/README.md` | A25 row; `rule` scope |
| `hifimagnet-projects/magnetdb.json/pupitre_checks.json` | rewritten by `etl dump` |

### Steps

1. Save this revision, ROADMAP row → verify: links resolve.
2. Tests first: derived wiring for 14 / 12 / 6 helices; `M8-260305` keeps
   `Ucoil14` and removes `Ucoil8–13`; `M8-211225` removes the rest of its
   group channels; an override row wins; no helix parts or an odd count →
   housing defaults; a global rule applies to every housing, a housing rule
   beats it, the existing merge order holds; `rule add` without a scope;
   dump / import of a global rule → verify: new tests fail, the existing 770
   pass.
3. Implement (NumPy docstrings) → verify: full `to_duckdb` suite; ruff
   reports nothing new.
4. Equivalence on the scratch copy `magnetdb-a25.duckdb`: for each of the 12
   explicit wirings (3 M9, 9 M10), the derived wiring has the same
   `channels`, `remove` (as columns) and `UH` formula → verify: 12 / 12;
   then delete those 12 rows.
5. Per-helix and cabling scan (read-only): first / middle / last file of
   each of the 47 assemblies with an insert (M10 28, M9 17, M8 1, M7 1;
   ≈ 140 files, ≈ 5 min): plugged taps vs derived taps, `Icoil7` plugged →
   verify: list of mismatches for the user to decide on overrides (known:
   `M10_A220223_00` from 2022-04-06, the stale start of `M10_A250311_00`,
   `M8_A211225_00`).
   5b. M7 measurement: untagged rules `Idcct1 - Idcct2`, `Idcct3 - Idcct4`
   (`max_abs`, `p99_abs`) and `IH - Icoil7` for M7; `--etl` on
   `M7_A140101_00` (253 files, ≈ 8 min) → verify: every experiment has
   `etl_checks`; report the distributions and a ≈ p95 proposal, **stop**
   for the M7 values (with open question 1).
6. Rules on the scratch copy: remove the measurement and per-assembly rules;
   add the global `IH_vs_Icoil7`, `A1_vs_A2`, `A3_vs_A4` with the housing
   values; `--etl` on the M7, M8, M9 and M10 assemblies in scope (≈ 610
   files, ≈ 20 min, one call per housing) → verify: channel results equal
   to those with the explicit wirings; `IH_vs_Icoil7` tags only the 16
   files of `M10_A210414_00` (plus what step 5 finds); `record_tags` = the
   failed tagged checks.
7. `etl dump` → `pupitre_checks.json` → verify: the user reviews it (tags,
   ≈ 3 rules with housing values, step 5 overrides only).
8. Notes in the ETL and rules plans, README, ROADMAP; commit in this repo
   (A25 code + this revision; only the `etl-config` hunks of
   `scripts/build_from_scratch.sh`, its `mysql_connect --utc/--no-utc`
   hunks are someone else's) → verify: `git show --stat`. The
   `hifimagnet-projects` commit waits for the user's branch choice.

### Measurements so far (2026-11-07, scratch copies only)

`p99_abs` of each file, ≈ p95 over the files of the housing. Left out:
`M10_A210414_00` and `M8_A211225_00` (data issues below).

| Housing | `A1_vs_A2` p95 / max [A] | `A3_vs_A4` p95 / max [A] | ≈ p95 proposal | Insert current rule |
|---|---|---|---|---|
| M9 (190 files) | 281 / 15001 | 35.8 / 300 | 280 / 36 (chosen for M9) | `IH - Icoil2` p99 ≤ 2.84 A |
| M10 (158 files) | 41.9 / 340 | 24.3 / 127 | 42 / 24 | `IH - Icoil5` p99 ≤ 3.0 A |
| M8 (155 files) | 41.0 / 14961 | 32.2 / 10001 | 41 / 32 | — |
| M7 | step 5b | step 5b | step 5b | step 5b |

Each ≈ p95 value tags ≈ 8 files of the housing. M9 and M8 have files with a
DCCT gap of 10–15 kA while the group current is right (single-supply or
unbalanced runs, **[unconfirmed]**).

### Data issues found (not fixed; each needs the user)

- **`M10_A210414_00` (2021-04-14 → 05-19): supplies swapped.** Insert fed by
  A1 + A2 (`Idcct1 + Idcct2` = 29 974 A = `Icoil5`), Bitters by A3 alone
  (`Idcct3` = 16 498 A = `Icoil15`, `Idcct4` = 0), while the M10 config has
  `IH = Idcct3 + Idcct4`, `IB = Idcct1 + Idcct2`. Fix: two M10 housing
  versions (swapped from 2021-04-14, base again from 2021-05-19), own plan.
  Until then 16 files fail the current and `A3_vs_A4` rules.
- **`M8_A211225_00`: supras only in the DB**, but `Idcct1` reaches 6 856 A
  and insert / Bitters taps carry signal (`ch1–7`, `11`, `12`, `15`, `16`):
  181 channel-check failures. Missing magnets in the JSON, or that supply
  and those taps served something else.
- **`M10_A220223_00` from 2022-04-06** (DB until 2022-04-22, insert
  `M19071101`, 12 helices): taps 5–7 only from `2022.04.06 - 11:42:33`
  (2–7 until `2022.04.02 - 14:22:58`), up to ≈ 27 kA; nothing changes at
  2022-04-22. A 6-helix insert from ≈ 2022-04-06 (`M10_A220422_00` →
  `M10_A220406_00`?) or `M19071101` cabled on 5–7 only: to check by the
  user. Taps show the cabling, not the magnet (Bitters-only
  `M10_A241209_00` has taps 2–7 plugged).
- **`M10_A250311_00` 2025-03-13 → 03-15 16:02** (8 files, ≤ 500 A): taps 2–7
  still plugged from an earlier set-up, re-cabled to 5–7 at 16:50, three
  minutes before the first powered run. The channel check tags them
  (`ch2–4`), as intended.

### Open questions

1. DCCT tolerances: ≈ p95 per housing (table above), the M9 values
   everywhere, or one global value?
2. Rule names `A1_vs_A2` / `A3_vs_A4` (DCCT numbers): keep?
3. `hifimagnet-projects` branch for the file (currently `magnetgeo-1.0.0`).

### Not in this revision

- The M10 housing versions for the 2021 supply swap; the 2022-04 assembly
  boundary; the `M8_A211225_00` question (data issues above).
- D1 = a code (wiring validity windows): revisited after this revision.
- PLAN_file_check_rules.md step 6 (dashboard tag colours) and the rest of
  step 7 (docs).
- `check_experiment_files.py --etl` over the whole DB (≈ 3.6 h) and loading
  the checks into the DB deployed in F7 (A22).
- A Bitters current rule (`IB - Icoil15`, housing-version dependent in M8).
- Section mapping of `M25032101` since 2025-05-09 (digital twin, data issue
  #12).

### Results of revision 2 (2026-11-07)

Checked on scratch copies of the reference DB `magnetdb-2026-11-05.duckdb`;
the repo DBs were not written.

| Step | Result |
|---|---|
| 2–3 | Tests first (12 failed), then `_derived_insert_wirings` in `build_pupitre_etl_spec`, a global rule level (`rule add/remove/show` without a scope, shown as `* (all housings)`; a global rule cannot be restricted to a housing version), dump / import of global rules. `to_duckdb` 785 passed, 3 skipped; ruff: nothing new |
| 4 | 10 of the 12 explicit wirings equal the derived ones. The other 2 are `M25032101` (`Ucoil2–7` set by hand because `Ucoil1` is empty since 2025-05-09; derived `Ucoil1–7`): dropped by the user, the empty tap adds 0 to `UH`. The plan's "12 / 12" expectation was wrong |
| 5 | Scan of 46 assemblies with an insert (first / middle / last file): no per-helix layout, `Ucoil7` plugged everywhere. 31 sampled files differ from the derived taps: empty taps (harmless, e.g. `Ucoil1` of several 14-helix inserts) or stale cabling at an assembly start (tagged by the channel check). **No override needed** |
| 5b | M7 (253 files): measurements, and the insert fed by A1 + A3 in 2014 (data issue #13 of the digital twin plan) |
| — | Housing versions `M7-140317`, `M7-160726`, `M10-210325`, `M10-210929` added to the bundled configs (python_magnetrun `69f6c49`, superproject `4774ec2`), approved separately |
| 6 | Final rules, `--etl` on 969 files (M7, M8, M9, M10): `record_tags` = the 398 failed tagged checks; channel results identical to the explicit-wiring runs except the expected ones (`M8_A230919_00` now checks its empty `Ucoil8–14`, `M25032101` keeps `Ucoil1` as a tap). `IH_vs_Icoil7` tags only 19 M7 files (16 with a 5.7–7.2 A offset under `M7-140317`, kept at 5 A by the user, and 3 isolated 2016 files) |
| 7 | `pupitre_checks.json`: 2 tags, 11 rules, no wirings; dump → import → dump identical |

Final rules (`p99_abs`, unit A):

| Rule | Global | M7 | M7 @ `M7-140317` | M8 | M10 |
|---|---|---|---|---|---|
| `IH_vs_Icoil7` = `IH - Icoil7` → `check:current_mismatch` | 5 | — | — | — | — |
| `A1_vs_A2` → `check:dcct_mismatch` | 280 (`Idcct1 - Idcct2`) | 82 | 82 (`Idcct1 - Idcct3`, the pair in service) | 41 | 42 |
| `A3_vs_A4` → `check:dcct_mismatch` | 36 (`Idcct3 - Idcct4`) | 5 | 5 (`Idcct2 - Idcct4`, both unused) | 32 | 24 |

Notes:
- The file names housing version `M7-140317`: importing it into a DB
  without the new versions fails as a whole; run `housing sync` first on
  an existing DB (a rebuild loads them from the bundled configs).
- Overrides are keyed by housing version (D1 = b). After a version that
  returns to the base wiring, later files resolve to that new version
  (M10 after 2021-09-29: `M10-210929`, not `M10-180220`).
- A "disabled rule" mechanism was considered for `M7-140317` and set
  aside (one case; version-specific rules with the pairs in service keep a
  meaningful check).
