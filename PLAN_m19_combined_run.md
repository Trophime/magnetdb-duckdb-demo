# Note: the M19 combined run (M9 + M10 powered together)

**Status (2026-11-10): note only, design open.** Background for ROADMAP item
G8 "Special experiments (M19, negative IH/IB)" ([ROADMAP.md](ROADMAP.md),
[to_duckdb/TODOs.md](to_duckdb/TODOs.md)). It records facts and options; it
proposes no schema change. Mateo's negative IH/IB experiments, the other half
of G8, are not covered here.

All findings below were checked read-only on 2026-11-10 against
`to_duckdb/magnetdb-2026-11-05.duckdb` and `~/LNCMIG-Data/records/pbsurv`.

## What M19 is

From [to_duckdb/TODOs.md](to_duckdb/TODOs.md): "M19 test M9 with 18 MW and
M10 with 10 MW". The M9 and M10 housings ran **at the same time**, and the
pigbrother acquisition logged them under a separate housing prefix, `M19`.
A copy of the data sits in a folder named `20240206_30MW` (about 30 MW in
total; reading the name that way is an inference).

> **Name clash.** The inserts `M19071101` and `M19020601` are magnet names.
> They have nothing to do with the M19 housing. `M19071101` was even the M10
> insert during the M19 run (see below).

## Raw data

`pbsurv/M19/` holds **64 TDMS files**. The `pbsurv/20240206_30MW/M19/` tree
is an exact copy: same file names and sizes, 0 differences.

| Category | 2023-10 | 2024-02 | 2024-03 | 2024-04 |
|---|---|---|---|---|
| Archive | 4 | 22 | 1 | 1 |
| ManuelTrig | — | 27 | — | — |
| Overview | — | 2 | 1 | 1 |
| Stats | — | 2 | 1 | 1 |
| Default | — | 1 | — | — |

Files per day: 2023-10-30 (4), 2024-02-05 (21), 2024-02-06 (2),
2024-02-08 (31), 2024-03-07 (3), 2024-04-04 (3). `M19_Overview_240207-0936`
exists only as a `.tdms_index`: its data file is missing.

### Overview files

| File | Span (local) | Peak currents | Peak `Puissance Alims` |
|---|---|---|---|
| `M19_Overview_240205-1624` | 02-05 16:24 → 02-06 09:11 | ≤ 3 A (idle) | ~0 |
| `M19_Overview_240208-0941` | 02-08 09:41 → 14:10 | A1 15 835, A2 15 883, A3 16 210, A4 16 207; GR1 31 716, GR2 32 413 A | **31.5 MW** |
| `M19_Overview_240307-1538` | 03-07 15:38 → 15:39 | ≤ 4 A (idle) | n/a (empty channel) |
| `M19_Overview_240404-1316` | 04-04 13:16 → 13:24 | ≤ 5 A (idle) | — |

So the only Overview file with current is **2024-02-08**. On that day the
peaks match GR1 ≈ A1 + A2 and GR2 ≈ A3 + A4. This is a match of peaks only,
not checked sample by sample. `Champ magn` stays at 0 throughout.

### Channel layout differs from a single-housing file

Compared with a regular M9 Overview file (`M9_Overview_261104-1818`):

| Group | M9 (single housing) | M19 (2024-02) |
|---|---|---|
| `Courants_Alimentations` | `Courant_GR1`, `Courant_GR2`, `Champ_magn` | `Courant GR1`, `Courant GR2`, `Champ magn` (spaces) |
| `Tensions_Aimant` | `Interne1-2`, `Interne3`…`Interne7`, `Externe1`, `Externe2`, `ALL_internes`, `ALL_externes` | `M9Externe1`, `M9Externe2`, `ALL internes`, `ALL externes`, `M10Externe1`, `M10Externe2`, `ALL internes 2`, `ALL externes 2` |

- Both magnets' taps are in one file. There are no per-section `InterneN`
  taps, only the `ALL internes` totals.
- There is one GR1/GR2 pair and one field channel for two magnets.
- The 2024-04-04 file already uses underscores (`Courant_GR1`,
  `ALL_internes2`), so the M19 layout changed between February and April.

## Context in the database

Assemblies active over the whole M19 period (2023-10-30 → 2024-04-04):

| Assembly | Housing | Magnets | Window |
|---|---|---|---|
| `M9_A230801_00` | M9 | `M23072801`, `M9Bitters-newBi08` | 2023-08-01 → 2024-08-06 |
| `M10_A230509_00` | M10 | `M19071101`, `M10Bitters` | 2023-05-09 → 2024-12-09 |

