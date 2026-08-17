# Site → Assembly rename: cross-package migration plan

**Status:** **Track A (Phases 1–7, this workspace) approved 2026-08-17** —
ready to execute, nothing yet implemented. Track B (separate repos) scope
corrected/expanded below (see Ecosystem map and Track B section);
execution intentionally deferred to its own future planning pass, not
part of this approval.

## Goal

Rename the "magnet assembly" concept — currently spelled `Site`/`MSite`
across the stack — to `Assembly`, consistently, everywhere it actually means
that concept. Do this without breaking: existing serialized `!<MSite>` YAML
geometry files (possibly present outside this repo), the live `.duckdb`
databases, or the upstream MagnetDB REST API contract this repo consumes as
a client (which is not ours to rename).

## Why this is trickier than a find/replace

Investigation (see per-package findings below) found that **"site" is not
one concept** — it's at least four, only one of which is the thing you want
renamed:

| # | What "site"/"Site" means | Where | Rename? |
|---|---|---|---|
| 1 | A full magnet geometry assembly (Insert+Bitter+Supra+Screens, e.g. `"M9"`) — the `MSite` class | `python_magnetgeo` | **Yes** — this is the source concept |
| 2 | The same assembly, as a DB row (`sites` table, `site_magnets` join, `site_name` FK on 5 other tables) | `to_duckdb` | **Yes** — downstream of #1 |
| 3 | The same assembly, in dashboard pages/labels/ids | `stage/dashboard`, `to_duckdb/dashboard` | **Yes** — downstream of #2 |
| 4 | The same assembly, as `MagnetRun.Site`/`getSite()`/`setSite()` ("name of the site in the magnetdb sense, e.g. `M9Ch1Lips`") | `python_magnetrun` | **Yes** — same concept, independently coupled |
| 5 | The magnet **bay/enclosure** (`"M8"`, `"M9"`, `"M10"`) — `MagnetRun.Housing`/`getHousing()`, `housing_config` table | `python_magnetrun`, `to_duckdb` | **No** — different concept, already correctly named `housing` |
| 6 | A **lab/geographic location** (`"grenoble"`, `"saclay"`) — `site=` param on `SimulationRun`/`BFieldRun` | `python_magnetrun` | **Rename, but not to `Assembly`** — see below, this is genuinely a different concept and needs its own word |
| 7 | The MagnetDB REST API's own vocabulary (`Site`/`SiteMagnet` Django models, `"site"`/`"site_id"`/`resource_type="site"` in JSON) | **`python_magnetdb`** (server, separate repo) and **`python_magnetapi`** (client library/CLI, separate repo) — both `Trophime`-owned, not third-party | **Yes, eventually** — corrected from an earlier draft of this plan, which wrongly assumed this was an external system. It isn't: it's your own server and client library, in sibling repos outside this workspace. See "Ecosystem map" below. |
| 8 | CSV column headers `Site` / `Magnet Sites` (proposals export) | `Data/proposals*.csv` | **No** — external export naming |
| 9 | `TODO.md`: "rename Site to housing_YYDDMM" | repo TODO | **Different, unrelated task** — renaming site *identifier values* to a date-based scheme, not the *concept*. Kept separate so it isn't conflated with this plan. |

Rows 1–4 (and 10, separately) are the actual scope of this migration. Rows
5, 8, 9 are explicitly **out of scope**. Row 7 is in scope conceptually but
lives in separate repos and is tracked as its own track below (Track B),
not executed as part of this workspace's changes.

## Ecosystem map (this workspace is one layer of a bigger system)

Investigation turned up three sibling repos, all under your own GitHub
account, not checked out inside `2026-m1-hifimagnet` but present on this
machine at `~/github/`:

- **`~/github/python_magnetdb`** (`git@github.com:Trophime/python_magnetdb`)
  — the real server: Django models + a FastAPI routes layer, backed by
  PostgreSQL, deployed via `docker-compose*-traefik-ssl.yml`. This is what
  `srv-data-install.lncmi.cnrs.fr` (or a successor domain) actually runs.
  It vendors `python_magnetgeo`, `python_magnetsetup`, and `python_magnetapi`
  as git submodules (`.gitmodules`), pointing at your own forks
  (`Trophime/python_magnetgeo` etc., which merge from a `MagnetDB` GitHub
  org) — the **same lineage** as this workspace's copies of those packages.
- **`~/github/python_magnetapi`** (`git@github.com:Trophime/python_magnetapi`)
  — "Python CLI and library for interacting with MagnetDB." This is the
  canonical client for `python_magnetdb`'s API: list/view/create/delete
  materials, parts, magnets, **sites**, records, servers, simulations;
  inductance/flow-param/hoop-stress computation. `python_magnetrun`'s own
  `requests/` subpackage and `python_magnetcooling/examples/flow_params.py`
  (in this workspace) look like an earlier, independently-evolved,
  partially-duplicated take on what `python_magnetapi` now does properly —
  worth knowing, out of scope to reconcile here.
