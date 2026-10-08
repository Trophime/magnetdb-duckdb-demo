#! /bin/bash

echo "Create a test magnetdb DataBase"

cd to_duckdb/
DB=magnetdb-$(date +%Y-%m-%d).duckdb
JSON=~/github/hifimagnet-projects/magnetdb.json
RECORDS=~/LNCMIG-Data/records
DATA_DIR=~/github/magnetdb-duckdb-demo/Data

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

# deal with known dead magnets
python magnetdb.py magnet update-status M09052601 \
    --status dead --dead-part ALL \
    --description "HS, coils declared dead following major incident on 2024-11-09." \
    --changed-at "2024-12-06 07:00:00" \
    --db "$DB"

python magnetdb.py magnet update-status M12082401 \
    --status retired \
    --description "Superseded, coils reused / no longer in service." \
    --changed-at "2024-12-10 07:00:00" \
    --db "$DB"

# mark Bitters -- aka M9Bi and M9_newBi09 -- that has burned as dead
# M9_A230124_00: M9Bitters dead with M9Bi dead

# Error: Part(s) ['M9Bi'] do not belong to magnet 'M9Bitters'.
# Error: Part(s) ['M9_newBi09'] do not belong to magnet 'M9Bitters-newBi09'.

python magnetdb.py magnet update-status M9Bitters \
    --status dead --dead-part M9Bi \
    --description "HS, inner bitter coil dead on 2023-06-08." \
    --changed-at "2023-06-08 07:00:00" \
    --db "$DB"

# M9_A250730_00: M9Bitters dead with M9_Bi09 dead
python magnetdb.py magnet update-status M9Bitters-newBi09 \
    --status dead --dead-part M9_newBi09 \
    --description "HS, inner bitter coil dead on 2026-05-05." \
    --changed-at "2026-05-05 07:00:00" \
    --db "$DB"

# check database consistency
../scripts/list_assembly_configs.sh
# 2 lines bellow seems broken with:
# _duckdb.ConstraintException: Constraint Error: Violates foreign key constraint because key "part_name: HybridSupra" is still referenced by a foreign key in a different table. If this is an unexpected constraint violation, please refer to our foreign key limitations in the documentation
python magnetdb.py part update $JSON/HybridSupra.json --db $DB
python magnetdb.py part update $JSON/M9_newBi10.json --db $DB

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
# magnetrun analysis M9_Overview_25*.tdms --housing M9 > M9_2025.log
# mv summary.json to ../Data/M9_summary_2025.json
# Populate overview_records from JSON
for file in $(../scripts/sort_summary_by_year.sh $DATA_DIR); do
    python magnetdb.py populate overview-records-from-json "$file" --db $DB
done
# Consolidate overview_records and remove duplicates
python magnetdb.py populate overview-records-infer --db $DB 

# Get user table contents from csv proposals from EMFL DB and SUPERVISION DB (experiences_log table)
# to be stored in $DATA_DIR/

# Use envdir to define environment variables such as EMFL_API_KEY and SUPERVISION_DB credentials
# see python_magnetrun/examples original .envrc
# record the directory from which the script is run
pushd ~/github/python_magnetrun/examples

# # EMFL DB: 
curl -H "X-API-Token: ${EMFL_API_KEY}" "https://user.portal.emfl.eu/api/proposals-for-ct/export-csv" -o $DATA_DIR/proposals.csv

# SUPERVISION DB: 
python python_magnetrun/examples/mysql_connect.py --mode export --format csv \
   --output-dir $DATA_DIR/ --tables EXPERIENCES_LOG \
   --host $MYSQL_HOST --user $MYSQL_USER --password $MYSQL_PASSWORD --database $MYSQL_DB_SUPERVISION

# Get water temperature input/output from HX
python python_magnetrun/examples/mysql_connect.py --mode export --format csv \
   --output-dir $DATA_DIR/ --tables bdd \
   --host $MYSQL_HOST --user $MYSQL_USER --password $MYSQL_PASSWORD --database $MYSQL_DB_SUPERVISION

# Get water Power and Cooling loop parameters
python python_magnetrun/examples/mysql_connect.py --mode export --format csv \
   --output-dir $DATA_DIR/ --tables site_parameters \
   --host $MYSQL_HOST --user $MYSQL_USER --password $MYSQL_PASSWORD --database $MYSQL_DB_MAGNETS

# Get logs from Cirrus
for table in cirrusA1 cirrusA2 cirrusA3 cirrusA4; do
    python python_magnetrun/examples/mysql_connect.py --mode export --format csv \
       --output-dir $DATA_DIR/ --tables $table \
       --host $MYSQL_HOST --user $MYSQL_USER --password $MYSQL_PASSWORD --database $MYSQL_DB_LOGS
done

popd

# to view database scheme: python mysql_connect.py --mode live --host myhost --user myuser --password mypw --database mydb

# Create User table demo
python demos/users_table_demo.py --from 2018-01-01 --db $DB 
python demos/users_table_demo.py --link-only --db $DB

# Check users that are not linked (nor associated with any records -- either experiments or overview records)
python demos/list_users_unlinked.py --db $DB

# update magnet/part status retro-actively
# get DB coverage from Valentin work
# try pca analysis including localcontact, diameter of innerbore of the innermost magnet in assembly in addition to fields used by Valentin