# Plan: fill missing `Magnet Sites` in proposals CSV

## Goal

Fill the empty `Magnet Sites` column in `Data/proposals_2026-07-22.csv` by
looking up each proposal's `Acronym` in `Data/EXPERIENCES_LOG.csv`'s
`UserCode`/`Magnet` columns, normalizing `M10e`/`M10i` → `M10`, and falling
back to fuzzy matching (with warnings) when the acronym isn't found
verbatim.

## Files affected

- `scripts/fill_magnet_sites.py` — create (new standalone script)
- `Data/proposals_2026-07-22_with_sites.csv` — create (new output file;
  original left untouched)

## Key findings from investigation

- There is no `UserCode` column in the proposals CSV — `Acronym` is the
  matching field (format `GXXnn-nnn`, e.g. `GSC01-219`), and it lines up
  with `EXPERIENCES_LOG.UserCode` (579 exact matches out of 1851 unique
  acronyms confirms this).
- `Magnet Sites` is currently empty for all 1912 rows.
- `EXPERIENCES_LOG.Magnet` values are `M1`…`M10` with an `e`/`i` suffix for
  insert/external coil (`M8e/M8i`, `M9e/M9i`, `M10e/M10i`); this matches the
  same normalization already used elsewhere in the repo
  (`to_duckdb/import_housing_summary.py:485`:
  `regexp_replace(p.Site, '[ie]$', '')`).
- A single `Acronym` can map to more than one distinct base magnet (147
  cases in the log) — joined as `;`-separated, numerically sorted (e.g.
  `M9;M10`).
- Fuzzy matching: at `difflib` cutoff `0.9`, 143 additional acronyms get a
  plausible typo match (missing/extra space or hyphen, digit slip — e.g.
  `'GAS01-111' -> 'GAS 01-111'`), with no obviously wrong matches. Lower
  cutoffs (e.g. 0.8) pull in clearly wrong matches (e.g.
  `GAS01-114 -> GAS07-114`, a different proposal), so 0.9 is the default.
  One case only differs by letter case (`GSC44-213`), handled by comparing
  case-insensitively before fuzzy matching.
- ~1176 acronyms have no match at all (exact, case-insensitive, or fuzzy)
  — these are left blank; no per-row warning (would be noisy), just a
  summary count.

## Approach

1. `scripts/fill_magnet_sites.py`, driven by `argparse`:
   - `--proposals` (default `Data/proposals_2026-07-22.csv`): input
     proposals CSV.
   - `--log` (default `Data/EXPERIENCES_LOG.csv`): input experiences log
     CSV.
   - `--output` (default `Data/proposals_2026-07-22_with_sites.csv`): path
     to write the filled-in CSV.
   - `--separator` (default `;`): separator used to join multiple base
     magnets in the `Magnet Sites` field (e.g. `M9;M10`).
   - `--fuzzy-cutoff` (default `0.9`, type `float`): `difflib` similarity
     cutoff for fuzzy `Acronym` → `UserCode` matching.
   - Logic:
     - Load `EXPERIENCES_LOG.csv`, build
       `UserCode (stripped) -> set of base magnets` (strip trailing `e`/`i`
       from `Magnet`).
     - Load `proposals_2026-07-22.csv` rows.
     - For each row with a non-empty `Acronym` and empty `Magnet Sites`:
       - Exact match (case-sensitive, then case-insensitive) → use it
         directly.
       - Else fuzzy match via
         `difflib.get_close_matches(cutoff=args.fuzzy_cutoff)` → use it,
         and print a warning:
         `WARNING: Acronym 'X' not found; using fuzzy match 'Y' (magnets: ...)`.
       - Else leave blank.
     - Write all rows (unchanged columns except `Magnet Sites`, joined with
       `args.separator`) to `args.output`.
     - Print a final summary: counts of exact / fuzzy / unmatched rows.
2. Run the script (defaults matching the values validated during
   investigation) and inspect the printed warnings + summary counts.

## Verification

- Run `python3 scripts/fill_magnet_sites.py` (defaults) and confirm it
  completes without errors.
- Spot-check output: exact-match count should be 579, fuzzy-match count
  ≈143, unmatched ≈1176 (per the pre-analysis above).
- Diff a few known rows (e.g. `GSC01-219`) against `EXPERIENCES_LOG.csv` by
  hand to confirm correctness.
- Confirm `--output`, `--separator`, and `--fuzzy-cutoff` each override
  their default correctly (e.g. rerun with `--fuzzy-cutoff 0.8` and check
  the fuzzy-match count increases).

## Assumptions & open questions

1. Default output stays a **new file**
   (`Data/proposals_2026-07-22_with_sites.csv`) rather than overwriting the
   original; `--output` lets you point it elsewhere, including back at the
   original if you want in-place overwrite.
2. Default separator `;` (via `--separator`) — override at the CLI if you
   prefer `,` or space.
3. Default fuzzy cutoff `0.9` (via `--fuzzy-cutoff`); warnings are still
   only printed to stdout, not written to a separate log file — say if you
   want that too.
