#! /bin/bash
set -eo pipefail

# step IDs, in build order (see --help)
STEPS=(create assemblies statuses check experiments exp-stats operationaldata op-stats
       overview-json overview-infer export users link-users unlinked-users)

usage() {
    cat <<EOF
Usage: $(basename "$0") [--from STEP] [--to STEP] [--db FILE]

Rebuild the MagnetDB DuckDB database, or run only the steps from --from to --to
(both included); the other steps are listed as "not run".

  --from STEP  first step to run (default: ${STEPS[0]})
  --to STEP    last step to run (default: ${STEPS[-1]})
  --db FILE    database file (default: to_duckdb/magnetdb-<YYYY-MM-DD>.duckdb);
               a relative path is taken from the current directory
  -h, --help   show this help

Steps: ${STEPS[*]}
EOF
}

# step_index ID: print the position of ID in STEPS; fails for an unknown ID
step_index() {
    local i
    for i in "${!STEPS[@]}"; do
        if [ "${STEPS[$i]}" = "$1" ]; then echo "$i"; return 0; fi
    done
    return 1
}

FROM=${STEPS[0]}
TO=${STEPS[-1]}
DB=""
while [ $# -gt 0 ]; do
    case "$1" in
        --from|--to|--db)
            [ $# -ge 2 ] || { echo "Error: $1 needs a value." >&2; usage >&2; exit 1; }
            case "$1" in --from) FROM=$2 ;; --to) TO=$2 ;; --db) DB=$2 ;; esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Error: unknown option '$1'." >&2; usage >&2; exit 1 ;;
    esac
done
FROM_I=$(step_index "$FROM") || { echo "Error: unknown step '$FROM'." >&2; usage >&2; exit 1; }
TO_I=$(step_index "$TO") || { echo "Error: unknown step '$TO'." >&2; usage >&2; exit 1; }
[ "$FROM_I" -le "$TO_I" ] || { echo "Error: --to $TO comes before --from $FROM." >&2; exit 1; }
# a relative --db is taken from the current directory, before the cd below
if [ -n "$DB" ] && [ "${DB#/}" = "$DB" ]; then DB="$PWD/$DB"; fi

cd $(dirname "$0")/../to_duckdb
[ -n "$DB" ] || DB="$PWD/magnetdb-$(date +%Y-%m-%d).duckdb"
JSON=~/github/hifimagnet-projects/magnetdb.json
RECORDS=~/LNCMIG-Data/records
DATA_DIR=~/github/magnetdb-duckdb-demo/Data
LOG="$DB.log"

if [ "$FROM" != create ] && [ ! -f "$DB" ]; then
    echo "Error: $DB not found; use --db." >&2
    exit 1
fi

echo "Building $DB (steps $FROM → $TO, log: $LOG)"
echo "### run $(date '+%F %T') --from $FROM --to $TO" >> "$LOG"

# --- display helpers --------------------------------------------------------
# Each step prints its title, sends its output to $LOG, then prints its status.
# Inside step functions every command ends with `|| return 1`: `set -e` is
# ignored in functions called from an `if`, so failures must be propagated.

title() {
    local pad=".................................................."
    printf '%s %s ' "$1" "${pad:${#1}}"
}
ok()      { echo -e "\033[32mOK\033[0m"; }
failed()  { echo -e "\033[31mFAILED\033[0m ($1see $LOG)"; }
skipped() { echo -e "\033[33mSKIPPED\033[0m ($1)"; }
not_run() { echo -e "\033[90mnot run\033[0m"; }

# wanted ID: true when step ID lies between --from and --to
wanted() {
    local i
    i=$(step_index "$1")
    [ "$i" -ge "$FROM_I" ] && [ "$i" -le "$TO_I" ]
}

# section ID TITLE COMMAND...: run COMMAND as one step; returns 1 (stopping the build) on failure.
# A step outside --from..--to is listed as "not run".
# A step function that sets SKIP_REASON and returns 0 is reported as SKIPPED.
section() {
    local id=$1 name=$2
    shift 2
    title "$name"
    if ! wanted "$id"; then
        not_run
        return 0
    fi
    echo "=== $name ===" >> "$LOG"
    SKIP_REASON=""
    if "$@" >> "$LOG" 2>&1; then
        if [ -n "$SKIP_REASON" ]; then skipped "$SKIP_REASON"; else ok; fi
    else
        failed
        return 1
    fi
}

