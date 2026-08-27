# In[10]:


import json
import time
from pathlib import Path

import duckdb
import pandas as pd
from python_magnetrun.MagnetRun import load_mrun
from rich.progress import Progress

DATA_DIR = Path("../Data")
PUPITRE_ROOT = Path("~/LNCMIG-Data/records/srv-data-install").expanduser()
PUPITRE_DIR = Path("~/LNCMIG-Data/records/srv-data-install/M9").expanduser()
PIGBROTHER = Path("../pigbrother_2025/M10_Overview_251201-0909.tdms")
DB = "test-magnetdb.duckdb"

FIELD_THRESHOLD = 0.1


# In[ ]:


# Sample the field at 20 points -> representation of the field profile
def compute_field_signature(mdata, field, threshold):
    from python_magnetrun.signature import Signature
    
    signature = Signature.from_mdata(mdata, field, "t", threshold)
    
    return ",".join(signature.to_dict())


# # HOUSING SUMMARY
# ### Load and merge the housing summary files
# 

# In[12]:


PATH_COLUMNS = [
    "overview", "archive", "pupitre", "default", "trigger", "spike",
    "hybrid_kHz", "hybrid_rms", "hybrid_trigger", "hybrid_vprocess",
    "pigbrother_runlog", "pupitre_runlog",
]

rows = []
for file in sorted(DATA_DIR.glob("*_summary-*.json")):

    print(f"Loading {file.name}")

    housing = file.stem.split("_")[0]
    year = int(file.stem[-4: ])

    with open(file, "r") as f:
        data = json.load(f)

    df = pd.json_normalize(data)

    for col in PATH_COLUMNS:
        df[col] = df[col].apply(lambda x: Path(x).name if x else x)

    df["housing"] = housing
    df["year"] = year

    rows.append(df)

summary_df = pd.concat(rows, ignore_index = True)

summary_df["experiment_id"]       = None
summary_df["field_max"]           = pd.Series(dtype = "float64")
summary_df["field_mean"]          = pd.Series(dtype = "float64")
summary_df["field_time_on"]       = pd.Series(dtype = "float64")
summary_df["mode"]                = ""
summary_df["field_signature"]     = ""
summary_df["reference_signature"] = ""

print(f"Found {len(summary_df)} summary files")
print(summary_df.head())


# ### Refresh the housing summary table and display basic stats

# In[13]:


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
            SELECT housing, year, COUNT(*) AS n
            FROM housing_summary
            GROUP BY housing, year
            ORDER BY housing, year
        """
    ).fetchdf()
)


# ### Data quality audit

# In[17]:


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


# In[ ]:


# Check for missing files
print("\nMISSING FILES:\n",
    con.execute(
        """
            SELECT
                SUM(CASE WHEN overview = '' THEN 1 ELSE 0 END) AS overview,
                SUM(CASE WHEN archive  = '' THEN 1 ELSE 0 END) AS archive,
                SUM(CASE WHEN pupitre  = '' THEN 1 ELSE 0 END) AS pupiter
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


# ### Link with the user DB : Add foreign key column and populate

