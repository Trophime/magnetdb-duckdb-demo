#! /bin/bash

echo "Create a test magnetdb DataBase"

cd to_duckdb/
DB=test-magnetdb.duckdb
JSON=~/github/hifimagnet-projects/magnetdb.json
RECORDS=~/LNCMIG-Data/records

python magnetdb.py db create --db $DB

# load assembly by data and check data
for file in $(../scripts/list_site_configs.sh); do
    echo $file
    python magnetdb.py site add "$f" --db $DB
done

python magnetdb.py check --db $DB   # flags missing geometry_data, bad file paths, etc.

# Populate experiments
python magnetdb.py populate  experiments --all --db $DB --records-base $RECORDS
# 4. Ingest per-file operational statistics (idempotent)
python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM sites ORDER BY name').fetchall():
    print(s)
" | while read SITE; do
    python compute_exp_stats.py --db $DB --site "$SITE"
done

# Populate OperationalData
python magnetdb.py populate  operationaldata --all --db $DB --records-base $RECORDS --type Overview Archive Spike Default Pupitre
# 4. Ingest per-file operational statistics (idempotent)
python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM sites ORDER BY name').fetchall():
    print(s)
" | while read SITE; do
    python compute_op_stats.py --db $DB \
        --records $RECORDS/srv-data-install \
        --site "$SITE" --type Pupitre
done
