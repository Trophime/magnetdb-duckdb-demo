from _common import *




def main(): 

    # Load proposals metadata and parse experiment date ranges.

    proposals_df = pd.read_csv(DATA_DIR / "proposals.csv")
    proposals_df["Debut"] = pd.to_datetime(proposals_df["Debut"], errors = "coerce")
    proposals_df["Fin"]   = pd.to_datetime(proposals_df["Fin"],   errors = "coerce")

    # Import the proposal matadata into DuckDB.

    con = duckdb.connect(DB)

    con.execute(
        """
            DROP TABLE IF EXISTS proposals
        """
    )
    con.register("proposals_df", proposals_df)
    con.execute(
        """
            CREATE TABLE proposals AS
            SELECT * FROM proposals_df
        """
    )

    # Inspect imported proposal table and compare with the experiments table

    print("\n" + " PROPOSALS.CSV ".center(80, "=") + "\n",
        con.execute(
            """
                DESCRIBE proposals
            """
        ).fetchdf()
    )
    print(
        con.execute(
            """
                SELECT * FROM proposals 
                LIMIT 10
            """
        ).fetchdf()
    )

    print("\n" + " EXPERIMENTS ".center(80, "=") + "\n",
        con.execute(
            """
                DESCRIBE experiments
            """
        )
    )
    print(
        con.execute(
            """
                SELECT * FROM experiments
                LIMIT 10
            """
        ).fetchdf()
    )

    # Check temporal coverage of the proposal metadata

    print("\n" + " EXPERIMENTS TIMESPAN ".center(80, "=") + "\n",
        con.execute(
            """
                SELECT MIN(file), MAX(file), COUNT(*)
                FROM experiments
            """
        ).fetchdf()
    )
    print("\n" + " HOUSING YEARSPAN ".center(80, "=") + "\n",
        con.execute(
            """
                SELECT DISTINCT year
                FROM housing_summary
                ORDER BY year
            """
        ).fetchdf()
    )
    print("\n" + " PROPOSAL TIMESPAN ".center(80, "=") + "\n",
        con.execute(
            """
                SELECT MIN(Debut), MAX(Fin), COUNT(*)
                FROM proposals
            """
        ).fetchdf()
    )

    # Add proposal column to housing_summary unless it already exists

    con.execute(
        """
            ALTER TABLE housing_summary
            ADD COLUMN IF NOT EXISTS proposal VARCHAR;
        """
    )

    # Link housing records to proposals by magnet site and experiment date

    con.execute(
        """
            UPDATE housing_summary AS h
            SET proposal = p.Acronym
            FROM proposals AS p
            WHERE h.pupitre <> '' AND h.pupitre IS NOT NULL
                AND h.housing = regexp_replace(p.Site, '[ie]$', '')
                AND strptime(right(replace(h.pupitre, '.txt', ''), 19), '%y.%m.%d - %H:%M:%S')
            BETWEEN CAST(p.Debut AS TIMESTAMP) AND CAST(p.Fin AS TIMESTAMP);
        """
    )

    # Validate the proposal linkage.

    print("\n" + " LINKAGE RESULTS ".center(80, "=") + "\n",
        con.execute(
            """
                SELECT COUNT(*) AS total, COUNT(proposal) AS linked
                FROM housing_summary;
            """
        ).fetchdf()
    )

    con.close()


    #
    # Inspect the newer proposal files ('Magnet Sites' missing)
    #

    proposals_df = pd.read_csv(DATA_DIR / "proposals_2026-07-22_with_sites.csv")
    proposals_df["Experiment Start Date"] = pd.to_datetime(proposals_df["Experiment Start Date"], errors = "coerce")
    proposals_df["Experiment End Date"]   = pd.to_datetime(proposals_df["Experiment End Date"], errors = "coerce")

    print("\n" + " PROPOSALS_2026.CSV ".center(80, "="),)
    print(proposals_df[["Acronym", "Magnet Sites", "Experiment Start Date", "Experiment End Date"]].head(), proposals_df.shape)


    # Check Magnet Sites in new proposals_2026-07-26.csv

    # print(proposals_df["Magnet Sites"].dtype)
    print("NUMBER OF ENTRIES:", len(proposals_df))
    print("OF WHICH 'Magnet Sites' non-empty:", proposals_df["Magnet Sites"].notna().sum())




if __name__ == "__main__":

    main()