# Plan: MAINTENANCE codes in `LNCMI Tech Staff`, applied by the build

Status: plan approved for saving (2026-11-03); implementation awaiting approval.

## Goal

The `LNCMI Tech Staff` research area covers `EXPLOIT.`, any acronym
containing "test", and the MAINTENANCE codes. The build sets it as the last
operation on `users`. Any run that rewrites `users` without setting the tag
again ends with a warning giving the command to run.

## Context

- The group is defined in `demos/find_research_area_candidates.py`
  (`TECH_STAFF_RESEARCH_AREA = "LNCMI Tech Staff"`), rule
  `(acronym = 'EXPLOIT.' OR acronym ILIKE '%test%')`. It only writes with
  `--apply-tech-staff` and is not called by `scripts/build_from_scratch.sh`,
  so no local DB has the tag yet.
- `EXPERIENCES_LOG.csv` has two MAINTENANCE sessions (`MAINTENANCE` on M10i,
  `MAINTENABCE` on M10e, both 2017-11-24).
- `demos/users_table_demo.py` loses the tag in two modes: the default mode
  deletes and re-inserts the rows (`replace_all_users`), and `--sync` compares
  `research_area` (`_USER_COMPARE_FIELDS`), so it resets tagged rows to NULL.
  `--link-only` and `--view` don't touch `research_area`.

## Decisions

- **Placement:** `tech-staff` is the last operation on `users`. It runs after
  `export`, `users`, `link-users`, `unlinked-users`, which makes it the
  build's last step.
- **Matching:** add `acronym ILIKE 'mainten%'`, which ignores case and
  catches the typo `MAINTENABCE`.
- **Warning:** printed in both `build_from_scratch.sh` and
  `demos/users_table_demo.py`.
- Only `LNCMI Tech Staff` is kept: no separate "Maintenance" research area.

## Files affected

| File | Action | Change |
|---|---|---|
| `to_duckdb/tests/test_find_research_area_candidates.py` | create | Tests for the group rule |
| `to_duckdb/tests/test_users_table_demo.py` | edit | Test for the new warning |
| `to_duckdb/demos/find_research_area_candidates.py` | edit | Add MAINTENANCE to the rule (`_is_tech_staff_acronym_sql`); update the texts listing the members: module docstring, `fetch_tech_staff_rows` docstring, `--apply-tech-staff` help, printed label |
| `to_duckdb/demos/users_table_demo.py` | edit | Private helper `_print_tech_staff_reminder(db, proposals)`, called in `main()` after the replace/sync writes |
| `scripts/build_from_scratch.sh` | edit | `tech-staff` in `STEPS`, its `section` call after `unlinked-users`, the warning before the final failure check |
| `to_duckdb/demos/README.md` | edit | Update the Tech Staff bullet; document the build step and the warnings |

## Steps

1. Write the rule tests first, on an in-memory `users` table with these rows:
   `EXPLOIT.`, `TEST`, `M10 TEST`, `MAINTENANCE`, `MAINTENABCE`,
   `maintenance`, a normal acronym, and a `MAINTENANCE` row that already has a
   research area.
   → verify: they fail before the rule change.
2. Extend the rule and update the texts.
   → verify: the new tests pass and the full `to_duckdb` suite still passes.
   `fetch_tech_staff_rows` returns the MAINTENANCE codes; `apply_tech_staff`
   tags them and leaves the normal acronym and the already-tagged row
   unchanged.
3. Write the warning test first: `_print_tech_staff_reminder` prints a warning
   plus a `find_research_area_candidates.py --apply-tech-staff --db <db>
   --proposals <proposals>` command (checked with `capsys`). Then add the
   helper and its call. The script path in the command comes from
   `Path(__file__).with_name(...)`, so it works from any directory.
   → verify: the test fails first, then passes.
4. Add the build step:

   ```bash
   # Tag internal LNCMI sessions (EXPLOIT., *test*, MAINTENANCE) as research_area 'LNCMI Tech Staff'
   section tech-staff "Tag LNCMI Tech Staff users" \
       python demos/find_research_area_candidates.py --apply-tech-staff --db $DB \
           --proposals $DATA_DIR/proposals.csv
   ```

   `--proposals` is needed because the build runs from `to_duckdb/` and the
   script's default path is relative to the repo root. The candidate-search
   report the script also prints goes to `$DB.log`.
   → verify: `bash -n` passes and `--help` lists `tech-staff`. On a scratchpad
   copy of `magnetdb-2026-10-08.duckdb`, `--from tech-staff --to tech-staff`
   prints OK, and the copy then has 932 rows (13 acronyms) with
   `LNCMI Tech Staff`.
5. Add the build warning:

   ```bash
   # rebuilding users drops the 'LNCMI Tech Staff' tag: tell the caller how to set it again
   if wanted users && ! wanted tech-staff; then
       echo -e "\033[33mWarning:\033[0m the users table was rebuilt without the tech-staff step;" \
               "research_area 'LNCMI Tech Staff' is not set. Run:"
       echo "  scripts/build_from_scratch.sh --from tech-staff --db $DB"
   fi
   ```

   → verify, on the scratchpad copy: `--from users --to users` ends with the
   warning (the demo's own warning goes to `$DB.log`); running the printed
   command restores the 932 rows; `--from users` (through `tech-staff`) shows
   no build warning. The original DB is not touched.
6. Update the README.
   → verify: read it back.

## Assumptions

- No effect on current data: the build's `users` step uses
  `--from 2018-01-01`, and the MAINTENANCE sessions date from 2017. The cutoff
  is not changed.
- Nothing is committed.