# assemblies in commissioning order
list_assemblies() {
    python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM assemblies ORDER BY commissioned_at NULLS LAST, name').fetchall():
    print(s)
"
}

# --- step functions ---------------------------------------------------------

set_magnet_statuses() {
    # deal with known dead magnets
    python magnetdb.py magnet update-status M09052601 \
        --status dead --dead-part ALL \
        --description "HS, coils declared dead following major incident on 2024-11-09." \
        --changed-at "2024-12-06 07:00:00" \
        --db "$DB" || return 1

    python magnetdb.py magnet update-status M12082401 \
        --status retired \
        --description "Superseded, coils reused / no longer in service." \
        --changed-at "2024-12-10 07:00:00" \
        --db "$DB" || return 1

    # mark Bitters -- aka M9Bi and M9_newBi09 -- that has burned as dead
    # M9_A230124_00: M9Bitters dead with M9Bi dead

    python magnetdb.py magnet update-status M9Bitters \
        --status dead --dead-part M9Bi \
        --description "HS, inner bitter coil dead on 2023-06-08." \
        --changed-at "2023-06-08 07:00:00" \
        --db "$DB" || return 1

    # M9_A250730_00: M9Bitters dead with M9_Bi09 dead
    python magnetdb.py magnet update-status M9Bitters-newBi09 \
        --status dead --dead-part M9_newBi09 \
        --description "HS, inner bitter coil dead on 2026-05-05." \
        --changed-at "2026-05-05 07:00:00" \
        --db "$DB" || return 1
}

ingest_exp_stats() {
    local assemblies assembly
    assemblies=$(list_assemblies) || return 1
    for assembly in $assemblies; do
        python compute_exp_stats.py --db $DB --records-base $RECORDS --assembly "$assembly" || return 1
    done
}

ingest_op_stats() {
    local assemblies assembly
    assemblies=$(list_assemblies) || return 1
    for assembly in $assemblies; do
        python compute_op_stats.py --db $DB \
            --records-base $RECORDS \
            --assembly "$assembly" --type Pupitre || return 1
    done
}

load_overview_records() {
    local files file
    files=$(../scripts/sort_summary_by_year.sh $DATA_DIR) || return 1
    for file in $files; do
        python magnetdb.py populate overview-records-from-json "$DATA_DIR/$file" --db $DB || return 1
    done
}

export_source_data() {
    # record the directory from which the script is run
    pushd ~/github/python_magnetrun/examples || return 1

    # Use direnv to define environment variables such as USERDB_API_KEY and SUPERVISION_DB credentials
    # see python_magnetrun/examples original .envrc (scripts do not run the direnv hook: load it explicitly)
    command -v direnv >/dev/null && eval "$(direnv export bash)"

    # Skip the export (keeping the existing $DATA_DIR files) when credentials are missing
    local missing="" var
    for var in USERDB_API_KEY MYSQL_HOST MYSQL_USER MYSQL_PASSWORD \
               MYSQL_DB_SUPERVISION MYSQL_DB_MAGNETS MYSQL_DB_LOGS; do
        [ -n "${!var}" ] || missing="$missing $var"
    done
    if [ -n "$missing" ]; then
        echo "Skipped: unset$missing; using existing files in $DATA_DIR."
        SKIP_REASON="unset$missing"
        popd
        unload_credentials
        return 0
    fi

    # # EMFL DB: download to a temporary file so a failed request keeps the previous proposals.csv
    if curl -fsS -H "X-API-Token: ${USERDB_API_KEY}" "https://user.portal.emfl.eu/api/proposals-for-ct/export-csv" -o "$DATA_DIR/proposals.csv.tmp"; then
        mv "$DATA_DIR/proposals.csv.tmp" "$DATA_DIR/proposals.csv" || return 1
    else
        rm -f "$DATA_DIR/proposals.csv.tmp"
        echo "Warning: EMFL proposals download failed; keeping existing $DATA_DIR/proposals.csv." >&2
    fi

    # SUPERVISION DB:
    python ./mysql_connect.py --mode export --format csv \
       --output-dir $DATA_DIR/ --tables EXPERIENCES_LOG \
       --host $MYSQL_HOST --user $MYSQL_USER --password $MYSQL_PASSWORD --database $MYSQL_DB_SUPERVISION || return 1

    # Get water temperature input/output from HX
    python ./mysql_connect.py --mode export --format csv \
       --output-dir $DATA_DIR/ --tables bdd \
       --host $MYSQL_HOST --user $MYSQL_USER --password $MYSQL_PASSWORD --database $MYSQL_DB_SUPERVISION || return 1

    # Get water Power and Cooling loop parameters
    python ./mysql_connect.py --mode export --format csv \
       --output-dir $DATA_DIR/ --tables site_parameters \
       --host $MYSQL_HOST --user $MYSQL_USER --password $MYSQL_PASSWORD --database $MYSQL_DB_MAGNETS || return 1

    # Get logs from Cirrus
    local table
    for table in cirrusA1 cirrusA2 cirrusA3 cirrusA4; do
        python ./mysql_connect.py --mode export --format csv \
           --output-dir $DATA_DIR/ --tables $table \
           --host $MYSQL_HOST --user $MYSQL_USER --password $MYSQL_PASSWORD --database $MYSQL_DB_LOGS || return 1
    done

    popd
    unload_credentials
}

