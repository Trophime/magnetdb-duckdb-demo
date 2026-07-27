import duckdb

db_path = "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb"
conn = duckdb.connect(db_path, read_only=True)

df_exp = conn.execute(
    "SELECT id, name, file FROM experiments WHERE site_name = 'M9_A250401_00' AND file IS NOT NULL LIMIT 3"
).df()
print(df_exp)
conn.close()