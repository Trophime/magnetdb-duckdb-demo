#!/usr/bin/env python
# coding: utf-8

# In[1]:


import duckdb
from compute_exp_stats import ingest_site

site = "M10_A251112_00"
db = "magnetdb.duckdb"


# In[2]:


con = duckdb.connect(db)

files = con.execute(
    """
        SELECT file FROM experiments WHERE site_name = ?
    """,
    [site]
).fetchall()

for f in files:

    print(f[0])

print(f"Number of files: {len(files)}")

ingest_site(site_name = site, db_path = db)


# In[ ]:




