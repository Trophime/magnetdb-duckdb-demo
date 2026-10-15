import os

import duckdb

db_path = os.environ.get(
    "MAGNETDB_DB_PATH", "/workspaces/magnetdb-duckdb-demo/to_duckdb/test-magnetdb.duckdb"
)

if __name__ == "__main__":
    conn = duckdb.connect(db_path, read_only=True)

    df_exp = conn.execute(
        "SELECT id, name, file FROM experiments WHERE assembly_name = 'M9_A250401_00' AND file IS NOT NULL LIMIT 3"
    ).df()
    print(df_exp)
    conn.close()
