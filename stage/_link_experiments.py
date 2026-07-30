from _common import *




# ### Link with the user DB: Add foreign key column and populate

def main():

    # Link each housing summary record to the corresponding experiment stored 
    # in MagnetDB using Pupitre filename.

    con = duckdb.connect(DB)

    con.execute(
        """
            UPDATE housing_summary AS h
            SET experiment_id = e.id
            FROM experiments AS e
            WHERE h.pupitre LIKE '%' || e.file
        """
    )

    # Validate the linkade by reporting the number of matched experiments and
    # several linked records.

    print("\nLINKED EXPERIMENTS:",
        con.execute(
            """
                SELECT COUNT(*)
                FROM housing_summary
                WHERE experiment_id IS NOT NULL
            """
        ).fetchone()[0]
    )
    print(
        con.execute(
            """
                SELECT experiment_id, filename, pupitre
                FROM housing_summary
                WHERE experiment_id IS NOT NULL
                LIMIT 10
            """
        ).fetchdf()
    )
    print(
        con.execute(
            """
                SELECT h.experiment_id, e.name, e.file, h.pupitre
                FROM housing_summary AS h
                JOIN experiments AS e
                ON h.experiment_id = e.id
                LIMIT 10
            """
        ).fetchdf()
    )

    con.close()




if __name__ == "__main__":
    
    main()