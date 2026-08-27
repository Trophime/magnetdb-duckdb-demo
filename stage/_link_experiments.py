import duckdb
from _common import DB, print_title

# ### Report on the overview_records <-> experiments link built by
# ### _import_housing.py. The link itself is formed at table-creation time
# ### (via the LEFT JOIN on sources_pupitre), so this step is read-only: it
# ### audits how complete that link is.

def main():

    print_title("2. LINK EXPERIMENTS (coverage report)")

    con = duckdb.connect(DB)

    print("\nOverview records by number of linked experiments:\n",
        con.execute(
            """
                SELECT n_links, COUNT(*) AS n_overview_records
                FROM (
                    SELECT filename, COUNT(experiment_id) AS n_links
                    FROM overview_experiments
                    GROUP BY filename
                )
                GROUP BY n_links
                ORDER BY n_links
            """
        ).fetchdf()
    )

    n_linked = con.execute(
        "SELECT COUNT(*) FROM overview_experiments WHERE experiment_id IS NOT NULL"
    ).fetchone()[0]
    n_total = con.execute("SELECT COUNT(*) FROM overview_experiments").fetchone()[0]

    print(f"\nLinked {n_linked} / {n_total} overview_experiments rows to an experiment "
          f"({100 * n_linked / n_total:.2f}%).")

    # Experiments that never matched any overview_record's sources_pupitre.

    unmatched = con.execute(
        """
            SELECT e.id, e.file, e.assembly_name
            FROM experiments AS e
            LEFT JOIN overview_experiments AS oe ON oe.experiment_id = e.id
            WHERE oe.experiment_id IS NULL
        """
    ).fetchdf()

    print(f"\nExperiments with no matching overview_record ({len(unmatched)}):\n", unmatched)

    con.close()




if __name__ == "__main__":

    main()
