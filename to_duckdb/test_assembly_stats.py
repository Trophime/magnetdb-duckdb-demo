# In[1]:


import duckdb
from compute_exp_stats import ingest_assembly

assembly = "M10_A251112_00"
db = "magnetdb.duckdb"


# In[2]:


con = duckdb.connect(db)

files = con.execute(
    """
        SELECT file FROM experiments WHERE assembly_name = ?
    """,
    [assembly]
).fetchall()

for f in files:

    print(f[0])

print(f"Number of files: {len(files)}")

ingest_assembly(assembly_name = assembly, db_path = db)


# In[ ]:




