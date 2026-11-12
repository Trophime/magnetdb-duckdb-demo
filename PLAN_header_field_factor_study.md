# Pupitre header validity and field factors: study notes

**Status (2026-11-08): discussion record, nothing approved.** This file
keeps the discussion and the numerical findings that should be the starting
point of a study plan. The study plan itself is still to be written and
approved (see [Choices still open](#choices-still-open)).

Related plans:
- [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md): L2 "Pupitre
  header reader", header versions `stale` / `commissioning` / `valid`, open
  questions #24, #25, #27, #32, #33;
- [PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md): step 1b (supra
  current `IS` from Hybrid `I_BOB`);
- [PLAN_signature_regime_robustness.md](apps/dashboards/magnetdb/PLAN_signature_regime_robustness.md)
  (S1): `Field` signature thresholds.

## Context and goal

Find **when the pupitre header content is valid** for the magnets of an
assembly.

- When a brand-new magnet is put in operation for the first time, the first
  experiments of its assembly are the **commissioning**: resistances are
  measured to get the reference resistances used afterwards to monitor
  magnet health, and a run estimates the **field factor** (centre field /
  current) of the new magnet.
- The pupitre header of these experiments most likely still holds the
  settings of the **previous** assembly (the magnet that was in operation
  before).
- From time to time, reference resistances are rechecked or changed.

Wanted: a script that goes through the `experiments` table, associates a
`Field` signature with each experiment, records the pupitre header data to
check their validity, and estimates the field factors per magnet. It
prepares the next step for the digital twin models (phase 2 rules for the
header versions, phase 3 commissioning tables).

## What the pupitre header holds

Line 1 of a pupitre file (format from the pupitre writer, see the digital
twin plan, L2 "Pupitre header reader"):

```
NbCoil  MagnetCode  Imax1  Imax2  [R00  Adv  Bdv  CT] × NbCoil
```

Per channel: the reference-resistance polynomial `R00` [mΩ], `Adv`
[mΩ/A], `Bdv` [mΩ/A²] and the temperature coefficient `CT` [1/K]. The
pupitre monitoring model:

- R0c = R00 + Adv·|I| + Bdv·I²;
- Rm = 1000·|U/I| [mΩ]; Tmoy = (Tin + Tout)/2;
- R0 = Rm / (1 + CT·Tmoy);
- `DRcoil` = 100·(R0 − R0c)/R0c [%]; Tcal = |Rm/R00 − 1| / CT.

**The header contains no field factor.** Field factors are in MAGFILE
(`FF<n>`, G/A, one per circuit, B = FF1·I₁ + FF2·I₂) and, implicitly, in
the computed `Field` column (below).

## Findings so far

### `DRcoil` is only a weak validity indicator

On `M9_A250401_00`, the stale header (the previous insert's coefficients)
gives median `DRcoil` of −0.8 % to +1.8 % per slot; a valid header (after
the tap change of 2025-05-09, data issue #12) gives −0.3 % to +0.6 % on the
insert slots and about −1 % on the Bitters. Inserts are similar enough that
old coefficients don't stand out sharply: worth recording as a supporting
indicator, not as a decision rule.

### Pupitre `Field` is computed, not measured

- M9 `2026.10.29 - 18:03:45` (11 439 rows, IH up to 29 kA): `Field =
  8.943·IH + 3.634·IB` G/A, exactly MAGFILE `FF1` / `FF2`, rms residual
  0.1 mT (0.0 mT on plateaux).
- M9 `2026.05.08 - 09:00:22`: 7.329 / 3.766 G/A, rms 0.05 mT.
- So the factors **in use** change between assemblies (`M9_A260505_00`,
  insert `M19071101`, Bitters `newBi08_01`: 7.329 / 3.766;
  `M9_A260707_00`, insert `M25032101`, Bitters `newBi10`: 8.943 / 3.634).
- Fitting `Field` only recovers the factors the pupitre was configured
  with. That is still useful, like the header coefficients: the moment
  they change shows when the operators entered the new values.
- The digital twin plan's "checked against measured field" (M9 34.986 T,
  M5 10.0 T) compares computed values with themselves: to reword.

### Pigbrother `Champ_magn` is computed too

`M9_Overview_260508-0900.tdms` against `2026.05.08 - 09:00:22.txt`:

| Check | Result |
|---|---|
| Maximum | `Champ_magn` 28 984.1 mT vs `Field` 28.990 T |
| `Champ_magn`/1000 ÷ `Field` (28 055 rows above 1 T) | median 0.9997 (p5 0.9995, p95 1.0236) |
| `Champ_magn` fitted on `Courant_GR1` / `Courant_GR2` | 7.329 / 3.766 G/A, rms 0.63 mT, condition number 8 |
| pupitre `Field` fitted on IH / IB | 7.329 / 3.766 G/A, rms 0.05 mT |

- `Champ_magn` [mT] = `Field` [T] × 1000: the same computed value, by
  design in both systems (user, 2026-11-08); the "Hall probe" description
  in `pigbrother-defs.json` is wrong.
- Clock lag **pupitre ↔ pigbrother: +33 s** on this file (pupitre time +
  lag = pigbrother time). The remaining differences (rms 115 mT, up to
  0.54 T) are timing on ramps. This lag varies from file to file; it is
  handled per overview record (see [Lag estimation](#lag-estimation-its-own-step-before-any-cross-system-comparison)).
- **Consequence: neither pupitre nor pigbrother records a measured field**
  (at least not in the overview's `Courants_Alimentations` group). Only
  the field factors *in use* can be recovered from these sources.

### M8: resistive and supra terms

Files `2026.10.30 - 09:10:03` and `2025.11.05 - 14:42:13`:

- `TotalField = Field + SupraField` to within 0.10 mT (rounding);
- `Field` is an exact two-term function of IH and IB (rms 0.07 mT over
  12 634 and 8 338 rows);
- `SupraField` (up to 8.5 T and 4.3 T) varies independently of the
  resistive currents: `SupraField = ffS·IS`, with `IS` the supra current
  (Hybrid `I_BOB`);
- **In NORMAL runs IH and IB move together** (condition number 2200–2900
  on these two files): the fit gives 8.956 / 2.917 G/A in one file and
  8.994 / 2.880 in the other with the same tiny residual; one such file
  only fixes the combination along the IH/IB ratio. The same happens on the
  M9 commissioning file `2025.04.01 - 16:35:30` (IH/IB ≈ 1.04 throughout,
  condition number 1307, fit 8.19 / 4.53 G/A, meaningless).
- **The operating mode picks the separating runs** (same strategy as on
  M9/M10). On 22 M8 files from 2026-09-29 to 2026-11-06:

  | File | Mode (IH/IB slope at low current) | ffH [G/A] | ffB [G/A] | Condition number |
  |---|---|---|---|---|
  | 13 full-field runs | NORMAL, 0.94–0.98 | 8.915–8.962 | 2.911–2.956 | 823–3713 |
  | `2026.10.28 - 09:02:02` | ECO, −0.08 | 8.927 | 2.945 | 13 |
  | `2026.11.03 - 11:17:21` (low current, ≈ 430 A) | NORMAL, 0.92 | 8.925 | 2.947 | 17 |
  | 17 files with current, pooled | — | 8.930 | 2.942 | 1534 |

  Factors in use on M8 since at least 2026-09-29: **ffH ≈ 8.926, ffB ≈
  2.946 G/A**. The NORMAL runs stay within ±0.02 G/A because `Field` is
  computed and noise-free (the poor conditioning only amplifies rounding).

### Pupitre ↔ Hybrid lag (open question #27)

Measured with
[`python_magnetrun/examples/hybrid_pupitre_lag.py`](python_magnetrun/examples/hybrid_pupitre_lag.py)
on M8 `2026.10.30 - 09:10:03.txt` (whole run, hours 8–13 UTC); convention
pupitre time + lag = Hybrid time:

| Pair | Lag | rms residual, Otsu mask | rms residual, `--sessions-log` | Ratio (sessions log) |
|---|---|---|---|---|
| pupitre IB vs `FEPC-AUX-LNCMI` `ALIM1_J1 + ALIM1_J2` (GR1) | −190 s | 273 A | **7.5 A** | 1.0016 |
| pupitre IH vs `FEPC-AUX-LNCMI` `ALIM2_J1 + ALIM2_J2` (GR2) | −190 s | 356 A | **4.8 A** | 1.0011 |
| pupitre `SupraField` vs `FEPC-LNCMI` `I_BOB` (not masked) | −191 s | 4.5 A | 4.5 A | ffS in use = **11.837 G/A** |

- A lag correction is needed before aligning `I_BOB` on pupitre
  timestamps (step 1b aligns with a 0.5 s `merge_asof` and no lag; the
  dashboard's `load_hybrid_supra_current` is about 3 min off today).
- No drift visible over the 5 h run (the −181 / −188 s spread seen first
  came from a window stopping before the ramp down). With residuals of
  5–7 A, one lag per file is precise to about the 1 s sampling on this run.
- Only one run checked so far.
- **Masking of the Hybrid resistive currents.** The Hybrid system records
  the supply currents whatever housing they feed, while the M8 voltages
  are recorded only when M8 is fed. By default `HybridRun.getData` zeroes
  the ALIM currents where the companion voltage (`BITTER_V2` for ALIM1,
  `PH_V14` for ALIM2) is below an Otsu threshold: the ~450 A M8 standby
  steps (1.7 V / 0.33 V) read 0 A, which was most of the residual. With
  `LoadOptions.sessions_log` (EXPERIENCES_LOG CSV, implemented 2026-11-08)
  the currents are kept only inside an M8 session on their supply group
  (`ElecGroup`), padded by 5 min, and Otsu is the fallback after the end
  of the log. Masked samples are still 0 (switching to NaN is a separate
  plan). Checked on 2026-10-14: M8 standby kept (447 / 411 A), the M10
  session on the same supplies (1.5 kA) and the off periods zeroed.

## Proposed study script

### Per experiment (one row)

- **identity:** id, file, assembly, housing, housing version at the file
  start, whether the assembly is the first one of one of its magnets
  (brand-new magnet);
- **header:** line-1 class, `MagnetCode`, `R00/Adv/Bdv/CT` per slot, a
  content hash to group identical headers;
- **run:** duration, maximum field, maximum current per circuit;
- **`Field` signature:** U/P/D at two thresholds (0.1 and 0.02 T/s, since
  S1 has not run), stored with their parameters, plus a staircase count
  (number of plateaux at current), less threshold-dependent;
- **monitoring:** median `DRcoil` per slot while the current is above a
  limit;
- **field factors in use** (below), with the separability flag;
- **lags** to the other systems (below), with their residual;
- **session:** the EXPERIENCES_LOG session of the experiment, read from
  the DuckDB `users` table (built from the same CSV by
  `to_duckdb/demos/users_table_demo.py`), whose `experiments_ids` already
  links sessions to experiments: acronym, proposal details, and an
  operator-only flag (`acronym = 'EXPLOIT'`). The CSV itself stays the
  source of the Hybrid mask, since only it has the coil and `ElecGroup`.
  To check before relying on `users`: `hstart`/`hstop` in Paris local time
  like the CSV, and its unclosed sessions (open question below).

### Operator-only sessions as a commissioning hint [unverified]

Both known commissionings fall entirely in operator (`EXPLOIT`) sessions
(raw CSV rows):

| Magnet | Period checked | Log content |
|---|---|---|
| `M25032101` (M9, header stable from 2025-04-03 15:09) | 2025-04-01 → 04-03 | 15 rows, all `EXPLOIT` (operators Rémi, Kévin, Cédric); first user session 2025-05-06 (GMA05-223) |
| `M25012001` (M9, header stable from 2025-01-27 14:06) | 2025-01-23 → 01-30 | 38 rows, all `EXPLOIT`, 29 unclosed; first user session 2025-02-10 (GMA02-123) |

- **A hint, not a criterion:** since 2021, 939 of 5096 CSV rows (18 %) are
  operator-only (tests, maintenance, …). Useful combined with the other
  signals: first assembly of a brand-new magnet, staircase `Field`
  signature, header version changing just after.
- **"First user session" is not the end of commissioning:** for
  `M25032101` it comes a month after the header stabilised, just before
  the tap change of 2025-05-09 (data issue #12). At best an upper bound for
  #32.

### Per header version (consecutive experiments of an assembly with the same header)

- `valid_from` / `valid_to` (first and next file start), number of
  experiments;
- **candidate `stale`:** identical to the last header of the housing's
  previous assembly, or `MagnetCode` ≠ the assembly's insert;
- **kind of change** from the previous version: coefficients refitted
  (small relative change), tap layout changed (slots appearing or
  disappearing, as on 2025-05-09), `MagnetCode` changed;
- **the staircase experiments just before the change:** what a reference
  check looks like, at commissioning or later.

### Field factors in use

Fit `Field ≈ ffH·IH + ffB·IB` per experiment. The piecewise-linear
IH(IB) relationship decides **whether** the two factors can be separated:

| Segment of IH(IB) | What it gives |
|---|---|
| IB constant (including 0), IH ramping | ffH = dB/dIH |
| IH constant, IB ramping | ffB = dB/dIB |
| IH = a·IB with at least two different slopes *a* | solve the 2×2 system |
| a single ratio over the whole file (co-ramped, `NORMAL` mode) | only ffH·a + ffB: not separable from this file |

- Infer the operating mode first (as on M9/M10): it selects the runs that
  separate the factors (ECO runs, low-current tests, see the M8 table
  above); NORMAL runs only fix the combination and serve as a consistency
  check. Reuse the idea of `infer_operating_mode`, not its code: it fits
  one slope near IB = 0, and it takes `Courant_GR1` as IH, which is
  inverted on M8 and M10 (digital twin data issue #17, to fix by housing
  version first). The pupitre `IH` / `IB` columns are already named by
  role. Fit on plateaux, to avoid lag and inductive effects; condition
  number as the separability test.
- When a file can't separate them, **pool the experiments of the same
  assembly**: an in-situ field factor is constant within an assembly (as
  long as the factors in use don't change).
- **M8:** `SupraField / IS` gives ffS directly (single term, no offset);
  checking it stays constant through the file is the validation. It needs
  `IS` aligned with the lag above.
- Changes of the factors in use are tracked like header versions.

### Lag estimation (its own step, before any cross-system comparison)

Uses quantities the systems compute identically:

- pupitre `Field` ↔ pigbrother `Champ_magn`/1000;
- pupitre IB / IH ↔ Hybrid `ALIM1` / `ALIM2`, loaded with the sessions
  log (`LoadOptions.sessions_log`) so the low-current steps are kept;
- pupitre `SupraField` ↔ Hybrid `I_BOB` (also gives ffS).

The lags vary from file to file, which is why `overview_records` attaches
the pupitre, pigbrother and Hybrid files of a run before the lag is
computed: they are stored per overview record in `sync_info` (S2). The
study reuses them when filled and estimates them otherwise (per hour if a
drift shows up), with the residual as a quality indicator. These lags also
feed S3 and step 1b.

### Measured field factors (stage 2, blocked)

Needs a **measured** centre field, which neither pupitre nor pigbrother
holds (see findings). Blocked until its source is known (open question
below). With it: measured (ffH, ffB, ffS on M8) per commissioning, compared
with the factors in use.

### Report

Per assembly: the header versions with their candidate status, the changes
with the experiments that preceded them, the factors in use and their
changes. Material to settle #32 (end of commissioning) and #33 (moved
magnets) and to write the phase 2 rules.

## Choices still open

Recommendations first.

1. **Output:** files (Parquet or CSV plus a Markdown report), no database
   change; phase 2 defines the real tables (`operating_configurations`,
   `config_sections`) from what the study shows. Alternative: a DuckDB
   staging table.
2. **Scope:** experiments with a full header only (about 3500 since
   2021-09, out of 6483), with `--housing` / `--assembly` filters.
   Signatures need the whole file, read over the records mount, so a full
   run takes a while.
3. **Signature threshold:** two thresholds plus the staircase count (above)
   rather than one.
4. **Location:** `to_duckdb/demos/`, reusing the helpers of
   `magnet_first_signatures.py`.
5. **M8 supra term in the first version:**
   - (a) compute ffS for M8 experiments with a Hybrid source, with the
     per-file lag correction (now measurable, see #27 above);
   - (b) leave it out until step 1b exists; do only ffH / ffB with the
     separability flag.

   (b) was recommended before the lag was measured, to keep the study
   independent of the Hybrid data; (a) is now feasible.

## Open questions

1. **Source of the measured centre field during commissioning:** NMR or
   Hall probe read by a separate system, a manual measurement, another
   pigbrother group or file? If kept somewhere, the study can compare it
   with the factors in use; if not, measured factors are entered by hand
   (L3 commissioning tables).
2. ~~Is the lag constant across runs?~~ Answered for pupitre ↔ pigbrother:
   it varies from file to file (+33 s on one M9 file), handled per
   overview record (`overview_records` sources, `sync_info`). Pupitre ↔
   Hybrid: presumably the same (one run checked, −190 s), stored the same
   way.
3. End of commissioning and moved magnets: digital twin open questions
   #32 and #33.
4. **Unclosed EXPERIENCES_LOG rows** (blank `HStop`: 1466 of 34 485 CSV
   rows; 376 of 4587 `users` sessions with `hstop` NULL, 236 of them
   `EXPLOIT`). Mostly repeated clicks within seconds, sometimes sessions
   left open for hours. python_magnetrun `load_sessions` drops a row
   followed by a new row on the same coil within 10 min, and closes the
   others at the next `HStart` on that coil or after 12 h; the DuckDB
   `users` table keeps `hstop` NULL. How should they be closed for the
   study and for the Hybrid mask? With the current rule, the mask windows
   can be wider than the real powering during a commissioning (many open
   rows), keeping currents that fed another housing.

## Tools

- [`to_duckdb/demos/magnet_first_signatures.py`](to_duckdb/demos/magnet_first_signatures.py):
  first valid experiment per magnet and its `Field` signature;
- [`python_magnetrun/examples/hybrid_pupitre_lag.py`](python_magnetrun/examples/hybrid_pupitre_lag.py):
  pupitre ↔ Hybrid lag and alignment plot; `--sessions-log` for the
  session-log mask;
- [`Data/EXPERIENCES_LOG.csv`](Data/EXPERIENCES_LOG.csv): SUPERVISION
  session log (coil, `ElecGroup`, `HStart`/`HStop` in Paris local time),
  read by python_magnetrun `analysis/sessions.py`; DuckDB `users` table
  built from it by
  [`to_duckdb/demos/users_table_demo.py`](to_duckdb/demos/users_table_demo.py).
