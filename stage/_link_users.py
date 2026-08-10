from _common import *




def main():

    # Links housing_summary experiment records to users based on the 
    # experiment ID.

    con = duckdb.connect(DB)

    # Add columns if none exist yet.

    existing_columns = set(
        con.execute(
            """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'housing_summary'
            """
        ).fetchdf()["column_name"]
    )

    columns = {
        "user_acronym": "VARCHAR",
        "research_area": "VARCHAR",
        "country": "VARCHAR",
        "access_mode": "VARCHAR",
        "user_type": "VARCHAR"
    }

    for name, type in columns.items():
        
        if name not in existing_columns:
            
            con.execute(
                f"""
                    ALTER TABLE housing_summary
                    ADD COLUMN {name} {type}
                """
            )

    # Link housing_summary and users

    con.execute(
        """
            UPDATE housing_summary AS hs
            SET
                user_acronym = u.acronym,
                research_area = u.research_area,
                country = u.country,
                access_mode = u.access_mode,
                user_type = u.type
            FROM users AS u
            WHERE list_contains(u.experiments_ids, hs.experiment_id)
        """
    )

    # VAlidation
    
    n_total = con.execute(
        """
            SELECT COUNT(*)
            FROM housing_summary
        """
    ).fetchone()[0]
    n_linked = con.execute(
        """
            SELECT COUNT(*)
            FROM housing_summary
            WHERE user_acronym IS NOT NULL
        """
    ).fetchone()[0]
    print(f"\nLinked users: {n_linked} / {n_total} ({n_linked / n_total * 100 :.2f}%)")

    print("\n" + " LINKED USERS ".center(80, "=") + "\n",
        con.execute(
            """
                SELECT COUNT(*)
                FROM housing_summary
                WHERE user_acronym IS NOT NULL
            """
        ).fetchone()[0]
    )

    n_matches = 20
    print("\n" + f" FIRST {n_matches} MATCHES ".center(80, "=") + "\n",
        con.execute(
            f"""
                SELECT
                    experiment_id, filename, proposal, user_acronym, 
                    research_area, access_mode, user_type
                FROM housing_summary
                WHERE user_acronym IS NOT NULL
                LIMIT {n_matches}
            """
        ).fetchdf()
    )

    print("\n" + f" MATCHES PER RESEARCH AREA ".center(80, "=") + "\n",
        con.execute(
            """
                SELECT research_area, COUNT(*) AS n
                FROM housing_summary
                WHERE research_area IS NOT NULL
                GROUP BY research_area
                ORDER BY n DESC
            """
        ).fetchdf()
    )

    print("\n" + f" UNLINKED RECORDS BY HOUSING AND YEAR ".center(80, "=") + "\n",
        con.execute(
            f"""
                SELECT
                    housing, year, COUNT(*) AS n
                FROM housing_summary
                WHERE user_acronym IS NULL
                GROUP BY housing, year
                ORDER BY year, housing
            """
        ).fetchdf()
    )

    print("\n" + f" STATISTICS PER RESEARCH AREA ".center(80, "=") + "\n",
        con.execute(
            f"""
                SELECT
                    research_area, COUNT(*) AS n_experiments,
                    AVG(field_max) AS mean_field,
                    MAX(field_max) AS max_field,
                    AVG(field_mean) AS mean_field_avg,
                    AVG(field_time_on) AS mean_field_time,
                    SUM(field_time_on) AS total_field_time
                FROM housing_summary
                WHERE research_area IS NOT NULL
                GROUP BY research_area
                ORDER BY n_experiments DESC
            """
        ).fetchdf()
    )

    print(
        con.execute(
            """
                SELECT *
                FROM operationaldata
                LIMIT 10
            """
        ).fetchdf(),

        con.execute(
            """
                SELECT *
                FROM experiments
                LIMIT 10
            """
        ).fetchdf()
    )

    con.close()




if __name__ == "__main__":

    main()