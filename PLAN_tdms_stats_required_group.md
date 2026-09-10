# Plan — type-dependent `required_group` in `TdmsReader`

Status: **proposed, not yet approved** (2026-09-10).

Context: `python_magnetrun` is introducing support for a new pigbrother TDMS
acquisition mode, "Stats" (example file:
`~/LNCMIG-Data/records/pbsurv/M9/Fichiers_stats/M9_Stats_260909-100205.tdms`).
Its groups/channels (`THD`, `U_HT1_RH`, `I_HT1_RH`, `I_HT2_RH`, `D`, `S`,
`Q1`, `P1`, `HT_frequence`, `U1rms`, `I1rms`, `cos_phi`, `Stats_moy`,
`Stats_sigma`, `Stats_lowf`, `Stats_midf`, `Stats_highf`) differ from
Overview/Archive/Default files and do **not** include `Courants_Alimentations`
— the group `TdmsReader.required_group` currently hardcodes as mandatory for
every TDMS file. Loading a Stats file today would fail that check.

Investigation established:
- No per-type defs.json is needed. `pigbrother-defs.json` is already shared
  across all TDMS acquisition modes (it's a format-level file, not a
  per-mode one) — new Stats `Group/Channel` entries get added there, not to
  a new file.
- `required_group` is TDMS-specific (lives on `TdmsReader`, checked against
  nptdms `Groups`) — it does not extend to Pupitre, which is a different
  format/reader (`PupitreReader`) with its own, separate Date/Time header
  check (`utils/validation.py:29-58`).
- `TdmsReader` already has an established pattern for exactly this kind of
  per-mode variation: `t_offsets: dict[str, float]` +
  `t_offset_for(filename)` (substring match on filename, `readers/tdms_reader.py:29-52`).
  The fix mirrors that pattern rather than inventing a new mechanism.

## Goal

`TdmsReader.required_group_for(filename)` returns the correct required TDMS
group per acquisition mode (`"THD"` for Stats files, `"Courants_Alimentations"`
for everything else), and `_fromtdms` uses it instead of the current single
hardcoded group.

## Files affected

1. `python_magnetrun/python_magnetrun/readers/tdms_reader.py` — edit
2. `python_magnetrun/python_magnetrun/magnetdata.py` — edit (lines ~175–178)
3. `python_magnetrun/tests/readers/test_tdms_reader.py` — edit

## Approach (test-first — this adds validation behavior)

1. Add tests to `test_tdms_reader.py`:
   - `test_required_groups_present`: `"Stats" in reader.required_groups`
   - `test_required_group_for_stats`:
     `reader.required_group_for("M9_Stats_260909-100205.tdms") == "THD"`
   - `test_required_group_for_unknown_file`:
     `reader.required_group_for("run_normal_2025.tdms") == "Courants_Alimentations"`
   - Leave existing `test_required_group` untouched (fallback attribute name
     and value don't change).
   → verify: `pytest tests/readers/test_tdms_reader.py -v` — new tests fail
   (method doesn't exist yet), existing tests still pass.

2. In `readers/tdms_reader.py`: keep `required_group: str = "Courants_Alimentations"`
   as the fallback default; add `required_groups: dict[str, str] = {"Stats": "THD"}`;
   add `required_group_for(self, filename: str) -> str` mirroring
   `t_offset_for` exactly (substring scan over `required_groups`, else
   return `self.required_group`). Update the class docstring's `Attributes`
   section for the new dict/method.
   → verify: `pytest tests/readers/test_tdms_reader.py -v` — all green.

3. In `magnetdata.py::_fromtdms`, replace the check at lines 175–178:
   ```python
   if reader.required_group not in Groups:
       raise RuntimeError(f"_fromtdms: {reader.required_group} group not found in {name}")
   ```
   with a resolved-per-filename version using `reader.required_group_for(name)`.
   → verify: `pytest tests/test_magnetdata_tdms.py tests/readers/test_tdms_reader.py -v`
   green; then a read-only sanity check loading the real file at
   `~/LNCMIG-Data/records/pbsurv/M9/Fichiers_stats/M9_Stats_260909-100205.tdms`
   through `_fromtdms` to confirm the required-group check no longer raises.

4. Run the full suite: `pytest` → no regressions.

## Assumptions & open questions

- `"Stats"` matches by substring containment in the filename, same
  convention as `"Overview"`/`"Archive"` in `t_offsets` — so it matches e.g.
  `M9_Stats_260909-100205.tdms`.
- Scope is deliberately limited to `required_group` only. This does **not**
  touch `utils/files.py`, `runlogs/pigbrother.py`, `plotting/style.py`, or
  `pigbrother-defs.json`, which are still needed later for full Stats
  file-type support (mode-dir routing, `file_type` property, plot styling,
  field defs). Those are separate, not-yet-scoped follow-ups.
- Not touching `CHANGELOG.md` — it exists but isn't consistently updated per
  small fix in recent history.