- **`~/github/hifimagnet-projects`** (`git@github.com:Trophime/hifimagnet-projects`)
  — per-assembly config data (directories like `HL-34`, `M9Bitters`,
  `magnetdb.json/*.json`) that round-trips with the server (see
  `python_magnetdb/actions/generate_site_directory.py`, `seeds/seed-*.py`).
  Its own commit history already uses **"assembly (aka site)"** in several
  recent messages ("fix assembly (aka site) name", "remove records from
  assembly -- aka site -- config") — you've informally been leaning this
  direction there for months.
- **`~/github/python_magnetworkflows`** — a 4th ecosystem member, not found
  in the original draft of this plan. Feel++ coupled electromagnetic-
  thermal workflow package; its `.gitmodules` vendors `python_magnetapi`,
  `python_magnetcooling`, and `python_magnetunits` as submodules, all from
  the `MagnetDB` GitHub org. It is a consumer of `python_magnetapi`'s
  `site` vocabulary (same `otype="site"` pattern as this workspace's
  `python_magnetcooling/examples/flow_params.py`) and must be accounted
  for wherever Track B eventually renames `python_magnetapi` — see Track B
  below.

Also noted, out of scope: `python_magnetdb/to_duckdb/` is a stale/
prototype directory (`student.duckdb`, `streaming-data-extension.md`,
etc.) living inside the `python_magnetdb` repo, not referenced from that
repo's own README — an earlier, unrelated exploration, not this
workspace's `to_duckdb`. No action needed.

And critically, **as you noted**: `to_duckdb` (in this workspace) is a
demonstrator/prototype of `python_magnetdb`'s own schema and API — not an
independent design consuming a fixed external contract. That reframes the
earlier draft of this plan, which treated the "sites" JSON vocabulary as
something to translate at a boundary and leave alone. It shouldn't be left
alone — it should eventually match whatever `python_magnetdb` and
`python_magnetapi` end up calling things, since you control both ends and
`to_duckdb` exists specifically to mirror them.

### What "Site" looks like inside `python_magnetdb`

- `models/site.py`: Django model `Site` (`db_table = "sites"`) — `id`,
  `name`, `description`, `status`, `config_attachment` (FK), `metadata`,
  `created_at`, `updated_at`. Two properties,
  `geometry_config_to_json`/`geometry_config_to_yaml`, **directly import
  `from python_magnetgeo.MSite import MSite`** and construct an `MSite`
  instance server-side from the model's related `SiteMagnet` rows — this is
  the tightest coupling point in the whole ecosystem between the Django
  model and the geometry class.
- `models/site_magnet.py`: `SiteMagnet` (`db_table = 'site_magnets'`) — FKs
  `magnet`, `site`; `z_offset`/`r_offset`/`parallax`/`commissioned_at`/
  `decommissioned_at`/`metadata`. This is the authoritative schema
  `to_duckdb/schema.py`'s `sites`/`site_magnets` tables mirror.
- Four more models carry a `site = ForeignKey('Site', ...)`:
  `MeshAttachment`, `CadAttachment`, `Simulation`, `Record` — all need a
  matching FK rename.
- `routes/api/*.py`: ~10 files reference `Site`/`site`. Notably,
  `resource_type == "site"` is used as a **polymorphic discriminator string**
  in `simulations.py`, `visualisations.py`, `mesh_attachments.py`,
  `cad_attachments.py`. `routes/api/serializers.py` has a
  `_site_post_processor` function and a `{Site: _site_post_processor}`
  dispatch entry driving JSON response shape. `routes/api/home.py` has a
  dashboard-stats route counting `Site.objects...` by status.
- **Frontend, confirmed** (corrected from an earlier draft, which treated
  this as unconfirmed/external): the `lemon.magnetdb.local`/
  `manager.lemon.magnetdb.local` subdomains referenced in the dev README
  are **LemonLDAP::NG** (`tiredofit/lemonldap:2.0.24`, defined in
  `docker-compose-traefik-ssl.yml`) — a third-party SSO/auth gateway, not a
  frontend. The real frontend is `python_magnetdb/web/`: a Vue.js SPA
  (`magnetdb-webapp` container, built from the local `web/` directory),
  vendored directly inside the `python_magnetdb` repo rather than a
  separate checkout. Confirmed 19 files / 232 "site" occurrences in
  `web/src`, including a dedicated `services/siteService.js` and
  `views/sites/` — this is real, in-scope surface for Track B, larger than
  the original draft assumed, and it sends the `resource_type: "site"`
  strings above, so it must move in lockstep with the server rename.
- 24 existing Django migrations. A `Site`→`Assembly` rename needs a new one
  (`RenameModel`, `AlterField` for the 5 FKs above, `db_table` rename) —
  applied against what looks like a **live production database**, real
  stakes, unlike `to_duckdb`'s local `.duckdb` files.

### What "Site" looks like inside `python_magnetapi`

`mtype="site"` / `otype="site"` resource-type strings are pervasive:
`record.py` (`data["site"]`, `"Site '{name}' not found"` errors),
`magnet.py` (attaching a magnet to a site by name/id), `analysis/
inductances.py`, `analysis/flow_params.py` (near-identical to this
workspace's `python_magnetcooling/examples/flow_params.py` — same
`site["site"]["name"]`/`site["site_id"]` response shape found earlier in
`notebooks/site.json`/`magnet.json`). Renaming the server's `Site` model
without a matching client-library update breaks every one of these call
sites immediately, so these two repos must be renamed together, not
independently.

## Notable finding, now resolved

`stage/dashboard/src/pages/site_stats.py:14` registers the page as
`name="Assembly stats"` in the nav, while every other identifier in that
same file (DataFrame columns, element ids like `site-stats-site-filter`,
visible text like `f"Sites: {total_sites}"`) still says "Site".
`git log --follow -- stage/dashboard/src/pages/site_stats.py` shows this
was **not** a half-finished rename in progress: `name="Assembly stats"`
has been present since the file's very first commit (`94a027d`, 2026-07-28,
"add stats to dashboard"). It was simply a friendlier user-facing label
chosen at creation time and never propagated to the code beneath it — no
special handling needed beyond the ordinary Phase 4 sequencing note below.

## Per-package findings

