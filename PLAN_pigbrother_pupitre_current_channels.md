# Plan: explicit pigbrother → pupitre current map (python_magnetrun)

**Status (2026-11-12): done, committed (python_magnetrun + submodule bump),
not pushed.** Out-of-scope question 5 of
[PLAN_overview_mode_gr_mapping.md](PLAN_overview_mode_gr_mapping.md) (data
issue #17), done first so that #17 can reuse it (plan B there).

## Problem

`HousingConfig.get_pupitre_current_channel("Courant_GR1")` and
`get_pupitre_channel("Référence_GR1")` return the fixed
`reference_gr1_current` (`IB` on M10 and M8, `IH` on M9 and M7).
`Courant_GR1` / `Référence_GR1` is always supplies A1 + A2
(`pigbrother_formula_map`: `Référence_GR1 = Référence_A1 + Référence_A2`).
During `M10-210325` (2021-03-25 09:50 → 2021-09-29 08:00), A1 + A2 feed the
insert (`IH = Idcct1 + Idcct2` in that version), but `reference_gr1_current`
stays `IB`. So `analysis/processing.py` `_compute_lag_correlation` correlates
`Courant_GR1` (insert) with pupitre `IB` (Bitters), and the reverse for GR2;
the result goes into `record.sync_info["lag_Courant_GR*"]`. 94 M10 Overview
files fall in the swap period. Loading (`processing.py` `_load_pupitre_data`)
is not affected: it adds both IH and IB anyway.

**Why not override `reference_gr1_current` in `M10-210325`, or add a version
parameter:** callers already resolve the version (`processing.py`
`HOUSING_CONFIGS[housing].at(t0)`), and the resolved version still says `IB`.
In the housing config "gr1" is the magnet role: `reference_gr1_current`,
`voltage_channels_gr1` and the hydraulics all describe the Bitters on M10, and
are paired in `runetl.py` / `to_duckdb/etl_spec.py`. The swap changed which
supplies feed which magnet, not the taps or the cooling circuit.

## Decision (user, 2026-11-12)

An explicit map in the version rather than a rule derived from the formulas:
new optional field `pigbrother_current_map` (keys `"GR1"` / `"GR2"`, value a
pupitre current), set only in the `M10-210325` override. `.at(t0)` already
applies any dataclass field listed in `overrides` (whole-value replace), so
no version code changes. Trade-off: it repeats what the formulas say; a
future swap version needs the entry by hand. Today only `M10-210325` needs
it (`M7-140317` has a single circuit).

## Files affected

| File | Action |
|---|---|
| `python_magnetrun/python_magnetrun/housing_config.py` | edit: field `pigbrother_current_map: dict` (empty by default); `get_pupitre_current_channel` (`Courant_GRn`) and `get_pupitre_channel` (`Référence_GRn`) read `map["GRn"]` first, else `reference_grn_current`; NumPy docstrings |
| `python_magnetrun/python_magnetrun/M10-housing-config.json` | edit: `M10-210325` overrides gain `"pigbrother_current_map": {"GR1": "IH", "GR2": "IB"}` |
| `python_magnetrun/tests/test_housing_config.py` | edit: tests |
| `PLAN_pigbrother_pupitre_current_channels.md` | create: this plan |

Not changed: `ROLE_TO_FIELD` (role-name CLI of `update_housing_config_json`),
`runetl.py`, the voltage / hydraulic pairing.

## Steps

1. Save this plan. → verify: the file exists.
2. Baseline: python_magnetrun suite with `-o addopts=""`. → verify: record the
   counts (known Git LFS failures).
3. Tests first: M10 at 2021-04-29 (`.at()`) → GR1 `IH`, GR2 `IB` through both
   methods; M10 at 2022-01-15 and 2021-10-01 (after `M10-210929`) → GR1 `IB`;
   M9, M8, M7 2014-03-20 unchanged; unknown key → `None` / `""`; bundled M10
   JSON loads and `to_dict` round-trips the field. → verify: the new tests
   fail.
4. Implement the field and the two lookups, then the M10 JSON. → verify: the
   new tests pass; suite = baseline + the new tests.
5. Commit (python_magnetrun) on a separate go-ahead, with plan B of #17.

## Results (2026-11-12, calcul24)

- Step 2 baseline: 1466 passed, 19 skipped, 10 failed, 24 errors (all in the
  Git LFS data tests `test_magnetdata.py`, `test_magnetdata_polars.py`,
  `test-plateau.py`).
- Step 3: 11 new tests in `TestPigbrotherCurrentMap`; 4 failed before the
  change (the M10 swap case and the three map tests), 7 passed (the cases
  that must not change).
- Step 4: private `_group_current(group)` shared by both lookups; M10 JSON
  valid. `test_housing_config.py` 64 passed; full suite 1477 passed, 19
  skipped, same 10 failed / 24 errors as the baseline. `to_duckdb` suite
  unchanged: 838 passed, 3 skipped.
- A DB built before this change keeps `M10-210325` without the map in
  `housing_config_versions`; `housing sync` reports it and does not overwrite
  it. Nothing reads the map from the DB.
