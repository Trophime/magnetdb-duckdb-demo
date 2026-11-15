# Follow-up prompt — fix `mid_elem`/`mid_stack` in magnettools' Python bindings

Status: not started. Targets a **separate repository**
(`~/github/my-magnettools`, remote `git@github.com:Trophime/magnettools.git`,
upstream `feelpp/magnettools`) — not `2026-m1-hifimagnet`. Paste the block
below into a fresh session started in `~/github/my-magnettools`.

---

```
Fix the representative-section selection in getHoop() in Python/Bmap.py of
this repo (magnettools' Python bindings), applying the same strategy used to
fix the equivalent bug in a sibling project (2026-m1-hifimagnet/to_duckdb),
summarized below.

## Context: what was found and how, in the sibling project

While debugging why to_duckdb's `hoop-stress compute` pipeline produced
wrong hoop-stress values for a real Bitter magnet, an array-index heuristic
called `mid_elem` was found to be picking the wrong "representative"
turn-group/section for current-density sampling:

    n_elem = Tube.get_n_elem()
    mid_elem = int(n_elem / 2) if (n_elem % 2) == 0 else int((n_elem + 1) / 2)
    j_unit_h[i] = Helices[mid_elem + Tube.get_index()].get_CurrentDensity()

This is `ceil(n_elem/2)` used as a 0-indexed array offset — for odd
`n_elem` it lands one position *past* the true center, not at it. Confirmed
against real geometry data: a Bitter part with `modelaxi.turns=[6,158,6]`
has 3 sections at z_offset `[-0.279, -0.000, +0.279]` m (halfheight
`[0.020, 0.259, 0.020]` m — confirmed via `BitterMagnet.get_Z_offset()`/
`get_HalfHeight()`); the section actually containing z=0 is index 1 (the
big 158-turn one), but the formula picks index 2 (a small end section).

The actual *purpose* of `mid_elem` (confirmed in discussion, not guessed):
Bz is only ever evaluated at one fixed z (z=0 in the existing code), so the
sampled current density should come from whichever section is genuinely
located at that z — not an arbitrary array-index "middle".

## The fix applied in the sibling project (stress_map.py)

Replaced the array-index heuristic with a helper that finds the section
whose z-extent actually contains the evaluation point:

    def _section_index_at_z(elements, indices, z0: float = 0.0) -> int:
        """Return the index from *indices* whose z-extent contains *z0*.
        Falls back to the closest get_Z_offset() if none does."""
        best_idx = indices[0]
        best_dist = None
        for idx in indices:
            elem = elements[idx]
            z_off = elem.get_Z_offset()
            half_h = elem.get_HalfHeight()
            if (z_off - half_h) <= z0 <= (z_off + half_h):
                return idx
            dist = abs(z0 - z_off)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

Applied identically to Helix (`Tubes`/`Helices`, grouped via
`Tube.get_index()`/`Tube.get_n_elem()`) and Bitter (`BMagnets`, grouped per
DB part via `mt.create_Bstack(BMagnets)`) — both are built from the same
`BitterMagnet` type, so the same helper covers both.

**Gotcha hit along the way**: iterating a `mt.VectorOfStacks` or a `Stack`
object directly (`for stack in stacks`, or `list(stack)`) raises
`RuntimeError`. Only index-based access works:
`stacks[i]`, `stack[j]`, built via `range(len(...))`.

z0 defaulted to 0.0 (current behavior) but was made resolvable per-magnet
in the caller (site_magnets.z_offset, DB-specific — not relevant to
magnettools itself, which has no DB concept; a plain z0 argument/default is
the right level here).

## What needs the same fix in THIS repo (Python/Bmap.py, getHoop())

`getHoop()` has its own **independent copy** of the same `mid_elem` bug for
Helix, plus a more broken variant for Bitter, plus an unrelated but
adjacent formula bug:

1. **Helix** — identical `mid_elem` off-by-one:

       for i, Tube in enumerate(Tubes):
           n_elem = Tube.get_n_elem()
           mid_elem = int(n_elem / 2) if (n_elem % 2) == 0 else int((n_elem + 1) / 2)
           j = Helices[mid_elem + Tube.get_index()].get_CurrentDensity()
           j_rint.append(j)

2. **Bitter `mid_stack`** — more broken than Helix's: the loop treats each
   *global BMagnets index* as if it were a section count, and only the
   *last* loop iteration's result survives (the loop body reassigns
   `mid_stack` every iteration instead of computing it once from
   `len(stack)`):

       Bstacks = mt.create_Bstack(BMagnets)
       for i in range(len(Bstacks)):
           stack = Bstacks[i]
           mid_stack = 0
           for k in range(len(stack)):
               n = stack[k]                              # a global BMagnets index, not a count!
               mid_stack = int(n / 2) if (n % 2) == 0 else int((n + 1) / 2)
           j = BMagnets[mid_stack].get_CurrentDensity()   # only correct by coincidence
           j_rint.append(j)

   Fix: build `indices = [stack[k] for k in range(len(stack))]` (remember
   the iteration gotcha above), then use the same
   `_section_index_at_z(BMagnets, indices, z0=0.0)` pattern as Helix.

3. **Bitter total-field formula bug** (found while investigating the above
   — same function, adjacent code, worth fixing in the same pass): the
   Helix loop correctly computes `Bext = Bb + Bs` then total field
   `Bext + Bh` (all three sources, no double-count). The Bitter loop copies
   that pattern verbatim but for Bitter, `Bext` is already `Bh + Bs`, so
   `Bext + Bh` double-counts Helix's field and never includes `Bb`
   (Bitter's own self-field, driven by the actual Bitter current) at all:

       for i in range(len(Bstacks)):
           Bext = Bh[len(Tubes) + i] if Bh is not None else 0
           Bext += Bs[len(Tubes) + i] if Bs is not None else 0
           Hoop_.append([
               f"B{i + 1}", rints[...], j_rint[...],
               Bext + Bh[len(Tubes) + i],   # BUG: should be Bext + Bb[len(Tubes) + i]
               Bb[len(Tubes) + i],           # self field — already correct
               rints[...] * j_rint[...] * (Bext + Bh[len(Tubes) + i]) / 1.0e6,   # inherits the bug
               rints[...] * j_rint[...] * Bb[len(Tubes) + i] / 1.0e6,
           ])

   Confirmed empirically: on a real Bitter-only experiment (IH=0
   throughout), this bug makes getHoop()'s Bitter Hoop_MPa values collapse
   to ~0 regardless of the real (non-zero) Bitter current, since the
   formula never includes Bb.

## Process

1. Read getHoop() in full first (Python/Bmap.py) — confirm these are still
   the current bugs (recent commit history on this file — `fix input
   currents in getHoop`, `fix getHoop` — suggests it's actively worked on;
   re-verify against HEAD before assuming the above is unchanged).
2. Ground every claim in real data before fixing — construct real
   `mt.BitterMagnet(...)`/`mt.Tube(...)` objects (or load a real site's
   geometry) and print actual `get_Z_offset()`/`get_HalfHeight()`/
   `get_CurrentDensity()` values rather than reasoning from the code alone.
   The constructor signature for `mt.BitterMagnet` is (confirmed via
   `help()`): `(external_radius, internal_radius, height, currentdensity,
   z_offset=0.0, lambda=1.0, rho=0.0)` — `get_HalfHeight()` returns
   `height/2`.
3. Present a plan (the concrete diff for all three items above) before
   editing, per this project's normal review process — check if this repo
   has its own contribution/review conventions (CLAUDE.md or equivalent)
   and follow them.
4. Implement: shared `_section_index_at_z()`-equivalent helper (or inline,
   matching this codebase's existing style), applied to both Helix and
   Bitter; fix the Bitter total-field formula.
5. Test: unit tests using lightweight, directly-constructed
   `mt.BitterMagnet`/`mt.Tube` objects (no full geometry-file loading
   needed) covering symmetric/asymmetric section layouts and the
   fallback-when-no-section-contains-z0 case. Add a regression test
   reproducing the real `[6,158,6]`-style layout.
6. Verify end-to-end against a real multi-section Bitter magnet if this
   repo has (or can reach) real geometry fixtures/test data — confirm
   Hoop_MPa for Bitter is no longer ~0 when Bitter current is non-zero.
```
