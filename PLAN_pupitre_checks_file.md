# Plan: keep the pupitre checks (tags, rules, wirings) across rebuilds

**Status (2026-11-07): approved, in progress.**

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
