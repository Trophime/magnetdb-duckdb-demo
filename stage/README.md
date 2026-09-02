#! /bin/bash

echo "Create a test magnetdb DataBase"

cd to_duckdb/
DB=test-magnetdb.duckdb
JSON=~/github/hifimagnet-projects/magnetdb.json
RECORDS=~/LNCMIG-Data/records

python magnetdb.py db create --db $DB

# load assembly by data and check data
for file in $(../scripts/list_assembly_configs.sh); do
    echo -n "$JSON/$file"
    if python magnetdb.py assembly add "$JSON/$file" --db "$DB" >> "$DB.log" 2>&1; then
        echo -e ": \033[32mOK\033[0m"
    else
        echo -e ": \033[31mERROR\033[0m"
    fi
done
python magnetdb.py magnet update-status M09052601 --db "$DB" --status retired ... 
python magnetdb.py magnet update-status M12082401 --db "$DB" --status retired ... 

# python magnetdb.py magnet update-status M09052601 \
#     --status retired \
#     --description "Superseded, coils reused / no longer in service." \
#     --changed-at "2026-09-02 07:00:00" \
#     --db "$DB"

python magnetdb.py check --db $DB   # flags missing geometry_data, bad file paths, etc.

# Populate experiments
python magnetdb.py populate  experiments --all --db $DB --records-base $RECORDS
# 4. Ingest per-file operational statistics (idempotent)
python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM assemblies ORDER BY name').fetchall():
    print(s)
 " | while read ASSEMBLY; do
    python compute_exp_stats.py --db $DB --assembly "$ASSEMBLY"
done

# Populate OperationalData
python magnetdb.py populate  operationaldata --all --db $DB --records-base $RECORDS --type Overview Archive Spike Default Pupitre
# 4. Ingest per-file operational statistics (idempotent)
python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM assemblies ORDER BY name').fetchall():
    print(s)
 " | while read ASSEMBLY; do
    python compute_op_stats.py --db $DB \
        --records $RECORDS/srv-data-install \
        --assembly "$ASSEMBLY" --type Pupitre
done

# note on creating *summary*.json
# Populate overview_records from JSON
for file in $(ls ../Data/*summary*.json); do
    python magnetdb.py populate overview-records-from-json "$file" --db $DB
done
# Consolidate overview_records and remove duplicates
python magnetdb.py populate overview-records-infer --db $DB 

# Get user table contents from csv proposals from EMFL DB and SUPERVISION DB (experiences_log table)
python to_duckdb/demos/users_table_demo.py --from 2018-01-01 --db to_duckdb/test-magnetdb.duckdb 
python to_duckdb/demos/users_table_demo.py --link-only --db to_duckdb/test-magnetdb.duckdb

# Check users that are not linked (nor associated with any records -- either experiments or overview records)
python to_duckdb/demos/list_users_unlinked.py --db to_duckdb/test-magnetdb.duckdb

# update magnet/part status retro-actively
# get DB coverage from Valentin work
# try pca analysis including localcontact, diameter of innerbore of the innermost magnet in assembly in addition to fields used by Valentin