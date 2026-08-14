# userdb
See: [to_duckdb/PLAN_users_multi_source.md](PLAN_users_multi_source.md)
- [ ] by default remove users entries with a hstart before the first ever commissioned date in the duckdb database (see site table
- [ ] instead of loading EXPERIENCES_LOG.csv, load this table directly from SUPERVISON DB
- [ ] same for proposal table, load it directly from EMFL user DB API


# stress
See: [to_duckdb/docs/hoop-stress.md](docs/hoop-stress.md) and [to_duckdb/PLAN_hoop_stress_history.md](PLAN_hoop_stress_history.md)
- [ ] `magnetdb.py hoop-stress compute` | Compute and persist hoop-stress bin stats + fatigue -- do not compute fatigue at this point
- [ ] test if fatigue can be used like a cumulative stats??
- [ ] **POSTPONED, must come back to — `--check` mode must work smoothly.**
      `validate_fast_from_pupitre(..., check=True)` sanity-checks the fast
      path against `magnettools.Bmap.getHoop()`. Crash fixed here; the
      deeper fix lives in a separate repo (`~/github/my-magnettools`,
      uncommitted, not yet reinstalled) and this file's `--check` call
      still needs to pass `z0_h`/`z0_b` into `getHoop()` once that lands.
      See `NOTES_hoop_stress_implementation.md`'s "Known limitations"
      section for the full trail.

# overview-record
- [ ] duration from overview
- [ ] backfill teb, ... from source_pupitres
- [ ] concat entries that share one pupitre file
- [ ] lag: see Wolali and Me
- [ ] plateaux:
- [ ] signature: 
  - [ ] Field (pupitre/pigbrother) for classification, 
  - [ ] Ref currents (pigbrother) for ODE system, 
  - [ ] currents A1 to A2 (pigbrother) and Iddct1 to Iddct4 for lag

> [!Question] quid des overview sans pupitre et vice-verca des pupitre sans overview... comment les detecter???

# duckdb schema:
- [ ] cleanup and update schema to reflect the above changes
- [ ] remove uneeded tables and columns: operationaldata, sum_x2_dt columns -- hoop proxy

# scheduler
See: [to_duckdb/PLAN_scheduled_populate.md](PLAN_scheduled_populate.md)
- [ ] add a scheduler to run the above scripts on a regular basis (cron job or similar) -- see claude calcul22

# Operational parameters
- [ ] compute ECCO params -- see claude on calcul22

# New features
- [ ] work on life cycle of magnets and parts -- status for magnet|part with some standardized values (in_operation|in_stock|retired|dead) along with a json struct to hold description of the status, the date of the status change and eventually reports/images on incidents, maintenance, etc. -- 
- [ ] correct and update [python_magnetrun/examples/bilan.py](python_magnetrun/examples/bilan.py)
- [ ] update numerical commissionning
- [ ] prepare data structure to store commissionning data and results in duckdb for site -- aka assembly -- and propagate to magnets
- [ ] how to flag experiments/overview-records to know what processing has been done on them (stress, fatigue, etc.) and what is still to be done 
- [ ] how to include cooling models by M1 student for better simulations especially for primary heat exchanger
- [ ] rework dashboards to start with housing and then go "down" to magnet, with a link to the overview-records and the stress/fatigue results
  See: [stage/dashboard/PLAN_dashboard_hierarchy_rework.md](../stage/dashboard/PLAN_dashboard_hierarchy_rework.md) (awaiting approval)
  - create a dashboard for housings
    - display stats for energy, magnet time per housing per year
    - make the table display site with housing, commissionning date, decomissionning date, status, energy, magnet time, binary field history -- like great tables
    - add selector for housinng and year to filter the table and the graphs
    - make the table clickable to go to the site_stats dashboard
    - add a table with details on site per housing per year with links to site_stats dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on experiments per housing per year with links to experiments dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on overview-records per housing per year with links to overview-records dashboard -- use accordeon to hide details and show only when needed
  - site_stats dashboard
    - use only site related data in this dashboard
    - display stats for energy, magnet time per site per year
    - make the table display site with housing, commissionning date, decomissionning date, status, energy, magnet time, binary field history -- like great tables
    - add selector for site and year to filter the table and the graphs
    - make the table clickable to go to the overview-records dashboard
    - add a table with details on magnets per site with links to magnet_stats dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on overview-records per site with links to overview-records dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on stress/fatigue per site with links to stress/fatigue dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on users per site with links to users dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on experiments per site with links to experiments dashboard -- use accordeon to hide details and show only when needed
  - magnet_stats dashboard
    - use only magnet related data in this dashboard
    - display stats for energy, magnet time per magnet per year
    - make the table display magnet with housing, commissionning date, decomissionning date, status, energy, magnet time, binary field history -- like great tables
    - add selector for magnet and year to filter the table and the graphs
    - make the table clickable to go to the overview-records dashboard
    - add a tablewith details on part per magnet with links to part_stats dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on site per magnet -- history of site that contain the given magnet -- with links to site_stats dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on overview-records per magnet with links to overview-records dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on stress/fatigue per magnet with links to stress/fatigue dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on users per magnet with links to users dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on experiments per magnet with links to experiments dashboard -- use accordeon to hide details and show only when needed
  - part_stats.dashboard
    - use only part related data in this dashboard
    - add selector for part and year to filter the table and the graphs
    - make the table clickable to go to the overview-records dashboard
    - add a table with details on site per part -- history of site that contain the given part -- with links to site_stats dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on magnet per part -- history of magnet that contain the given part -- with links to magnet_stats dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on overview-records per part with links to overview-records dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on stress/fatigue per part with links to stress/fatigue dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on users per part with links to users dashboard -- use accordeon to hide details and show only when needed
    - add a table with details on experiments per part with links to experiments dashboard -- use accordeon to hide details and show only when needed

# Links with other projects
Unsorted todo list of links with other projects:
- [ ] hifimagnet-projects
  - [ ] add site -- aka assembly -- setup for M7, M8,  ... -- cf cahier E. Verney
- for M8 and experience from Xavavier on M9/M10:
  - review stats for Field -- must be Field + Supra_Field == Total_Field, 
  - pay attention to the first records for hybrid test where Supra_Field was hardcoded
- what about pigbrother data before 2022?
- How to handle special experiments
  - e.g., M19 test M9 with 18 MW and M10 with 10 MW and Mateo's experiments with a negative IH/IB current??