**`python_magnetgeo`** (source of the concept)
- `python_magnetgeo/python_magnetgeo/MSite.py`: `class MSite(YAMLObjectBase)`,
  `yaml_tag = "MSite"`. Serializes with a literal `!<MSite>` YAML tag and a
  `__classname__: "MSite"` JSON field (via the shared `YAMLObjectBase`
  registry in `base.py`, which auto-registers `cls.yaml_tag` — dual-tag
  backward compat is cheap to add here).
- Referenced in `python_magnetgeo/python_magnetgeo/__init__.py` at 3 spots
  (import, `__all__`, an internal class list used by the
  `check-magnetgeo-yaml` console script).
- Only one committed data file uses the tag:
  `python_magnetgeo/tests.cfg/msite1.yaml`. No production geometry YAML in
  this repo uses it — but we can't grep data that lives outside the repo
  (e.g. `hifimagnet-projects`, your local data dirs), so read-compat for the
  old tag is cheap insurance, not paranoia.
- `python_magnetgeo/tests/test_msite_refactor.py` (413 lines, entirely about
  `MSite`) and other tests reference the class directly — needs a matching
  rename, not just a passthrough.

**`python_magnetsetup`** (consumer, geometry setup/meshing)
- Imports `MSite` in `setup.py` three times (lines 341, 392, 484) — **all
  three are dead code**, never used for `isinstance`/attribute access.
  Actual site-vs-magnet dispatch is structural (`"geom" in confdata`), not
  type-based. Cheap to clean up.
- `ana.py:447` writes `out.write("!<MSite>\n")` — a **hardcoded literal
  string**, not derived from `MSite.yaml_tag`. This is the one place a
  magnetgeo rename can silently drift out of sync if not updated in
  lockstep (recommend deriving it from the class's `yaml_tag` attribute
  going forward, to prevent this exact class of bug in the future).
- `ana.py:476` exposes `--msite` as an `argparse` flag (not an installed
  console script — no `[project.scripts]` entries exist in this package at
  all — so blast radius is direct-invocation callers only).
- Function names `msite_setup`/`msite_simfile` are internal, safe to rename
  freely. No YAML/JSON template in the package embeds a "site" key.

**`to_duckdb`** (largest surface, ~500+ occurrences across the package)
- `schema.py`: table `sites`, join table `site_magnets`, and `site_name` FK
  columns on `experiments`, `operationaldata`, `overview_records`, and two
  tables whose *names themselves* contain "site":
  `op_site_bin_stats`, `exp_site_bin_stats`.
- `crud.py`: `insert_site`, `insert_site_magnets`, `update_site_magnet`,
  `attach_site_to_overview_record`, `view_sites`, `view_site`, `delete_site`,
  and the `site_name` parameter used pervasively.
- `magnetdb.py`: **user-facing CLI** — `site` is a top-level entity with
  `add`/`view`/`delete`/`update-magnet` subcommands, plus a `--site` flag
  used across several other subcommands; `_validate_site`/`_add_site`
  helpers.
- `stress_map.py`: the one file that bridges both renames —
  `from python_magnetgeo.MSite import MSite` (line 327), builds an `MSite`
  instance out of `sites`/`site_magnets` DB rows (line 380). Must land after
  `python_magnetgeo`'s rename lands.
- `to_duckdb/dashboard/pages/magnets.py` (a second, separate mini-dashboard,
  distinct from `stage/dashboard/` — flagged in `PROJECT_STRUCTURE_PLAN.md`
  as a likely duplicate to consolidate later): also has `site_name`/"Site"
  labels. Low priority given that consolidation is already planned
  separately.
- Import scripts (`import_housing_summary.py` etc.) read upstream JSON that
  already uses `"site"`/`"site_magnets"` as its own field names (confirmed
  against `notebooks/site.json`, `notebooks/magnet.json` — real MagnetDB API
  exports). These must keep reading the upstream `"site"` key and map it
  onto the renamed internal column at import time — same pattern already
  used for `housing`.
- Test surface: `tests/test_add_site.py`, plus `site`/`site_name` references
  throughout `test_crud.py`, `test_magnetdb.py`, `test_compute_hoop_stats.py`.
- Stale/exploratory, not imported by production code, low priority:
  `to_duckdb/marimo/select_site.py` (+ `select_site_note.md`),
  `to_duckdb/test_site_stats.py`/`.ipynb`.
- `stage/dash_site_stats.py` is dead/orphaned (only referenced from a doc
  comment, not imported anywhere) — candidate to delete rather than rename,
  separately from this plan.

**`stage/dashboard`**
- `src/pages/site_stats.py`: page module, DataFrame columns, element ids
  (`site-stats-site-filter`, `site-stats-table`), visible text
  (`f"Sites: {total_sites}"`) — see the nav-label mismatch flagged above.
- `src/magnetdb_analysis.py`: `get_all_sites`, `get_magnet_types_for_site`,
  `get_files_for_site`, `get_overview_records_for_site`, `_site_sort_key`,
  `_SITE_DATE_RE` — direct DB queries against `sites`/`site_magnets`.
- `src/pages/home.py`, `src/pages/comparison.py`: user-facing dropdown label
  `"1. Choose Site :"`, element id `dd-site-compare`, and a `?site=` URL
  query param used for cross-page links.
- Note: `PLAN_dashboard_hierarchy_rework.md` (currently awaiting separate
  approval, not yet implemented) plans further edits to `site_stats.py` and
  a not-yet-existing `experiment_links.py`. That plan and this one will
  touch the same file — sequencing matters (see Approach, step 4).

**`python_magnetrun`** (independent of the above — confirmed **zero**
`import python_magnetgeo` anywhere in this package)
- `MagnetRun.py`: `self.Site`, `getSite()`/`setSite()` (lines ~361–379),
  docstring explicitly: *"name of the site in the magnetdb sense (e.g.
  `M9Ch1Lips`)"* — this is the true match for concept #1/#4. Sits alongside
  `Housing`/`getHousing()`/`setHousing()`, which is genuinely different and
  stays as-is.
