# Notes — hoop-stress compute pipeline: implementation and testing

Companion to `PLAN_hoop_stress_history.md` (status/phase tracking). This
note is the technical record of Phase 1: making `hoop-stress compute`
actually work end-to-end, and what was done to verify it. Uncommitted, same
as the code it describes.

## Context

`hoop-stress compute` (`compute_hoop_stats.py:compute_hoop_stress_history`,
delegated to from `magnetdb.py`) had never successfully run against real
data. The bug that caused this was masked by a swallowed exception, so
fixing it surfaced a chain of further bugs, each only reachable once the
previous one was fixed. Every item below was found and fixed in that order,
against `test-magnetdb.duckdb` (a scratch copy — `magnetdb.duckdb`,
production, was never written to).

## Implementation

### 1. `prepare_geometry_directory()` called incorrectly

`compute_hoop_stress_history` called it once per magnet, in a loop:

```python
for magnet_name, config, geometry_data in magnet_configs:
    prepare_geometry_directory(
        magnet_name, config, tmpdir_path,
        geometry_data=geometry_data, geometries_dir=geometries_dir,
    )
```

but the real signature is `prepare_geometry_directory(site_name, config,
db_path, geometries_dir=None)` — no `geometry_data` parameter at all, and
the third positional argument is `db_path`, not a temp directory. Every call
raised `TypeError`, caught by a bare `except Exception: print(f"[WARN]
...")` that let the pipeline limp on with an empty geometry directory, only
to fail later (or silently produce nothing).

The working reference was `_load_site()` (used by the already-functional
`barchart`/`history`/`stats`/`fatigue` commands), which calls it **once per
site**:

```python
site_config = {"name": site_name, "magnets": [config for _n, config, _g in magnet_configs]}
tmpdir_path = prepare_geometry_directory(site_name, site_config, db_path, geometries_dir=..., con=con)
```

Fixed `compute_hoop_stress_history` to match.

### 2. Stale docstrings

`prepare_geometry_directory` and `geometry_config_to_yaml`'s docstrings
described a "geometry_data argument" source and a `geometries_dir`
read-fallback that were never implemented. Investigation traced the real
behavior: `parts.geometry_data` is the *only* geometry ever persisted;
`magnets.geometry_data` and `sites`-level geometry are always rebuilt on the
fly (`magnet_geometry_config_to_yaml()` from parts, `geometry_config_to_yaml()`
from magnets). Docstrings corrected to say so. `magnetdb.py magnet add
--geometry`'s help text made the same false claim ("required for
geometry_config_to_yaml") — corrected to describe it as an optional cache.

### 3. DuckDB connection conflict

Once (1) was fixed enough to actually reach `prepare_geometry_directory`,
it failed with:

```
Connection Error: Can't open a connection to same database file with a
different configuration than existing connections
```