Pupitre files (`experiments`) on the M19 days:

| Day | M9_A230801_00 | M10_A230509_00 |
|---|---|---|
| 2023-10-30 | — | — |
| 2024-02-05 / 06 | — | — |
| 2024-02-07 | 2 (15:15–15:18) | 21 (15:29–17:48) |
| 2024-02-08 | 2 (09:07, 12:54) | 1 (09:07) |
| 2024-03-07 | — | — |
| 2024-04-04 | — | 5 (15:34–16:13) |

- During 2024-02-05 → 02-08, M9 and M10 have **no pigbrother files of their
  own**: the acquisition wrote everything under `M19`.
- On 2024-04-04, M10 has its own pigbrother files again (3 Archive, 1 Default,
  3 Overview, 3 Stats). The M19 Overview stops at 13:24, and the M10 pupitre
  runs start at 15:34.
- The 2024-02-07 pupitre runs fall in the gap left by the missing
  `M19_Overview_240207-0936` data file.

## Why the database misses it

- `assemblies.housing` only takes M5, M7, M8, M9 and M10. There is no M19
  assembly.
- `populate` scans `pbsurv/<assembly.housing>/<subdir>`
  ([to_duckdb/populate.py](to_duckdb/populate.py), `pbsurv_dir / housing /
  …`). No assembly has `housing = "M19"`, so **0 rows** of `operationaldata`
  come from `pbsurv/M19` (M9: 26 903 rows, M10: 17 376).
- The schema assumes:
  - one housing per assembly;
  - no overlap between two assemblies of the same housing
    ([to_duckdb/docs/schema.md](to_duckdb/docs/schema.md));
  - one `assembly_name` per `operationaldata` / `overview_records` row.

  An M19 file belongs to two assemblies at once.
- The channel names (`Courant GR1` with a space, `M9Externe1`, …) would not
  match the readers written for single-housing files.

## Related issues

- **Data issue #17** (GR1/GR2 → IH/IB,
  [PLAN_overview_mode_gr_mapping.md](PLAN_overview_mode_gr_mapping.md)):
  the mapping already depends on the housing (M9: GR1 = IH; M8/M10: GR1 =
  Bitters). For M19 it is unknown which GR feeds which magnet.
- **magnet-scipy `reference_csv`:** the 2026-11-05 session used the M19
  Overview reference channels (`Référence_A1…A4`) as the example of a
  current reference read from pigbrother.
- **Field validation** (ROADMAP G6): `Champ magn` is 0 in M19 files, so no
  measured field is available for the combined run.

## Design options (not decided)

| Option | What | Pros | Cons |
|---|---|---|---|
| (a) Pseudo-housing `M19` | An assembly `M19_A240205_00` with housing `M19`, referencing the magnets of both assemblies | `populate` picks up `pbsurv/M19` unchanged | Same magnets in two active assemblies; per-housing no-overlap does not catch it; stats per assembly would mix M9 and M10 |
| (b) Link one file to two assemblies | A link table `operationaldata_assemblies` (file ↔ assembly) for combined runs | Each magnet keeps its own history | Schema change; every query on `assembly_name` must handle the link |
| (c) Split at ETL time | Write two derived records per M19 file, one per housing, with the matching channels | Downstream code stays single-housing | Needs the supply → magnet mapping; derived files to store and keep in sync |
| (d) Tag only | Load nothing into stats; register the M19 files with a tag (`special:m19`) for reference | Smallest change | M19 currents (31.5 MW) are missing from fatigue and cumulated stats of the magnets involved |

Whatever the option, the magnets' cumulated stats (hoop stress, fatigue,
hours) currently **miss the M19 runs**.

## Open questions

1. Which supply feeds which magnet during M19? (A1/A2 → GR1 and A3/A4 → GR2
   from the peaks; which GR is M9, which is M10, insert or Bitters?)
2. Was the field measured anywhere? `Champ magn` is 0.
3. What were the 2023-10-30 Archive files (4 files, no pupitre run that day):
   a commissioning test of the combined setup?
4. Where is the data file for `M19_Overview_240207-0936`? Only the index is
   on the records server.
5. Can `pbsurv/20240206_30MW/` be removed as a duplicate of `pbsurv/M19/`?
6. Were there other combined runs, under another prefix?
7. Should the M19 currents count in the cumulated stats of `M23072801`,
   `M19071101` and both Bitters?
