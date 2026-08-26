# lag_test.py versions

Three standalone scripts for computing the time lag between pupitre and
pigbrother (overview/archive) current signals. All three share the same
core `get_lag()` (FFT cross-correlation on normalized derivatives) and the
same `Idcct1`/`Courant_A1` fallback to `Idcct3`/`Courant_A3` when the first
pair isn't available. They differ only in **how they find and load the
files being compared**.

Run with the project venv:

```bash
cd stage/dashboard/tests
../../../to_duckdb/venv-systempackages/bin/python3 <script>.py [options]
```

## lag_test_file.py — explicit files

Takes the pupitre and overview filenames directly on the command line and
loads them via `load_mrun`. Computes a single lag from that one file pair.

```bash
python3 lag_test_file.py \
  --fichier-pupitre "2025.12.02 - 14:30:46.txt" \
  --fichier-overview "M9_Overview_251202-1430.tdms" \
  --housing M9
```

- `--fichier-pupitre` (default: `"2025.12.02 - 14:30:46.txt"`)
- `--fichier-overview` (default: `"M9_Overview_251202-1430.tdms"`)
- `--housing` (default: inferred from `--fichier-overview`, e.g. `M9`)

## lag_test.py — database-driven

Looks up the `overview_records` DuckDB table for the row whose `filename`
matches `--fichier-overview`, and reads its `sources_pupitre`,
`sources_overview`, `sources_archive` file lists from there (no disk
scanning). Reports the lag two ways:

- **merged** — every file in each source list concatenated into one
  DataFrame, one lag computed for pupitre-vs-overview and one for
  pupitre-vs-archive.
- **not merged** — every pupitre file compared individually against every
  overview file and every archive file (one lag per file pair).

```bash
python3 lag_test.py --fichier-overview "M9_Overview_251202-1430.tdms"
```

- `--fichier-overview` (default: `"M9_Overview_251202-1430.tdms"`)
- `--housing` (default: the `housing` column from the matched DB row)

Database path defaults to the same convention as
`stage/dashboard/src/magnetdb_analysis.py`; override with:

```bash
export MAGNETDB_DB_PATH=/path/to/magnetdb.duckdb
```

## lag_test_discovery.py — disk discovery, no database

Builds an `OverviewRecord` via `process_overview_file`/`FileDiscovery`,
which scans the given data directories and auto-discovers the pupitre and
archive files associated with the overview file (by housing/timestamp
matching), without touching any database. Reports pupitre-vs-overview and
pupitre-vs-archive lag.

```bash
python3 lag_test_discovery.py \
  --fichier-overview "M9_Overview_251202-1430.tdms" \
  --pupitre-datadir /path/to/pupitre/data \
  --pigbrother-datadir /path/to/pigbrother/data
```

- `--fichier-overview` (default: `"M9_Overview_251202-1430.tdms"`; accepts a
  glob pattern, e.g. `"M9_Overview_2512*.tdms"` — every matching file is
  processed in turn)
- `--pupitre-datadir` (default: `DEFAULT_DATA_DIR`)
- `--pigbrother-datadir` (default: `DEFAULT_PIGBROTHER_DATA_DIR`)
- `--log-file` (default: `lag_test_discovery.log`, next to the script)

Note: `FileDiscovery` expects data organized in its usual directory layout
(not a flat folder of loose files) to find matches.

**Always quote `--fichier-overview` when it contains a `*`.** Unquoted, your
shell expands the pattern against your *current directory* before Python
ever sees it — if exactly one file there happens to match (e.g. the sample
file in this `tests/` folder), the script silently receives that one
resolved filename instead of the pattern, and only processes it. Quoting
(`--fichier-overview "M9_Overview_2512*.tdms"`) passes the literal pattern
through so the script's own glob (against the real data directory) runs
instead.
