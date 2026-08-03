* userdb
- by default remove users entries with a hstart before the first ever commissioned date in the duckdb database (see site table
- instead of loading EXPERIENCES_LOG.csv, load this table directly from SUPERVISON DB
- same for proposal table, load it directly from EMFL user DB API
* stress
- see to_duckdb/docs/hoop_stress.md and to_duckdb/PLAN_hoop_stress_history.md
- `magnetdp.py hoop-stress compute` | Compute and persist hoop-stress bin stats + fatigue -- do not compute fatigue at this point
- test if fatigue can be used like a cumulative stats??
* overview-record
- concat entries that share one pupitre file
- lag: see Wolali and Me
- plateaux:
- signature: 
  - Field (pupitre) for classification, 
  - Ref currents (pigbrother) for ODE system, 
  - currents A1 to A2 (pigbrother) and Iddct1 to Iddct4 for lag