# unload what direnv loaded from the .envrc (no .envrc here, so direnv reverts it)
unload_credentials() {
    command -v direnv >/dev/null && eval "$(direnv export bash)"
    return 0
}

# --- build ------------------------------------------------------------------

section create "Create database" python magnetdb.py db create --db $DB

# load assembly by data and check data; a failed file is reported but does not stop the build
if wanted assemblies; then
    echo "Load assemblies"
    echo "=== Load assemblies ===" >> "$LOG"
    n_failed=0
    for file in $(../scripts/list_assembly_configs.sh "$JSON"); do
        echo -n "  $file"
        if python magnetdb.py assembly add "$JSON/$file" --db "$DB" >> "$LOG" 2>&1; then
            echo -e ": \033[32mOK\033[0m"
        else
            echo -e ": \033[31mERROR\033[0m"
            n_failed=$((n_failed + 1))
        fi
    done
    title "Load assemblies"
    if [ "$n_failed" -eq 0 ]; then ok; else failed "$n_failed file(s), "; fi
else
    title "Load assemblies"
    not_run
fi

section statuses "Set known magnet statuses" set_magnet_statuses

# check database consistency (check exits non-zero when it finds problems: report and go on)
section check "Check database consistency" python magnetdb.py check --db "$DB" || true
# python magnetdb.py part update $JSON/HybridSupra.json --db $DB
# python magnetdb.py part update $JSON/M9_newBi10.json --db $DB

# Populate experiments
section experiments "Populate experiments" \
    python magnetdb.py populate  experiments --all --db $DB --records-base $RECORDS
# Ingest per-experiment statistics (idempotent)
section exp-stats "Ingest per-experiment statistics" ingest_exp_stats

# Populate OperationalData
section operationaldata "Populate operationaldata" \
    python magnetdb.py populate  operationaldata --all --db $DB --records-base $RECORDS --type Overview Archive Spike Default Pupitre
# Ingest per-file operational statistics (idempotent)
section op-stats "Ingest per-file operational statistics" ingest_op_stats

# note on creating *summary*.json
# magnetrun analysis M9_Overview_25*.tdms --housing M9 > M9_2025.log
# mv summary.json to ../Data/M9_summary_2025.json
# Populate overview_records from JSON
section overview-json "Load overview records from JSON" load_overview_records
# Consolidate overview_records and remove duplicates
section overview-infer "Consolidate overview records" python magnetdb.py populate overview-records-infer --db $DB

# Get user table contents from csv proposals from EMFL DB and SUPERVISION DB (experiences_log table)
# to be stored in $DATA_DIR/
section export "Export source data" export_source_data

# to view database scheme: python mysql_connect.py --mode live --host myhost --user myuser --password mypw --database mydb

# Create User table demo
section users "Build users table" \
    python demos/users_table_demo.py --from 2018-01-01 --db $DB \
        --log $DATA_DIR/EXPERIENCES_LOG.csv --proposals $DATA_DIR/proposals.csv
section link-users "Link users" python demos/users_table_demo.py --link-only --db $DB

# Check users that are not linked (nor associated with any records -- either experiments or overview records)
section unlinked-users "List unlinked users" python demos/list_users_unlinked.py --db $DB

# update magnet/part status retro-actively
# get DB coverage from Valentin work
# try pca analysis including localcontact, diameter of innerbore of the innermost magnet in assembly in addition to fields used by Valentin
