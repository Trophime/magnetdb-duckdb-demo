import json
import duckdb
import pandas as pd
from pathlib import Path
import time

from python_magnetrun.magnetdata import MagnetData




DATA_DIR = Path("../Data for Stage")
PUPITRE_ROOT = Path("../pupitre_2023/srv-data-install")
PUPITRE_DIR = Path("../pupitre_2023/srv-data-install/M9")
DB = "magnetdb.duckdb"

FIELD_THRESHOLD = 0.1

### HOUSING SUMMARY
# Load and merge the housing summary files

rows = []
for file in sorted(DATA_DIR.glob("*_summary-*.json")):

    print(f"Loading {file.name}")

    site = file.stem.split("_")[0]
    year = int(file.stem[-4: ])

    with open(file, "r") as f:
        data = json.load(f)

    df = pd.json_normalize(data)

    df["site"] = site
    df["year"] = year

    rows.append(df)

summary_df = pd.concat(rows, ignore_index = True)

# Refresh the housing summary table and display basic stats

con = duckdb.connect(DB)
con.execute(
    """
        DROP TABLE IF EXISTS housing_summary
    """
)
con.register("summary_df", summary_df)
con.execute(
    """
        CREATE TABLE housing_summary AS
        SELECT *
        FROM summary_df
    """
)

print("\nRows:\n",
    con.execute(
        """
            SELECT site, year, COUNT(*) AS n
            FROM housing_summary
            GROUP BY site, year
            ORDER BY site, year
        """
    ).fetchdf()
)

# Data quality audit
## Check the date schema
print("\nTABLE SCHEMA: ",
    con.execute(
        """
            DESCRIBE housing_summary
        """
    ).fetchdf()
)
## Count imported records
print("\nNUMBER OF ROWS:", 
    con.execute(
        """
            SELECT COUNT(*) FROM housing_summary
        """
    ).fetchone()[0]
)
# Count number of records linked to experiments
print("NUMBER OF MATCHES:",
    con.execute(
        """
            SELECT COUNT(*)
            FROM housing_summary AS h
            JOIN experiments AS e
            ON h.pupitre LIKE '%' || e.file
        """).fetchone()[0]
)
# Check for missing files
print("\nMISSING FILES:\n",
    con.execute(
        """
            SELECT
                SUM(CASE WHEN overview = '' THEN 1 ELSE 0 END) AS overview,
                SUM(CASE WHEN archive  = '' THEN 1 ELSE 0 END) AS archive,
                SUM(CASE WHEN pupitre  = '' THEN 1 ELSE 0 END) AS pupiter,
                SUM(CASE WHEN trigger  = '' THEN 1 ELSE 0 END) AS trigger
            from housing_summary
        """
    ).fetchdf()
)
# Check for duplicate files
print("\nDUPLICATE FILENAMES:\n",
    con.execute(
        """
            SELECT filename, COUNT(*) AS n
            FROM housing_summary
            GROUP BY filename
            HAVING COUNT(*) > 1
            ORDER BY n DESC
        """
    ).fetchdf()
)

con.execute(
    """
        ALTER TABLE housing_summary
        ADD COLUMN field_max DOUBLE
    """
)
con.execute(
    """
        ALTER TABLE housing_summary
        ADD COLUMN field_mean DOUBLE
    """
)
con.execute(
    """
        ALTER TABLE housing_summary
        ADD COLUMN field_time_on DOUBLE
    """
)

# Link with the user DB : Add foreign key column and populate
con.execute(
    """
        ALTER TABLE housing_summary
        ADD COLUMN experiment_id INTEGER
    """
)
con.execute(
    """
        UPDATE housing_summary AS h
        SET experiment_id = e.id
        FROM experiments AS e
        WHERE h.pupitre LIKE '%' || e.file
    """
)

print("\nLINKED EXPERIMENTS:",
    con.execute(
        """
            SELECT COUNT(*)
            FROM housing_summary
            WHERE experiment_id IS NOT NULL
        """
    ).fetchone()[0]
)
print(
    con.execute(
        """
            SELECT experiment_id, filename, pupitre
            FROM housing_summary
            WHERE experiment_id IS NOT NULL
            LIMIT 10
        """
    ).fetchdf()
)
print(
    con.execute(
        """
            SELECT h.experiment_id, e.name, e.file, h.pupitre
            FROM housing_summary AS h
            JOIN experiments AS e
            ON h.experiment_id = e.id
            LIMIT 10
        """
    ).fetchdf()
)

rows = con.execute(
    """
        SELECT rowid, site, pupitre
        FROM housing_summary
        WHERE pupitre <> ''
    """
).fetchall()

start = time.perf_counter()
for i, (rowid, site, pupitre) in enumerate (rows, start = 1):

    filename = Path(pupitre).name
    filepath = PUPITRE_ROOT / site / filename

    if not filepath.exists():
        continue

    try: 

        md = MagnetData.fromtxt(str(filepath))
        df = md.getPandasData(None)

        field = df["Field"]

        con.execute(
            """
                UPDATE housing_summary
                SET 
                    field_max = ?,
                    field_mean = ?,
                    field_time_on = ?
                WHERE rowid = ?
            """, 
            (float(field.max()), float(field.mean()), int((field > FIELD_THRESHOLD).sum()), int(rowid))
        )

        if i % 100 == 0:
            print(f"{i}/{len(rows)}")

    except Exception as e:
        
        print(filename, e)


end = time.perf_counter()
print(f"Dataframe updated in: {end - start} s")

print(
    con.execute(
        """
            SELECT COUNT(field_max), COUNT(field_mean), COUNT(field_time_on)
            FROM housing_summary
        """
    ).fetchdf()
)
print(
    con.execute(
        """
            SELECT experiment_id, field_max, field_mean, field_time_on
            FROM housing_summary
            WHERE field_max IS NOT NULL
            LIMIT 10
        """
    ).fetchdf()
)

con.close()



### INFER MODE
# Inspect a Pupiter file

files = sorted(PUPITRE_DIR.glob("*.txt"))

print(f"\n\nFound {len(files)} files")
file0 = files[0]
print(f"Loading: {file0.name}")

md = MagnetData.fromtxt(str(file0))
df = md.getPandasData(None)

print("\nAVAILABLE CHANNELS:", md.getKeys())
print("\nCOLUMNS:", df.columns.tolist())
print("\nFIRST ROWS:\n", df.head())

for k in md.getKeys():

    if "Idcct" in k or "Icoil" in k:
        print(k)