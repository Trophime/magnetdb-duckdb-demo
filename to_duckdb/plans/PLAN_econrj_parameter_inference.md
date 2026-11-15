# Plan — infer EcoNRJ parameters (Tr, R, ImaxH, ImaxB) from IH/IB data

Status: not implemented — design sketch for future work

## Goal

Given a dataset of `(IH, IB)` current pairs from a magnet run (or several
runs), automatically fit and report the four EcoNRJ mode parameters that are
not already known from the field-map commissioning data: `Tr`, `R`,
`ImaxH`, `ImaxB`.

## Background: the EcoNRJ model

EcoNRJ mode uses 6 parameters per site to derive the B-field profile from
Bitter & Helix coil currents:

- Field factors `FFH`, `FFB` — [T/A], convert coil current to field
  contribution. Already estimated separately via OLS regression
  (`python_magnetrun/tests/test-fieldfactor.py`, README.md "Field factor
  identification" section).
- Current limits `ImaxH`, `ImaxB` — [A], max current per coil.
- Threshold and ratio `Tr`, `R` — the switch point between two operating
  regimes:
  - **Constant gradient** (B ≤ BTr): `IH` and `IB` increase together from
    the origin at a fixed ratio `R = IH / IB`.
  - **Variable gradient** (B > BTr): ratio changes; both currents continue
    increasing (at a different, shared slope) until they reach `ImaxH` and
    `ImaxB` simultaneously at the site's maximum field.

In the `(IB, IH)` plane this is a single-breakpoint piecewise-linear curve:
segment 1 is a line through the origin with slope `R`; segment 2 runs from
the breakpoint `(IB_Tr, Tr)` to the endpoint `(ImaxB, ImaxH)`.

## Existing tooling to build on

- `python_magnetrun/examples/corr_Ih_Ib.py` already fits piecewise-linear
  `IH`/`IB` relationships:
  ```bash
  python3 examples/corr_Ih_Ib.py <file>.txt --xkey IB --ykey IH \
      --algo piecewise_regression --breakpoints 1
  ```
  Uses the `piecewise_regression` package (Muggeo's segmented regression)
  or `pwlf` as an alternative backend. Currently only plots the fit; does
  not extract or report `Tr`/`R`/`ImaxH`/`ImaxB` as named values.
- `python_magnetrun/tests/test-fieldfactor.py` — separate OLS regression
  for `FFH`/`FFB`, not part of this task but produces the other 2 of the 6
  parameters.

## Fitting recipe

1. Run a 1-breakpoint segmented regression of `IH` on `IB`:
   `pw_fit = piecewise_regression.Fit(IB, IH, n_breakpoints=1)`.
2. Read off `const`, `alpha1` (slope 1), `beta1` (slope change),
   `breakpoint1` from `pw_fit.get_results()`.
3. Map to the EcoNRJ parameters:
   - `R = alpha1`
   - `IB_Tr = breakpoint1`, `Tr = const + alpha1 * breakpoint1`
   - `alpha2 = alpha1 + beta1`
   - `ImaxB = max(IB)` observed in the (filtered) dataset
   - `ImaxH = Tr + alpha2 * (ImaxB - IB_Tr)`, or `max(IH)` directly if the
     run genuinely reached the current limit

## Caveats / validity checks

- `const` should come out ≈ 0 — segment 1 is physically forced through the
  origin (both currents are zero at zero field). A large intercept signals
  either a current-sensor zero offset or contamination of the fit window
  with non-ramp data.
- Not every `(IH, IB)` pair in a Pupitre log lies on the EcoNRJ envelope —
  only points from an actual EcoNRJ-mode ramp toward max field do. Mixing
  in arbitrary user-selected operating points will bias or blur the
  breakpoint fit.
- Practical data selection: prefer one clean full-field ramp-up per run
  (drop plateau/ramp-down/noise segments) rather than pooling raw points
  across many runs indiscriminately.

## Implementation TODO

- [ ] Add a `--report-econrj-params` (or standalone script) that wraps the
  fit above and prints/returns `{R, Tr, ImaxH, ImaxB}` instead of only
  plotting.
- [ ] Add the origin-constraint sanity check (`const ≈ 0`, e.g. warn if
  `|const| > tolerance`).
- [ ] Add a ramp-selection filter (monotonic increasing segment, drop
  plateaus) so a raw Pupitre file can be fed in directly.
- [ ] Validate fitted values against known commissioning field-map
  parameters for at least one site (MagnetInfo field-maps reference) to
  confirm the mapping is correct.
- [ ] Decide whether to support pooling `(IH, IB)` endpoints across
  multiple runs (one point per full-field ramp) as an alternative data
  source to a single-run trajectory.

## Open questions

- Is `Tr` in the actual Pupitre/EcoNRJ config defined as the Helix current
  at the threshold (as assumed above), or as the threshold field `BTr`
  itself? Needs cross-checking against a real site config if one becomes
  available.
- Should the fit be done per-site, per-housing, or per-run? (Field factors
  are per-site; it's not yet confirmed whether `Tr`/`R`/`ImaxH`/`ImaxB` are
  as well.)