- `cli_args.py`: `--site` flag (distinct help text from `--housing`).
- `requests/MRecord.py`: `site` field, `getSite()`/`setSite()` — likely
  serializes into JSON posted to the upstream MagnetDB REST API. **Check
  before renaming**: if the wire payload key is literally `"site"`, keep
  that JSON key and rename only the Python-side attribute/accessor, same
  boundary pattern as `to_duckdb`'s import layer.
- `requests/cli.py`: `db_Sites` dict, `site_names`, comment *"actually list
  of site in magnetdb sens"* — near-literal MSite records, builds the
  same shape by hand.
- Stale docs, not code — found but not in scope to fix as part of this
  rename, only noted because they'll otherwise mislead whoever reads them
  next: `analysis/README.md`, `REFACTORING_PROMPT.md`,
  `CONTINUATION_PROMPT.md` describe a `SiteConfig`/`site_config.py`/
  `<Housing>-site-config.json` that **doesn't exist** — the real code
  already renamed this to `HousingConfig`/`housing_config.py`/
  `<Housing>-housing-config.json` at some point and the docs were never
  updated. Good precedent that this kind of rename has been done here
  before without incident.
- Test surface: 9 files, ~65 hits, including direct assertions on
  `.Site`/`getSite`/`setSite` (`tests/test_magnetrun.py`) and `site="grenoble"`
  usage for the *separate* lab-location meaning (`tests/test_protocol.py`)
  — don't touch the latter.
- Existing precedent for staged renames in this exact package:
  `pyproject.toml`'s `[project.scripts]` already keeps old console-script
  names as "deprecated aliases — keep for one release cycle, then remove"
  (e.g. `python-magnetrun` aliasing `magnetrun`). Reuse this pattern.

**`python_magnetcooling`** (small, downstream of `python_magnetrun`)
- `examples/heatexchanger_primary.py`, `python_magnetcooling/clawtest1.py`:
  `--site` CLI flag, calls `mrun.getSite()` — follows whatever
  `python_magnetrun` does.
- `examples/flow_params.py`: talks to the upstream REST API directly using
  its own vocabulary (`otype="site"`, `site["site_id"]`) — **leave this
  alone**, it's concept #7 (external API), not #1/#4.

## Files affected (create/edit, by phase)

**Phase 1 — `python_magnetgeo`** (expanded detail — this is the foundation
everything else depends on)

*How the registration machinery actually works, confirmed by reading
`base.py`, `deserialize.py`, and `__init__.py` directly (not assumed):*

`YAMLObjectBase.__init_subclass__` (`base.py:372-439`) runs once, when the
class body is first executed at import time (not per-instance). For a class
with `yaml_tag = "MSite"` it does three independent things, which matters
because backward compat needs to handle each separately:

1. `cls._class_registry[cls.__name__] = cls` **and**
   `cls._class_registry[cls.yaml_tag] = cls` — one shared dict, keyed by
   both the Python class name and the tag string. For `MSite` these
   collapse to the same key today (`"MSite"` either way), which is exactly
   why this dict is the thing to alias for backward compat.
2. `yaml.add_constructor(cls.yaml_tag, constructor)` — registers the
   `!<MSite>` → object constructor with **PyYAML's own global tag
   registry**, a *separate* mechanism from `_class_registry` above, keyed
   purely by tag string.
3. `yaml.add_representer(cls, representer)` — registers the object → YAML
   writer, keyed by **the Python class object itself**, not a string. Since
   there will only ever be one class (`Assembly`), there is exactly one
   representer, and it always writes `cls.yaml_tag`. This is why a clean
   rename can't accidentally keep *writing* the old tag — only *reading* it
   needs an explicit compat shim.

Separately, `deserialize.unserialize_object()` (`deserialize.py:83`) resolves
JSON's `"__classname__"` field via `YAMLObjectBase.get_class(clsname)`, i.e.
a lookup into the *same* `_class_registry` from point 1. So aliasing that
one dict is enough to cover **both** old-JSON-file reads and any code doing
`get_class("MSite")` — only the PyYAML tag registry (point 2) needs a
second, separate line.

*Concrete steps:*

1. `git mv python_magnetgeo/python_magnetgeo/MSite.py
   python_magnetgeo/python_magnetgeo/Assembly.py`.
2. In `Assembly.py`: rename `class MSite` → `class Assembly`; `yaml_tag =
   "MSite"` → `"Assembly"`; module docstring `"Provides definition for
   Site:"` → `"...for Assembly:"`; the two literal debug-print prefixes
   `"MSite/get_channels:"` (line 182) and `"MSite/get_names: ..."` (line
   269) → `"Assembly/..."`; every `MSite(...)`/`msite = ...` occurrence in
   docstring `Example:` blocks (roughly a dozen, throughout the file) →
   `Assembly(...)`/`assembly = ...`, purely cosmetic but the file is
   otherwise almost entirely about this rename anyway.
