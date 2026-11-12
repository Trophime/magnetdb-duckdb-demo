# Plan: operating mode with the right IH / IB channels (data issue #17)

**Status (2026-11-09): drafted, not approved.** Follow-up of phase G of
[PLAN_overview_records_from_operationaldata.md](PLAN_overview_records_from_operationaldata.md);
to run after it. Needs `approve` before any step.

## Problem

`to_duckdb` `crud.infer_operating_mode` fits IH(IB) with `Courant_GR1` as IH
and `Courant_GR2` as IB (data issue #17 in
[PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md)). That holds on
M9 only: on M8 and M10 GR1 feeds the Bitters. On M10 during the swapped
supplies (`M10-210325`, files 2021.03.25 11:52 → 2021.07.10 10:29) GR1 feeds
the insert again.

Its two callers:

- `populate._overview_mode` → `operationaldata.mode` (phase C), read by
  `_postprocess_overview_record` since phase E;
- `crud._postprocess_overview_record`, when no mode is stored, loads the
  Overview file itself → `overview_records.mode`.

## Findings (2026-11-09, read-only)

Script and per-file results: the session scratchpad (`mode17_check.py`,
`mode17.csv`, `swap_gr1_check.py`); 1409 M8/M10 Overview files of
`magnetdb-2026-11-05.duckdb`, read in 2 min on calcul24.

