import duckdb
from _common import DB, print_title


def main():

    # Build overview_experiments: one row per (overview_records, experiments)
    # link, joining on the Pupitre filename recorded in
    # overview_records.sources_pupitre. LEFT JOIN so overview_records with no
    # linked Pupitre experiment still appear (experiment_id = NULL).
    # Duplicate/merged overview_records (merged_into IS NOT NULL) are excluded,
    # matching the convention already used elsewhere (e.g. magnetdb_analysis.py).

    print_title("1. IMPORT HOUSING")

    con = duckdb.connect(DB)

    con.execute(
        """
            DROP TABLE IF EXISTS overview_experiments
        """
    )
    con.execute(
        """
            CREATE TABLE overview_experiments AS
            SELECT
                o.filename,
                e.id AS experiment_id,
                e.file AS pupitre_file,
                o.housing,
                CAST(EXTRACT(YEAR FROM o.t0) AS BIGINT) AS year,
                o.mode,
                CAST(NULL AS DOUBLE)  AS field_max,
                CAST(NULL AS DOUBLE)  AS field_mean,
                CAST(NULL AS DOUBLE)  AS field_std,
                CAST(NULL AS DOUBLE)  AS field_median,
                CAST(NULL AS DOUBLE)  AS field_time_on,
                CAST(NULL AS VARCHAR) AS field_signature,
                CAST(NULL AS VARCHAR) AS reference_signature,
                CAST(NULL AS VARCHAR) AS user_acronym,
                CAST(NULL AS VARCHAR) AS research_area,
                CAST(NULL AS VARCHAR) AS country,
                CAST(NULL AS VARCHAR) AS access_mode,
                CAST(NULL AS VARCHAR) AS user_type
            FROM overview_records AS o
            LEFT JOIN experiments AS e
                ON list_contains(o.sources_pupitre, e.file)
            WHERE o.merged_into IS NULL
        """
    )

    print_title("DATA SUMMARY")

    print("\nNumber of rows per housing and year:\n",
        con.execute(
            """
                SELECT housing, year, COUNT(*) AS n
                FROM overview_experiments
                GROUP BY housing, year
                ORDER BY housing, year
            """
        ).fetchdf()
    )

    n_rows = con.execute("SELECT COUNT(*) FROM overview_experiments").fetchone()[0]
    n_overview_records = con.execute(
        "SELECT COUNT(*) FROM overview_records WHERE merged_into IS NULL"
    ).fetchone()[0]

    print(f"\n{n_overview_records} overview_records produced {n_rows} overview_experiments rows.")

    con.close()




if __name__ == "__main__":

    main()