3. Immediately after the class body, add the backward-compat shim (~8
   lines, self-contained, easy to delete later in one place):
   ```python
   # Backward compatibility: accept files serialized under the old name.
   # Safe to remove once no `!<MSite>`-tagged YAML or `"__classname__":
   # "MSite"` JSON is expected to exist anywhere (including outside this repo).
   def _legacy_msite_constructor(loader, node):
       values = loader.construct_mapping(node, deep=True)
       return Assembly.from_dict(values)

   yaml.add_constructor("MSite", _legacy_msite_constructor)
   YAMLObjectBase._class_registry["MSite"] = Assembly
   ```
   (needs `import yaml` added to this file — currently not imported here,
   only in `base.py`). This covers old-format reads for both YAML and JSON
   without touching `base.py`'s generic machinery at all.
4. `__init__.py` — three exact spots (line numbers as of this
   investigation, will drift slightly as edits land):
   - Line 66: `from .MSite import MSite` → `from .Assembly import Assembly`.
   - Line 115 (`__all__` list): `"MSite"` → `"Assembly"`.
   - Line 175 (`verify_class_registration()`'s `expected_classes` list):
     `"MSite"` → `"Assembly"`.
   - Optionally, right after the import: `MSite = Assembly  # deprecated
     alias — remove after one release`. This is a **plain object alias**
     (not a wrapping proxy that emits `DeprecationWarning`) — deliberately,
     because `python_magnetdb/models/site.py` does `isinstance`-free direct
     construction (`MSite(name=..., magnets=..., ...)`) and this form keeps
     `MSite is Assembly` true, so any `isinstance(x, MSite)` check anywhere
     downstream keeps working identically. A warning-emitting wrapper would
     break that identity. If you want the deprecation to be *loud*
     (visible warnings on use) rather than silent-but-compatible, say so —
     it's a real tradeoff, not an oversight.
5. `visualization.py:153` — docstring-only: `"...(Insert, MSite, etc.)..."`
   → `"...(Insert, Assembly, etc.)..."`.
6. Tests: rename `tests/test_msite_refactor.py` →
   `tests/test_assembly_refactor.py`; update all `MSite`/`msite` references
   (imports, constructions, the `parsed['__classname__'] == 'MSite'`
   assertion → `'Assembly'`). **Add**, don't just rename away, two new
   regression tests for the compat shim itself:
   - loading `tests.cfg/msite1.yaml` (existing fixture, untouched, still
     tagged `!<MSite>`) returns an `Assembly` instance with correct
     attributes.
   - a hand-built dict with `"__classname__": "MSite"` round-trips through
     `unserialize_object()` into an `Assembly` instance.
7. Fixtures: keep `tests.cfg/msite1.yaml` exactly as-is — it's now the
   dedicated regression fixture for point 6 above, not stale test data.
   Add `tests.cfg/assembly1.yaml` (identical content, `!<Assembly>` tag) for
   the normal forward-going test path.

*Confirmed low-risk, no extra work needed:* `utils.py::getObject()`
dispatches purely on file extension (`.json` → `loadJson`, `.yaml`/`.yml` →
`loadYaml`) with no hardcoded class names anywhere in the dispatch path;
`examples/check_magnetgeo_yaml.py` (the installed `check-magnetgeo-yaml`
console script) is fully registry-driven, no class names hardcoded. Neither
needs touching. Also confirmed: `MSite` is imported in exactly one place
inside the whole `python_magnetgeo` package (`__init__.py:66`) — the class
body itself has no other internal cross-file coupling.

*Noticed in passing, out of scope for this rename:* `MSite.__init__`
(lines 103-108, unchanged by this rename) has a pre-existing oddity — it
iterates the `magnets` parameter while also appending resolved objects back
onto that same list (`magnets.append(...)` inside `for magnet in magnets:`)
instead of appending to `self.magnets` directly. It happens to still
terminate correctly (Python's list iteration picks up appended items), but
it's fragile and worth a second look someday. Flagging only because Phase 1
touches nearly every line of this file anyway — not fixing it here to avoid
mixing an unrelated correctness fix into a rename.

**Phase 2 — `python_magnetsetup`**
- Edit: `setup.py` — delete the 3 dead `MSite` imports (or update to
  `Assembly` if you'd rather keep them for readability); rename
  `msite_setup`→`assembly_setup`, `msite_simfile`→`assembly_simfile`.
- Edit: `ana.py` — stop hardcoding `"!<MSite>\n"`; derive the tag string
  from `python_magnetgeo.Assembly.yaml_tag` instead (fixes the drift risk
  noted above); rename `--msite` CLI flag → `--assembly` (keep `--msite` as
  a deprecated alias for one cycle, argparse supports this via
  duplicate `dest`).

**Phase 3 — `to_duckdb`**
- Create: `to_duckdb/migrations/migrate_rename_site_to_assembly.py` —
  follows the existing `migrate_*.py` pattern (`--db`, `--dry-run`).
  `ALTER TABLE sites RENAME TO assemblies`, `ALTER TABLE site_magnets RENAME
  TO assembly_magnets`, `ALTER TABLE assembly_magnets RENAME COLUMN
  site_name TO assembly_name`, same column rename on `experiments`,
  `operationaldata`, `overview_records`; `ALTER TABLE op_site_bin_stats
  RENAME TO op_assembly_bin_stats` and same for `exp_site_bin_stats`.
  DuckDB's `RENAME` DDL is metadata-only, so this is fast and safe to run
  against both `test-magnetdb.duckdb` and `magnetdb.duckdb`.
- Edit: `schema.py` — update all `CREATE TABLE`/column definitions to the
  new names (so fresh DBs match what the migration produces on existing
  ones).
- Edit: `crud.py` — rename all `*site*` functions/params to `*assembly*`.
- Edit: `magnetdb.py` — rename the `site` CLI entity → `assembly` (subparser
  `add`/`view`/`delete`/`update-magnet`), `--site` flag → `--assembly`;
  keep `site` as a hidden/deprecated alias subcommand for one cycle if you
  run this CLI from any cron jobs or saved scripts today (confirm — see
  open questions).
- Edit: `stress_map.py` — update the `MSite`/`Assembly` import and
  construction to match Phase 1's rename; must land after Phase 1.
- Edit: import scripts (`import_housing_summary.py` etc.) — for now, keep
  reading upstream JSON's `"site"`-shaped records (that's what the live
  `python_magnetdb` server still emits until Track B below lands), mapping
  onto the renamed `assembly_name` column. This mapping becomes a
  straight passthrough once Track B renames the server's own vocabulary —
  not a permanent translation layer, just a temporary one until both ends
  match.
- Edit: tests (`test_add_site.py` → `test_add_assembly.py`, plus
  `site`/`site_name` references in `test_crud.py`, `test_magnetdb.py`,
  `test_compute_hoop_stats.py`).
- Leave for now (separately tracked): `to_duckdb/dashboard/pages/magnets.py`,
  `to_duckdb/marimo/select_site.py`, `to_duckdb/test_site_stats.py`/`.ipynb`,
  `stage/dash_site_stats.py`.

**Phase 4 — `stage/dashboard`**
- Edit/rename: `src/pages/site_stats.py` → `assembly_stats.py`; ids,
  DataFrame columns, visible text → `assembly`/`Assembly`.
- Edit: `src/magnetdb_analysis.py` — rename all `*_site*` query functions.
- Edit: `src/pages/home.py`, `src/pages/comparison.py` — dropdown label,
  element ids, `?site=` → `?assembly=` URL param (consider accepting both
  query param names for a transition period, since old links may be
  bookmarked/shared).
- Coordinate with `PLAN_dashboard_hierarchy_rework.md`: that plan (awaiting
  its own approval) also edits `site_stats.py`. **Sequencing decision:**
  land this rename's Phase 4 first — `PLAN_dashboard_hierarchy_rework.md`
  isn't approved yet and doesn't block Track A, so `site_stats.py` is only
  touched once, under the new `Assembly` vocabulary, before that plan's
  edits land on top of the renamed version.

**Phase 5 — `python_magnetrun`** (no hard dependency on Phases 1–4; can run
in parallel)
- Edit: `MagnetRun.py` — `Site`/`getSite`/`setSite` → `Assembly`/
  `getAssembly`/`setAssembly`; leave `Housing`/`getHousing`/`setHousing`
  untouched.
- Edit: `cli_args.py`, `cli.py` — `--site` → `--assembly` (deprecated alias
  for one cycle, per this package's existing convention).
- Edit: `requests/MRecord.py`, `requests/cli.py` (`db_Sites`→
  `db_Assemblies`, `site_names`→`assembly_names`) — **first confirm the
  upstream API wire key**; if MagnetDB's REST API expects `"site"` in the
  POST payload, keep that JSON key literally and rename only the Python
  attribute/accessor around it.
- Edit: `simulation/simulation_run.py`, `bfield/bfield_run.py` — rename the
  `site` param to **`location`** (confirmed decision — keeps the field for
  whatever it was originally meant for, under a name that doesn't collide
  with the `Assembly` concept). Investigation finding: this param looks
  like **unused placeholder scaffolding**, not live functionality — its
  only non-docstring occurrences anywhere in the package are 3 call sites
  in `tests/test_protocol.py` (`site="grenoble"`, `site="saclay"`),
  introduced in the single commit that scaffolded both classes (`fd83fe5
  start working on SimulationRun and BFieldRun`); no production code path
  constructs either class with a real value. Update those 3 test call
  sites to `location=` at the same time.
- Leave untouched: `HousingConfig`/`housing_config.py` (already correctly
  named, confirmed — `housing` means the same bay/enclosure concept in both
  `python_magnetrun` and `to_duckdb`).
- Optionally fix (separate, low-risk cleanup, not required for this
  rename): the stale `SiteConfig`/`site_config.py` references in
  `analysis/README.md`, `REFACTORING_PROMPT.md`, `CONTINUATION_PROMPT.md` —
  update to reflect the already-real `HousingConfig` naming while you're in
  the area.
- Edit tests: `tests/test_magnetrun.py` and the ~8 other files asserting
  `.Site`/`getSite`/`setSite`.

**Phase 6 — `python_magnetcooling`**
- Edit: `examples/heatexchanger_primary.py`, `clawtest1.py` — `--site` →
  `--assembly`, `mrun.getSite()` → `mrun.getAssembly()` (depends on Phase 5
  landing first).
- Leave untouched: `examples/flow_params.py` (talks to upstream API
  directly using its own vocabulary).

**Phase 7 — cleanup (low priority, fate confirmed)**
- **Delete** `stage/dash_site_stats.py` — confirmed dead code, not
  imported anywhere.
- **Rename** the rest for vocabulary consistency, deferring their
  eventual consolidation to the separately-planned dashboard-consolidation
  work in `PROJECT_STRUCTURE_PLAN.md`: `to_duckdb/marimo/select_site.py`
  (+ `select_site_note.md`), `to_duckdb/test_site_stats.py`/`.ipynb`,
  `to_duckdb/dashboard/pages/magnets.py` (the duplicate mini-dashboard).
  None of these are on the critical path.

## Track B — separate repos, backport when ready (not executed by this plan)

Per your note, these live outside this workspace and get backported "at
some point," not necessarily now. Recorded here so Track A's naming choices
are chosen to already match what Track B will eventually use — the goal is
to rename once, not rename `to_duckdb` now and rename it *again* later when
the real server catches up.

**`python_magnetdb`** (`~/github/python_magnetdb`)
- `models/site.py` → rename `Site` → `Assembly` (Django model, `db_table`
  `"sites"` → `"assemblies"`); update the `MSite`/`Assembly` import in
  `geometry_config_to_json`/`geometry_config_to_yaml` to match Phase 1's
  `python_magnetgeo` rename — bump the vendored submodule pointer first.
- `models/site_magnet.py` → `SiteMagnet` → `AssemblyMagnet`, `db_table`
  `'site_magnets'` → `'assembly_magnets'`.
- Rename the `site` FK on `MeshAttachment`, `CadAttachment`, `Simulation`,
  `Record` → `assembly`.
- `routes/api/*.py`: rename `resource_type == "site"` dispatch strings (in
  `simulations.py`, `visualisations.py`, `mesh_attachments.py`,
  `cad_attachments.py`) → `"assembly"` — **first confirm nothing outside
  this codebase (e.g. a frontend at `lemon.magnetdb.local`, not found under
  `~/github`) sends the old string**, or add a transition period accepting
  both. `serializers.py`'s `_site_post_processor` → rename + update the
  dispatch table; `home.py`'s dashboard-stats route.
- New Django migration: `RenameModel`, matching `AlterField`s for the 5 FKs
  above, `db_table` renames. This runs against a live production database —
  treat with the same care as any production schema migration (backup
  first, test against a copy, plan for a maintenance window if this DB
  serves other live consumers).

**`python_magnetapi`** (`~/github/python_magnetapi`)
- Must be renamed **together with** `python_magnetdb`, not before or a
  meaningful lag after — every `mtype="site"`/`otype="site"` call site
  (`record.py`, `magnet.py`, `analysis/inductances.py`,
  `analysis/flow_params.py`) breaks the moment the server stops
  recognizing the old resource-type string.
- Consider, while in the area (optional, separate from the rename itself):
  this package is functionally very close to
  `python_magnetcooling/examples/flow_params.py` and `python_magnetrun`'s
  `requests/` subpackage in *this* workspace — worth a follow-up
  conversation about whether those should just depend on `python_magnetapi`
  instead of maintaining parallel implementations. Not part of this rename.

**`python_magnetdb/web/`** (frontend, vendored inside the server repo —
found this session, not in the original draft)
- Vue.js SPA (`magnetdb-webapp` container). Confirmed 19 files / 232
  "site" occurrences in `web/src`, including `services/siteService.js` and
  `views/sites/`. Must be renamed in the same coordinated pass as
  `python_magnetdb`/`python_magnetapi` — it's the thing actually sending
  the `resource_type: "site"` strings the server-side routes dispatch on.

**`python_magnetworkflows`** (`~/github/python_magnetworkflows`, found this
session, not in the original draft)
- Feel++ coupled electromagnetic-thermal workflow package. Vendors
  `python_magnetapi`/`python_magnetcooling`/`python_magnetunits` as
  submodules from the `MagnetDB` org — a 4th consumer of
  `python_magnetapi`'s `site` vocabulary. Needs the same lockstep-renaming
  treatment as `python_magnetcooling/examples/flow_params.py` in this
  workspace: leave alone until Track B renames the server/client
  vocabulary, then update together.
- Separately, its **own** code (not just the vendored submodules) hardcodes
  `"MSite"`/`"MSite_Tout"` as literal dict/DataFrame column keys in
  `commissioning.py:141,193-194`, `export.py:36,222`, and `error.py:52,482`
  — same class of drift risk already flagged for `python_magnetsetup/ana.py`
  in Phase 2 (a hardcoded string, not derived from the class's name/tag).
  When this repo is eventually touched, these become `"Assembly"`/
  `"Assembly_Tout"`.

### Other consumers of `python_magnetgeo`'s `Assembly` rename (separate
repos, checked this session — not part of the original draft)

These depend on Phase 1's class rename specifically (concept #1: the
geometry assembly class itself), not on the MagnetDB API vocabulary above.
Unlike `python_magnetsetup` in Track A (whose `MSite` imports are dead
code), the two mesh-generation consumers below have **real, load-bearing**
coupling — `isinstance(x, MSite)` checks and dedicated `MSite`-named
modules — so Phase 1's plain-alias design (`MSite = Assembly`, preserving
object identity) matters here too: it keeps these `isinstance` checks
working unchanged even before either repo is touched.

- **`python_magnetgmsh`** (`~/github/python_magnetgmsh`) — mesh-generation
  package, vendors `python_magnetgeo` as a submodule (own fork,
  `branch = refactor_claude`). Real usage: `isinstance(Object, MSite)`
  checks in `python_magnetgmsh/m3d/MeshData.py:123`,
  `axi/MeshAxiData.py:124`, `axi/Air.py:21`; a dedicated
  `axi/MSite.py` module (`gmsh_box`, `gmsh_ids`, `gmsh_bcs` functions
  taking an `MSite` positional argument); `cfg.py`'s `MSite_Gmsh()`
  function and `ObjectType = MSite | Bitters | Supras | ...` union type;
  a CLI dispatch dict keyed by the `MSite` class in `cli.py`. When this
  repo is touched: rename `axi/MSite.py` → `axi/Assembly.py`,
  `MSite_Gmsh` → `Assembly_Gmsh`, and the `MSite` type-union/dispatch
  entries, matching Phase 1's vocabulary.
- **`hifimagnet.salome`** (`~/github/hifimagnet.salome`) — the Salome
  CAD/mesh-generation plugin. `HIFIMAGNET/src/hifimagnet-salome/
  generators/msite.py` implements `HIFIMAGNET_GenerateMSite`, imported via
  `from python_magnetgeo.MSite import MSite`; `example_cli_main.py` has the
  same `ObjectType = MSite | Bitters | ...` union and class-keyed dispatch
  dict pattern as `python_magnetgmsh` above. Same treatment when touched:
  `generators/msite.py` → `generators/assembly.py`,
  `HIFIMAGNET_GenerateMSite` → `HIFIMAGNET_GenerateAssembly`.
- **`magnet-scipy`** (`~/github/magnet-scipy`) — checked, **no** `site`/
  `MSite` references found anywhere in the package (RL-circuit/PID-control
  simulation, unrelated domain). Not affected by this rename; listed here
  only because it was asked about.
- **`hifimagnet.paraview`** (`~/github/hifimagnet.paraview`) — checked,
  one incidental hit: a commented-out `"site"` entry in an argparse
  `choices` list (`scripts/display_results_v0.1.py:79`), dead code, not
  live. Negligible; no action needed.

**`hifimagnet-projects`** (`~/github/hifimagnet-projects`)
- Data files (`magnetdb.json/*.json`, per-assembly directories) don't
  literally use a `"site"` key (confirmed by inspection — they use `name`,
  `housing`, `magnets`, `commissioned_at`, etc.), so no field rename is
  needed there. What's worth finishing, given your commit history already
  calls these "assembly (aka site)": deciding on consistent terminology in
  new commit messages/scripts (e.g. `check_duplicate_records.py`,
  `fix_housing_date.py` in `magnetdb.json/`) going forward, once `Assembly`
  is the settled term everywhere else.

## Suggested order

**Track A (this workspace, can start now):** Phases 1 → 2 → 3 → 4 have a
real dependency chain (each consumes the one before it, via
`stress_map.py` and the dashboard's DB queries). Phase 5 (and its
follow-on, Phase 6) has zero coupling to `python_magnetgeo` and can be done
independently, in parallel, by a different session/person if useful. Phase
7 is cleanup, do whenever.

**Track B (separate repos):** independent of Track A's execution — you
could do Track B first, last, or never, and Track A still works, since
`to_duckdb`'s import scripts translate at the boundary either way (see
Phase 3). The only thing that must be shared between the two tracks is the
**vocabulary decision** (`Assembly`, `assembly_name`, `assemblies`,
`assembly_magnets`) — pick it once, in Phase 1 of Track A, and reuse it
verbatim in Track B whenever that happens, so the eventual backport is a
mechanical rename rather than a second design decision.

## Backward-compatibility strategy

Mirrors patterns already present in this repo rather than inventing new
ones:
- **YAML tag / JSON `__classname__`**: dual-register old and new tag in
  `python_magnetgeo`'s existing class registry — old files keep loading
  indefinitely (registry lookup is cheap, no reason to ever remove read
  support unless you're sure no old file exists anywhere).
- **Python API**: keep a deprecated alias (`MSite = Assembly`,
  `getSite = getAssembly` with a `DeprecationWarning`) for one release
  cycle, same as `python_magnetrun/pyproject.toml`'s existing "deprecated
  aliases — keep for one release cycle, then remove" console-script
  entries.
- **CLI flags/subcommands**: keep the old flag/subcommand name as a
  deprecated alias for one cycle, same convention.
- **DB schema**: `ALTER TABLE ... RENAME` (metadata-only in DuckDB, cheap
  and reversible) rather than copy-and-drop.
- **MagnetDB REST API** (`python_magnetdb`/`python_magnetapi`): *not*
  permanently external — corrected from an earlier draft. Translate at the
  `to_duckdb` import boundary only as a **temporary** measure until Track B
  (above) renames the server and client library to match; then the
  translation collapses into a passthrough.
- **Proposals CSV** (`Data/proposals*.csv`): genuinely external export
  naming, never renamed.

## Assumptions & open questions

**Resolved:**
- Target name: **`Assembly`** (dropping the `M` prefix from `MSite`) —
  confirmed.
- `Housing` in `python_magnetrun` = `housing` in `to_duckdb`, same concept,
  stays as-is — confirmed.
- `SimulationRun`/`BFieldRun`'s `site=` param → renamed to **`location`**
  (see Phase 5) — confirmed 2026-08-17.
- MagnetDB API vocabulary (`python_magnetdb`/`python_magnetapi`) is in
  scope, not external — confirmed, now Track B above.
- `site_stats.py`'s `name="Assembly stats"` nav label — confirmed not an
  in-progress rename; present since the file's first commit (see "Notable
  finding, now resolved" above). Ordinary Phase 4 sequencing applies.
- Deprecation-alias window — **one release cycle, everywhere in Track A**
  (YAML/JSON compat, Python aliases, CLI flags), mirroring the existing
  `python_magnetrun/pyproject.toml` precedent — confirmed 2026-08-17. Track
  B's Django migration is a separate, bigger decision (live production DB
  migration, not just a Python alias), to be made when Track B is actually
  scheduled.
- CLI/cron muscle-memory: checked — no crontab exists for this user, and no
  system cron references `magnetdb.py` or `python_magnetapi`. Not a
  blocker for keeping the deprecation window at one cycle in either place.
- Frontend for `python_magnetdb`: confirmed to exist, and it's
  `python_magnetdb/web/` (vendored in-repo, not a separate `~/github`
  checkout as originally assumed) — see Ecosystem map and Track B above.
  `lemon.magnetdb.local` is unrelated (LemonLDAP::NG, a third-party SSO
  gateway).
- Track B scheduling — **deferred to a separate future dedicated plan**,
  not part of this approval. This session's corrections (the `web/`
  frontend and `python_magnetworkflows` findings above) keep that future
  plan's scope accurate in the meantime.
- Phase 7 cleanup targets — confirmed: delete `stage/dash_site_stats.py`
  (dead code), rename the rest (`select_site.py`, `test_site_stats.py`/
  `.ipynb`, `to_duckdb/dashboard/pages/magnets.py`) for consistency,
  deferring their consolidation fate to `PROJECT_STRUCTURE_PLAN.md`'s
  separate dashboard work.
