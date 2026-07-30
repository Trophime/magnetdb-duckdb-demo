from _common import *




def main():

    # Load and merge housing summary JSON files into a single dataframe.
    # Each record corresponds to one experiment, with additional metadata 
    # identifying the housing and acquisition year.

    rows = []
    for file in sorted(DATA_DIR.glob("*_summary-*.json")):

        print(f"Loading {file.name}")

        housing = file.stem.split("_")[0]
        year = int(file.stem[-4: ])

        with open(file, "r") as f:
            data = json.load(f)

        df = pd.json_normalize(data)

        for col in PATH_COLUMNS:
            df[col] = df[col].apply(lambda x: Path(x).name if x else x)

        df["housing"] = housing
        df["year"] = year

        rows.append(df)

    summary_df = pd.concat(rows, ignore_index = True)

    summary_df["experiment_id"]       = None
    summary_df["field_max"]           = pd.Series(dtype = "float64")
    summary_df["field_mean"]          = pd.Series(dtype = "float64")
    summary_df["field_time_on"]       = pd.Series(dtype = "float64")
    summary_df["mode"]                = ""
    summary_df["field_signature"]     = ""
    summary_df["reference_signature"] = ""

    print(f"Found {len(summary_df)} summary files")
    print(summary_df.head())


    # Refresh the housing_summary table and display basic stats.

    con = duckdb.connect(DB)

    con.execute(
        """
            DROP TABLE IF EXISTS housing_summary
        """
    )
    con.register("summary_df", summary_df)
    con.execute(
        """
            CREATE TABLE housing_summary AS
            SELECT *
            FROM summary_df
        """
    )

    print("\nRows:\n",
        con.execute(
            """
                SELECT housing, year, COUNT(*) AS n
                FROM housing_summary
                GROUP BY housing, year
                ORDER BY housing, year
            """
        ).fetchdf()
    )


    # Perform data quality audit

    ## Check the date schema
    print("\nTABLE SCHEMA: ",
        con.execute(
            """
                DESCRIBE housing_summary
            """
        ).fetchdf()
    )
    ## Count imported records
    print("\nNUMBER OF ROWS:", 
        con.execute(
            """
                SELECT COUNT(*) FROM housing_summary
            """
        ).fetchone()[0]
    )
    ## Count number of records linked to experiments
    print("NUMBER OF MATCHES:",
        con.execute(
            """
                SELECT COUNT(*)
                FROM housing_summary AS h
                JOIN experiments AS e
                ON h.pupitre LIKE '%' || e.file
            """).fetchone()[0]
    )

    ## Check for missing files
    print("\nMISSING FILES:\n",
        con.execute(
            """
                SELECT
                    SUM(CASE WHEN overview = '' THEN 1 ELSE 0 END) AS overview,
                    SUM(CASE WHEN archive  = '' THEN 1 ELSE 0 END) AS archive,
                    SUM(CASE WHEN pupitre  = '' THEN 1 ELSE 0 END) AS pupitre
                from housing_summary
            """
        ).fetchdf()
    )
    ## Check for duplicate files
    print("\nDUPLICATE FILENAMES:\n",
        con.execute(
            """
                SELECT filename, COUNT(*) AS n
                FROM housing_summary
                GROUP BY filename
                HAVING COUNT(*) > 1
                ORDER BY n DESC
            """
        ).fetchdf()
    )

    ## List records for which no Pupitre file is available
    print(
        con.execute(
            """
                SELECT filename, housing, year, pupitre
                FROM housing_summary
                WHERE pupitre IS NULL OR pupitre = ''
                ORDER BY year, housing, filename
            """
        ).fetchdf()
    )

    con.close()




if __name__ == "__main__":
    
    main()