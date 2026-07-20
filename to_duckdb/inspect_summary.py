import json
import duckdb
import pandas as pd
from pathlib import Path

from python_magnetrun.magnetdata import MagnetData

path = "/mnt/LNCMIG-Data/records/srv-data-install/M9/2025.01.23 - 16:56:54.txt"
md = MagnetData.fromtxt(path)
df = md.getPandasData(path)

FILE = Path("../Data for Stage/M9_Summary-2025.json")

with open(FILE, "r") as f:
    data = json.load(f)

df = pd.json_normalize(data)

print(df.head())
print(df.columns.tolist())

print(80 * "=")
print(type(data))

if(isinstance(data, list)):

    print(f"\nNumber of records: {len(data)}")
    print("\nFirst record:\n")
    first = data[0]

    for k, v in first.items():
        print(f"{k:25} {type(v).__name__:10} {v}")

elif isinstance(data, dict):

    print("\nTop-levelkeys:\n")

    for k in data.keys():
        print(k)

        print("\nExample values:\n")

        for k, v in data.items():
            print(f"{k:25} {type(v).__name__}")


con = duckdb.connect("magnetdb.duckdb")

con.execute(
    """
        DROP TABLE IF EXISTS housing_summary
    """
)

con.register("summary_df", df)

con.execute(
    """
        CREATE TABLE housing_summary AS
        SELECT * FROM summary_df
    """
)

con.execute(
    """
        ALTER TABLE housing_summary
        ADD COLUMN mode VARCHAR
    """
)
con.execute(
    """
        ALTER TABLE housing_summary
        ADD COLUMN field_signature VARCHAR
    """
)
con.execute(
    """
        ALTER TABLE housing_summary
        ADD COLUMN current_signature VARCHAR
    """
)

print("\nTable schema: ", con.execute(
    """
        DESCRIBE housing_summary
    """
).fetchdf())

print("\nNumber of rows: ", con.execute(
    """
        SELECT COUNT(*) FROM housing_summary
    """
).fetchone()[0])

con.close()