`compute_hoop_stress_history` holds one read-write `con` open for the whole
function; `geometry_config_to_yaml`/`magnet_geometry_config_to_yaml` each
opened their *own* fresh read-only connection to the same file internally.
DuckDB doesn't allow that. `load_site_config_from_duckdb` already had a
`con=` reuse parameter for exactly this reason — `prepare_geometry_directory`
and the two functions it calls didn't. Added the same `owns_con = con is
None` pattern to all three, and threaded `con=con` from
`compute_hoop_stress_history`.

### 4. `load_magnettools()` called with the wrong shape

Next failure: `msite_setup: ... KeyError: 'magnets'`. `msite_setup()`
(python_magnetsetup, external package) unconditionally does
`confdata['magnets']` — it always expects the site-shaped
`{"name":..., "magnets": [...]}` dict, for any number of magnets.
`compute_hoop_stress_history` instead built `combined_config` via
`magnet_configs[0][1]` (single magnet) or `_merge_configs(magnet_configs)`
(flat key-merge across magnets) — neither has a `"magnets"` key.
`_merge_configs` was dead weight the moment this was fixed (only caller),
so it and its two unit tests were deleted. Fixed to reuse the same
`site_config` already built for step 1.

### 5. Bitter parts with multiple physical plates

Next failure, on a real Bitters magnet with 2 DB parts:

```
Constraint Error: Violates foreign key constraint because key
"name: B3_fast" does not exist in the referenced table
```

`build_part_column_map()` assumes one `B{n}_fast` column per DB `bitter`
part. But `python_magnetsetup.ana.BMagnet()` decomposes *each* Bitter part
into one `mt.BitterMagnet` per axial turn-group (its `modelaxi.turns`/
`pitch` lists) — for this magnet, 2 parts → 6 turn-groups. Confirmed via
`n_bmag = len(BMagnets)` at the precompute stage (6), while `magnet_parts`
only has 2 `bitter`-type rows for that magnet. Columns B3_fast–B6_fast had
no entry in `part_map`, fell back to the literal column name, and violated
the FK.

Fixed by grouping `BMagnets` back into per-part stacks via
`mt.create_Bstack(BMagnets)` (confirmed empirically: for 6 BMagnets across
2 parts, it returns 2 stacks of indices `[0,1,2]` and `[3,4,5]`) and
collapsing each stack to one representative value — `n_bmag` becomes
"number of DB Bitter parts" again, matching `build_part_column_map`
unchanged. No schema change; `part_name` stays the plain part name.

Note: iterating a `mt.VectorOfStacks`/`Stack` object directly (`for stack in
stacks`, or `list(stack)`) raises `RuntimeError` — only index-based access
(`stacks[i]`, `stack[j]`, `range(len(...))`) works. Cost one extra
debugging round-trip.

### 6. Representative-section selection (`mid_elem` → `_section_index_at_z`)

The pre-existing Helix code picked one "representative" turn-group per Tube
via an array-index heuristic:

```python
n_elem = Tube.get_n_elem()
mid_elem = int(n_elem / 2) if (n_elem % 2) == 0 else int((n_elem + 1) / 2)
j_unit_h[i] = Helices[mid_elem + Tube.get_index()].get_CurrentDensity()
```

Investigation (prompted by discussion of what this was *for*: Bz is only
ever evaluated at a fixed z, currently `z=0`, so the sampled current density
should come from whichever section is actually located at that z) found a
real off-by-one: `mid_elem` computes `ceil(n_elem/2)` as a 0-indexed array
offset, which for odd `n_elem` lands one position *past* the true center,
not at it. Confirmed against real data — a Bitter part with
`turns=[6,158,6]` has 3 sections at z_offset `[-0.279, -0.000, +0.279]`
(halfheights `[0.020, 0.259, 0.020]`); the true z=0-centered section is
index 1, but `mid_elem` for n=3 picks index 2 (an end section).

Replaced with `_section_index_at_z(elements, indices, z0=0.0)`
(`stress_map.py`): finds the section among `indices` whose
`[z_offset−halfheight, z_offset+halfheight]` interval actually contains
`z0`, falling back to the closest `z_offset` if none does. Applied
identically to Helix (`Tubes`/`Helices`) and Bitter (`Bstacks`/`BMagnets`),
since both are built from the same `mt.BitterMagnet` type via the same
`python_magnetsetup.ana.BMagnet()` decomposition.

`_bz_at(radii, z0s)` was reworked from a single shared `z=0` to per-element
`(r, z)` pairs, since Bz genuinely depends on z (this was a real correction
mid-discussion — r is constant across a part's sections, but Bz is not).

### 7. Per-magnet z0 from `site_magnets.z_offset`

`z0` defaults to `0.0` (magnets centered on z=0) but is resolved **per
magnet**, not globally, via new `resolve_z0_by_type(site_name, db_path,
con=None)` (`compute_hoop_stats.py`, mirrors `build_part_column_map`'s
magnets-JOIN-parts traversal, additionally joining `site_magnets.z_offset`).
Returns `(z0_h, z0_b)` — ordered lists matching `H{i}_fast`/`B{j}_fast`
column order — so a magnet installed off-center within a site (nonzero
`site_magnets.z_offset`) is evaluated at its own true axial position. No
CLI flag; fully automatic. (0 of 89 real `site_magnets` rows currently have
a non-zero `z_offset`, so this path is real but currently untested against
production data — see Known limitations.)

### 8. Bitter/Supra silently dropped from `history`/`fatigue`

Three `H\d+_fast`-only regexes in `stress_map.py` (`cmd_fatigue`,
`plot_stress_history`, `_load_history`'s preview print) meant `hoop-stress
history`/`fatigue` only ever showed Helix columns, even with
`--magnet-type all`. `compute_stress_stats()` already used the correct
`(H|B|Supra)\d+_fast` pattern — the other three were brought in line.

## Testing

- **Orchestration test** for `compute_hoop_stress_history()` — previously
  had zero coverage at this level (only its helper functions were tested;
  see the now-obsolete `PROMPT_test_hoop_orchestration.md`). New
  `tests/test_compute_hoop_stats.py` fixtures use a **file-backed** scratch
  DuckDB (`tmp_path`), not the usual `:memory:` `con` fixture — confirmed
  empirically that `compute_hoop_stress_history()` opens its own
  `duckdb.connect(db_path)`, which does not see state from a separate
  `:memory:` connection. Covers: full successful run, geometry-prep failure
  aborting cleanly (and the temp directory it created being cleaned up —
  regression check for the connection-conflict fix), skip/reprocess
  semantics, dry-run writing nothing, mixed bin-configs warning without
  skipping, one experiment erroring without aborting the batch, and an
  experiment with no hoop columns.
- **Unit tests**: `compute_stress_stats()` (previously untested),
  `_section_index_at_z()` (symmetric/asymmetric section layouts built from
  real `mt.BitterMagnet(...)` objects — constructor signature confirmed via
  `help()` before writing the tests — including a fallback case where no
  section contains z0), `resolve_z0_by_type()` (default-zero case and a
  fixture with an explicit non-zero `site_magnets.z_offset`), and
  regression tests locking in the Bitter/Supra regex fix.
- **Real-data verification**: `hoop-stress compute --site M9_A241202_00
  --db test-magnetdb.duckdb --reprocess` — a site with one Insert magnet
  (14 Helix parts) and one Bitters magnet (2 parts, 6 physical plates).
  Confirmed: geometry prep succeeds (previously always failed), `msite_setup`
  loads both magnets (14 Helices, 2 Bstacks), hoop stress computes for the
  one experiment file, `hoop_stress_bin_stats`/`hoop_stress_fatigue` get
  exactly 16 part rows (14 Helix + `M9Be` + `M9_newBi08`, no FK violation),
  `hoop_stress_processed` marks the experiment processed with the correct
  Parquet path, and the Parquet file is written. `H1_fast` came out all
  zero — checked `IH` directly, confirmed genuinely zero throughout this
  file (a Bitter-only run), not a computation bug.
- **Full suite**: 306/306 pass (`MPLBACKEND=Agg pytest tests -k hoop`,
  excluding `test_matplotlib.py` per the known hang).
- One `MAT_ISOLANT` material row was copied from `magnetdb.duckdb`
  (production, read-only) into `test-magnetdb.duckdb` (scratch) partway
  through — `test-magnetdb.duckdb` had none, and every site's geometry load
  requires one row for insulator material properties. Confirmed
  production-only, one-row copy; no other data touched.

## Known limitations / open items

- **`--check` mode — POSTPONED, must be revisited. This must work smoothly.**
  (`validate_fast_from_pupitre(..., check=True)` compares fast-path output
  against `bmap.getHoop()` row by row.) Status as of 2026-08-13:
  - The original crash (`KeyError: 'label'` — `bmap.getHoop()` has no
    `label` column, the real one is `num`) is **fixed** in
    `to_duckdb/stress_map.py`.
  - Once fixed, `--check` ran but gave near-zero reference values for
    Bitter. Traced to **three bugs in `getHoop()` itself**
    (`~/github/my-magnettools/Python/Bmap.py` — a *separate* repo, not
    `2026-m1-hifimagnet`): the same Helix `mid_elem` off-by-one as the bug
    fixed here, a more broken Bitter/Supra `mid_stack` (depended on the
    last stack index by coincidence, not `len(stack)`), and a total-field
    formula that double-counted Helix's field and never included Bitter's
    own. **All three are fixed** in that repo, plus a new `z0` parameter
    added to `getHoop()` (mirrors `z0_h`/`z0_b` here) and a current-state
    restoration bug fixed as well — but **none of this is deployed**: the
    installed package (`/usr/lib/python3/dist-packages/magnettools/`,
    root-owned) is a separate copy from the git source and needs
    reinstalling; nothing in that repo is committed either.
  - Even after that lands, `--check`'s own call site here needs updating:
    it doesn't currently pass any `z0` into `bmap.getHoop()`, so it won't
    be a true apples-to-apples comparison against the fast path (which
    does use `z0_h`/`z0_b`) until it does.
  - **Do not consider `--check` mode validated until**: (1) the
    `my-magnettools` fixes are installed, (2) this file's `--check` block
    is updated to pass `z0_h`/`z0_b` into `bmap.getHoop()`, and (3) it's
    re-run against real multi-section Bitter data and gives sane,
    non-near-zero agreement.
- **Supra** is out of scope. It has the same underlying native-section
  capability (`UMagnets()` supports `dblepancake`/`pancake`/`tape` detail
  levels) but currently always collapses to one value per part
  (`detail=None` path), so it doesn't hit the Bitter-style crash today.
  `z0_s` stays hardcoded to `0.0` in `validate_fast_from_pupitre`.
- **Per-magnet z0 is unverified against real misaligned data** — every real
  `site_magnets.z_offset` is currently `0.0`. The resolution logic
  (`resolve_z0_by_type`) is unit-tested with a synthetic non-zero fixture,
  but the full pipeline's behavior on an actually-misaligned site has not
  been (and currently cannot be) exercised end-to-end.
- `cmd_barchart`/`compute_hoop_at_currents` (wraps `bmap.getHoop()` directly)
  was not touched — it may have the same per-part-vs-per-plate question for
  Bitter, but it's a separate code path from `compute_hoop_stress_history`.
