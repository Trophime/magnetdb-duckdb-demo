import duckdb
from compute_exp_stats import ingest_site

#site = "M9_A250730_00"
db = "magnetdb.duckdb"

con = duckdb.connect(db)

sites = [
    s[0] for s in con.execute(
    """
        SELECT name FROM sites ORDER BY name
    """).fetchall()
]


for site in sites:

    n_files = con.execute(
        """
            SELECT COUNT(*) FROM experiments WHERE site_name = ?
        """,
        [site]
    ).fetchone()[0]
    
    print(f"Processing site {site} ({n_files} files):")
    ingest_site(site_name = site, db_path = db)


rows = con.execute(
    """
        SELECT DISTINCT id, name, site_name, status 
        FROM experiments
        ORDER BY name
    """).fetchall()

print(f"\n{"id":>4} {"name":25} {"site":15} status")
print("-" * 80)

for id, name, site, status in rows:

    print(f"{id:4d} {name:25} {site:15} {status}")

con.close()