| Housing | Two-channel files | Same mode | Changed |
|---|---|---|---|
| M10, outside the swap | 1205 | 1181 | 24 (10 ECO→NORMAL, 14 NORMAL→ECO) |
| M10, swap period | 88 | 88 | 0 (GR1 is IH there: today's code is right) |
| M8 | 113 | 110 | 3 |

261 files have one GR channel only (NORMAL either way), 3 could not be read.
Fitted IH(IB) slope with the corrected channels (10th / 50th / 90th
percentile): M10 ECO 1.65 / 2.28 / 2.48, NORMAL 0.92 / 0.94 / 1.00; swap ECO
1.74 / 1.77 / 1.87; M8 NORMAL 0.95 / 0.97 / 0.99 (matches the 0.97 of open
question 25). Today the slopes are inverted (M10 ECO ≈ 0.44), still outside
0.66–1.5: inverting alone flips almost nothing; the 27 changes come from the
fit window (`50 A < IB < 25 % of max IB`) being taken on the wrong current.

Which DCCT pair `Courant_GR1` follows (pupitre file of the same window,
95th percentile):

| Overview | Period | `Courant_GR1` | `Courant_GR2` | Pupitre |
|---|---|---|---|---|
| `M10_Overview_210202-1546` | before swap | 29 013 A | 27 393 A | Idcct1+2 = Icoil15 (Bitters) = 29 033; Idcct3+4 = Icoil7 (insert) = 27 386 |
| `M10_Overview_210429-1509` | swap | 1 928 A | 1 069 A | Idcct1+2 = Icoil7 (insert) = 1 935; Idcct3+4 = Icoil15 = 1 064 |

So `Courant_GR1` always follows supplies A1 + A2 (Idcct1 + Idcct2), as the
`pigbrother_formula_map` says (`Référence_GR1 = Référence_A1 + Référence_A2`),
and the coil it feeds is given by the version's `pupitre_formula_map`.

**Why not override `reference_gr1_current` in `M10-210325`:**
`reference_gr*_current` is paired with `voltage_channels_gr*`,
`reference_gr*_voltage` and the hydraulics in `to_duckdb/etl_spec.py`
(`_apply_missing_types`, `_derived_insert_wirings`) and
`python_magnetrun/runetl.py` (Icoil renaming). Changing the current alone
would pair IH with the Bitters taps `Ucoil15/16`.

## Goal

`infer_operating_mode` fits the insert current against the Bitters current
on every housing and housing version, so `operationaldata.mode` and
`overview_records.mode` are right on M8 and M10, the M10 swap included.

## Files affected

| File | Action |
|---|---|
| `to_duckdb/crud.py` | edit: `infer_operating_mode(df, ih="Courant_GR1", ib="Courant_GR2")`; new `_overview_current_channels(housing, t0)`; `_postprocess_overview_record` passes the channels on its load path |
| `to_duckdb/populate.py` | edit: `_overview_mode(path, housing, verbose)`, called with the housing by `fill_operationaldata_metadata` |
| `to_duckdb/tests/test_crud.py` | edit: tests for the helper, the new keywords and the postprocess path |
| `to_duckdb/tests/test_populate.py` | edit: `fill_operationaldata_metadata` stores the mode with the right channels |
| `PLAN_digital_twin_schema.md` | edit: data issue #17 marked fixed (see open question 3) |

No change in python_magnetrun or in the housing config files.

## Approach

`_overview_current_channels(housing, t0)` returns `(ih_channel,
ib_channel)` among `Courant_GR1` / `Courant_GR2`:

1. resolve `HOUSING_CONFIGS[housing].at(t0)` (`t0` from the Overview file
   name, Paris time; base wiring before the first version);
2. supplies of each group from `pigbrother_formula_map`
   (`Référence_GR1 = Référence_A1 + Référence_A2` → {1, 2});
3. DCCTs of IH from `pupitre_formula_map["IH"]` (`IH = Idcct1 + Idcct2` →
   {1, 2});
4. the group whose supplies equal IH's DCCT numbers holds IH, the other IB;
5. otherwise (unknown housing, single circuit M5 / M7, mixed supplies such
   as `M7-140317` `IH = Idcct1 + Idcct3`): today's default
   (`Courant_GR1`, `Courant_GR2`).

Expected: M9 → (GR1, GR2); M8, M10 → (GR2, GR1); M10 during `M10-210325` →
(GR1, GR2).

Steps:

0. Baseline: `to_duckdb` suite → verify: record the count (838 passed,
   3 skipped on 2026-11-09, before phase G).
1. Tests first:
   - `_overview_current_channels` for M9, M8, M10 2022, M10 2021-04-29
     (swap), M5, M7 2014-03-20, an unknown housing;
   - `infer_operating_mode` with `ih` / `ib` keywords on a synthetic pair
     whose mode flips with the channel order (fit window on the right
     current), and the single-channel case still NORMAL;
   - `_overview_mode` / `fill_operationaldata_metadata` on an M10 file name
     store the corrected mode (patched `load_magnetdata`);
   - `_postprocess_overview_record` load path uses the channels.

   → verify: the new tests fail.
2. Implement the helper and the keywords; pass them in both callers; NumPy
   docstrings updated (`infer_operating_mode` no longer says
   "`Courant_GR1` (IH)"). → verify: step-1 tests pass; full suite = baseline
   + the new tests.
3. Real files, read-only: recompute the mode with the new code for the 27
   changed files and 50 unchanged ones (from `mode17.csv`, or a rerun of
   `mode17_check.py`). → verify: equal to the `mode_fixed` column; no change
   in the 88 swap-period files.
4. Mark data issue #17 fixed. → verify: re-read the section.
5. Stored modes (see open question 1).

Commits on a separate go-ahead.

## Assumptions and open questions

1. **Stored modes.** If the fix lands before the next build, nothing to
   recompute: the build computes `operationaldata.mode` and the
   `overview_records` rows again. For a DB already built (the calcul22
   rebuild, the DB deployed on calcul18):
   `populate operationaldata-metadata --assembly <M8 and M10 assemblies>
   --type Overview --reprocess` (re-reads the Overview files only, a few
   minutes), then the M10 rows through
   `populate overview-records-from-operationaldata --reprocess` and the M8
   rows through `overview-records-from-json --reprocess` (the stored mode is
   then used, no file read). Which DBs?
2. **DCCT n ↔ supply An.** The rule assumes `Idcct n` measures supply `An`,
   as both checked files show on M10; not checked on M8 or M9 data.
3. Data issue #17 is in a section of `PLAN_digital_twin_schema.md` that is
   uncommitted (the user's edits): mark it fixed there, or note the fix in
   this plan only?
4. **Out of scope, to record:** python_magnetrun
   `HousingConfig.get_pupitre_current_channel("Courant_GR1")` returns
   `reference_gr1_current` (IB on M10), so pigbrother ↔ pupitre current
   matching (sync / lag) pairs the wrong currents during the M10 swap
   (2021-03-25 → 2021-07-10). Same root cause; separate plan if needed.
5. The ECO / NORMAL thresholds (0.66–1.5) and the fit window are kept.
