from _common import *




def main():

    # Compute field stats and signatures for all housing records that have not 
    # yet been processed.

    con = duckdb.connect(DB)

    rows = con.execute(
        """
            SELECT rowid, housing, pupitre
            FROM housing_summary
            WHERE pupitre <> '' AND (field_signature = '' OR field_signature IS NULL)
        """
    ).fetchall()


    start = time.perf_counter()

    with Progress() as progress:

        task = progress.add_task("Updating field stats", total=len(rows))

        for rowid, housing, pupitre in rows:
            filename = Path(pupitre).name
            filepath = PUPITRE_DIR / housing / filename
            progress.update(task, description=f"{housing}/{filename}")

            if not filepath.exists():
                progress.advance(task)
                continue

            try:
                # Load the Pupitre acquisition corresponding to the experiment.
                md = load_mrun(str(filepath), housing = housing).getMData()
                df = md.Data

                # Compute a compressed signature describing the field evolution.
                signature = Signature.from_mdata(md, "Field", "t", FIELD_THRESHOLD)
                field_signature = json.dumps({"times": signature.times, "values": signature.values})
                field = df["Field"]

                # Store the computed quantities in the database.
                con.execute(
                    """
                        UPDATE housing_summary
                        SET 
                            field_max = ?,
                            field_mean = ?,
                            field_time_on = ?,
                            field_signature = ?
                        WHERE rowid = ?
                    """, 
                    (float(field.max()), float(field.mean()), int((field > FIELD_THRESHOLD).sum()), field_signature, int(rowid))
                )

            except Exception as e:
                progress.console.print(f"[red]{filename}: {e}[/red]")

            progress.advance(task)

    end = time.perf_counter()
    print(f"Dataframe updated in {int((end - start) // 60)} m {((end - start) % 60):.2f} s")


    # Validated the update: check that field stats and signatures have been 
    # successfully added to the database.

    print(
        con.execute(
            """
                SELECT COUNT(field_max) AS field_stats, COUNT(field_signature) AS signatures
                FROM housing_summary
            """
        ).fetchdf()
    )
    print(
        con.execute(
            """
                SELECT experiment_id, field_max, field_signature
                FROM housing_summary
                WHERE field_signature <> ''
                LIMIT 10
            """
        ).fetchdf()
    )
    print(
        con.execute(
            """
                SELECT experiment_id, field_signature
                FROM housing_summary
                WHERE field_signature IS NOT NULL
                LIMIT 5
            """
        ).fetchdf()
    )
    con.close()




if __name__ == "__main__":

    main()