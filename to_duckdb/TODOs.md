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

* add a scheduler to run the above scripts on a regular basis (cron job or similar) -- see claude calcul22
- see to_duckdb/PLAN_scheduled_populate.md
* compute ECCO params -- see claude on calcul22
* correct and update python_magnetrun/examples/bilan.py
* update numerical commissionning
* prepare data structure to store commissionning data and results in duckdb for site -- aka assembly -- and propagate to magnets
* how to flag experiments/overview-records to know what processing has been done on them (stress, fatigue, etc.) and what is still to be done 
* how to include cooling models by M1 student for better simulations especially for primary heat exchanger
* rework dashboards to start with housing and then go "down" to magnet, with a link to the overview-records and the stress/fatigue results
