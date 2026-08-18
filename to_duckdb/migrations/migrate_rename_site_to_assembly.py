"""
Rename the sites/site_magnets vocabulary to assemblies/assembly_magnets.

DuckDB refuses to ALTER RENAME a table or column that participates in a
foreign key relationship, and has no ALTER TABLE DROP CONSTRAINT support to
remove the FK first (tested against 1.5.2) — so this can't be done with
in-place ALTER statements like the other migrate_*.py scripts in this
directory. Instead it rebuilds the whole database via EXPORT DATABASE
(dumps every table to Parquet plus a generated schema.sql, in FK-safe
dependency order) / IMPORT DATABASE (recreates everything from that dump),
rewriting the generated schema.sql to the new table/column names in
between.

Renames: sites -> assemblies, site_magnets -> assembly_magnets,
site_name -> assembly_name (wherever it's a column), op_site_bin_stats ->
op_assembly_bin_stats, exp_site_bin_stats -> exp_assembly_bin_stats.

Never modifies --db: writes a new database file at --out. Swapping the
migrated file in for the original is a separate, deliberate step left to
the caller.
"""

import argparse
import re
import sys
import tempfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DEFAULT_DB

RENAMES: list[tuple[str, str]] = [
    (r"\bsite_magnets\b", "assembly_magnets"),
    (r"\bsites\b", "assemblies"),
    (r"\bsite_name\b", "assembly_name"),
    (r"\bop_site_bin_stats\b", "op_assembly_bin_stats"),
    (r"\bexp_site_bin_stats\b", "exp_assembly_bin_stats"),
]

CHECKED_TABLES = [
    ("sites", "assemblies"),
    ("site_magnets", "assembly_magnets"),
]


def _rewrite_schema_sql(text: str) -> str:
    for pattern, repl in RENAMES:
        text = re.sub(pattern, repl, text)
    return text


def migrate(db_path: str, out_path: str, dry_run: bool = False) -> None:
    db_path = Path(db_path)
    out_path = Path(out_path)
    if out_path.exists():
        raise FileExistsError(f"{out_path} already exists — refusing to overwrite")

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        con = duckdb.connect(str(db_path), read_only=True)
        con.execute(f"EXPORT DATABASE '{tmpdir}' (FORMAT PARQUET)")
        con.close()

        schema_file = tmpdir / "schema.sql"
        load_file = tmpdir / "load.sql"
        schema_original = schema_file.read_text()
        load_original = load_file.read_text()

        if dry_run:
            print("Would rewrite schema.sql and load.sql:")
            for pattern, repl in RENAMES:
                count = len(re.findall(pattern, schema_original)) + len(
                    re.findall(pattern, load_original)
                )
                if count:
                    print(f"  {pattern} -> {repl}: {count} occurrence(s)")
            print(f"Would write migrated database to {out_path}")
            return

        # Rename the exported Parquet files to match, so load.sql's rewritten
        # COPY ... FROM '<table>.parquet' paths point at files that exist.
        for old_table, new_table in CHECKED_TABLES + [
            ("op_site_bin_stats", "op_assembly_bin_stats"),
            ("exp_site_bin_stats", "exp_assembly_bin_stats"),
        ]:
            old_parquet = tmpdir / f"{old_table}.parquet"
            if old_parquet.exists():
                old_parquet.rename(tmpdir / f"{new_table}.parquet")

        schema_file.write_text(_rewrite_schema_sql(schema_original))
        load_file.write_text(_rewrite_schema_sql(load_original))

        new_con = duckdb.connect(str(out_path))
        new_con.execute(f"IMPORT DATABASE '{tmpdir}'")

        old_con = duckdb.connect(str(db_path), read_only=True)
        for old_table, new_table in CHECKED_TABLES:
            old_count = old_con.execute(f"SELECT COUNT(*) FROM {old_table}").fetchone()[0]
            new_count = new_con.execute(f"SELECT COUNT(*) FROM {new_table}").fetchone()[0]
            if old_count != new_count:
                raise RuntimeError(
                    f"Row count mismatch: {old_table}={old_count} vs {new_table}={new_count}"
                )
            print(f"  {old_table} ({old_count}) -> {new_table} ({new_count}): OK")
        old_con.close()
        new_con.close()

    print(f"Migrated. New database written to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="Source DuckDB file (read-only, never modified)")
    parser.add_argument("--out", required=True, help="Path for the new, migrated DuckDB file")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be renamed without writing anything",
    )
    args = parser.parse_args()
    migrate(args.db, args.out, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