# In[ ]:


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
        SELECT rowid, housing, pupitre
        FROM housing_summary
        WHERE pupitre <> ''
    """
).fetchall()

print(f"rows to process: {len(rows)}")
print(f"Pupitre files to process: {len([r for r in rows if r[2] != ''])}")


# In[19]:


print(
    con.execute("""
        DESCRIBE housing_summary
    """).fetchdf()
)


# In[ ]:


start = time.perf_counter()
with Progress() as progress:
    task = progress.add_task("Updating field stats", total=len(rows))
    for rowid, housing, pupitre in rows:
        filename = Path(pupitre).name
        filepath = PUPITRE_ROOT / housing / filename
        progress.update(task, description=f"{housing}/{filename}")

        if not filepath.exists():
            progress.advance(task)
            continue

        try:
            md = load_mrun(str(filepath), housing=housing)
            mdata = md.getMData()
            df = mdata.Data

            field = df["Field"]
            field_signature = compute_field_signature(mdata, "Field", 1.e-3)

            con.execute(
                """
                    UPDATE housing_summary
                    SET 
                        field_max = ?,
                        field_mean = ?,
                        field_time_on = ?,
                        field_signature = ?
                    WHERE rowid = ?
                """, 
                (float(field.max()), float(field.mean()), int((field > FIELD_THRESHOLD).sum()), field_signature, int(rowid))
            )

        except Exception as e:
            progress.console.print(f"[red]{filename}: {e}[/red]")

        progress.advance(task)

end = time.perf_counter()
print(f"Dataframe updated in {int((end - start) // 60)} m {((end - start) % 60):.2f} s")


# In[10]:


# Validate update
print(
    con.execute(
        """
            SELECT COUNT(field_max) AS field_stats, COUNT(field_signature) AS signatures
            FROM housing_summary
        """
    ).fetchdf()
)
print(
    con.execute(
        """
            SELECT experiment_id, field_max, field_signature
            FROM housing_summary
            WHERE field_signature <> ''
            LIMIT 10
        """
    ).fetchdf()
)

print(
    con.execute(
        """
            SELECT experiment_id, field_signature
            FROM housing_summary
            WHERE field_signature IS NOT NULL
            LIMIT 5
        """
    ).fetchdf()
)


# In[ ]:


con.close()

files = sorted(PUPITRE_DIR.glob("*.txt"))

print(f"Found {len(files)} files")
print(f"Loading: {files[0].name}")

md = load_mrun(str(files[0]))
df = md.getMData().Data

print("\nAVAILABLE CHANNELS:", md.getKeys())
print("\nCOLUMNS:", df.columns.tolist())
print("\nFIRST ROWS:\n", df.head())


# # MODE INFERRING

# In[ ]:


mrun = load_mrun(str(PIGBROTHER), housing = "M10")
mdata = mrun.getMData()
print(mdata)

print("Courants_Alimentations columns:", mdata.Data["Courants_Alimentations"].columns)


# # PROPOSALS

# In[ ]:


# Load proposals metadata and parse experiment date ranges

proposals_df = pd.read_csv(DATA_DIR / "proposals_2026-07-22_with_sites.csv")
proposals_df["Debut"] = pd.to_datetime(proposals_df["Debut"], errors = "coerce")
proposals_df["Fin"]   = pd.to_datetime(proposals_df["Fin"],   errors = "coerce")


# In[ ]:


# Connect to the database and recreate the proposals table

con = duckdb.connect(DB)

con.execute(
    """
        DROP TABLE IF EXISTS proposals
    """
)
con.register("proposals_df", proposals_df)
con.execute(
    """
        CREATE TABLE proposals AS
        SELECT * FROM proposals_df
    """
)


# In[ ]:


# Inspect imported proposal schema as well as the experiments table
 
print(
    con.execute(
        """
            DESCRIBE proposals
        """
    ).fetchdf()
)
print(
    con.execute(
        """
            SELECT * FROM proposals 
            LIMIT 10
        """
    ).fetchdf()
)

print(
    con.execute(
        """
            DESCRIBE experiments
        """
    )
)
print(
    con.execute(
        """
            SELECT * FROM experiments
            LIMIT 10
        """
    ).fetchdf()
)


# In[ ]:


# Check temporal coverage of the proposal metadata

print(
    con.execute(
        """
            SELECT MIN(file), MAX(file), COUNT(*)
            FROM experiments
        """
    ).fetchdf()
)
print(
    con.execute(
        """
            SELECT DISTINCT year
            FROM housing_summary
            ORDER BY year
        """
    ).fetchdf()
)
print(
    con.execute(
        """
            SELECT MIN(Debut), MAX(Fin), COUNT(*)
            FROM proposals
        """
    ).fetchdf()
)


# In[ ]:


# Add proposal column to housing_summary unless it already exists

con.execute(
    """
        ALTER TABLE housing_summary
        ADD COLUMN IF NOT EXISTS proposal VARCHAR;
    """
)

# Link housing records to proposals by magnet site and experiment date

con.execute(
    """
        UPDATE housing_summary AS h
        SET proposal = p.Acronym
        FROM proposals AS p
        WHERE h.pupitre <> '' AND h.pupitre IS NOT NULL
            AND h.site = regexp_replace(p.Site, '[ie]$', '')
            AND strptime(right(replace(h.pupitre, '.txt', ''), 19), '%y.%m.%d - %H:%M:%S')
        BETWEEN CAST(p.Debut AS TIMESTAMP) AND CAST(p.Fin AS TIMESTAMP);
    """
)


# In[ ]:


# Validate propsal linkage

print(
    con.execute(
        """
            SELECT COUNT(*) AS total, COUNT(proposal) AS linked
            FROM housing_summary;
        """
    ).fetchdf()
)


# In[47]:


con.close()


# In[ ]:


proposals_df = pd.read_csv(DATA_DIR / "proposals_2026-07-22.csv")
proposals_df["Experiment Start Date"] = pd.to_datetime(proposals_df["Experiment Start Date"], errors = "coerce")
proposals_df["Experiment End Date"]   = pd.to_datetime(proposals_df["Experiment End Date"], errors = "coerce")

print(proposals_df[["Acronym", "Magnet Sites", "Experiment Start Date", "Experiment End Date"]].head(), proposals_df.shape)


# In[ ]:


# Check Magent Sites in new proposals_2026-07-26.csv

print(proposals_df["Magnet Sites"].dtype)
print(len(proposals_df))
print(proposals_df["Magnet Sites"].notna().sum())


# In[ ]:


###
print(
    con.execute("""
        SELECT year, COUNT(*)
        FROM housing_summary
        GROUP BY year
        ORDER BY year
    """).fetchdf()
)


# In[ ]:




