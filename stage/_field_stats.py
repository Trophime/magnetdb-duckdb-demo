from _common import *




def main():

    # Fill in field_max/field_mean/field_std/field_median/field_time_on from
    # the per-experiment scalars already computed by to_duckdb's
    # compute_exp_stats.py (exp_run_scalars) -- no raw file I/O needed for
    # these. field_signature is the only value that still requires loading
    # the raw Pupitre file, since the compressed time/value/regime signature
    # isn't stored anywhere else.

    print_title("3. FIELD STATISTICS")

    con = duckdb.connect(DB)

    con.execute(
        """
            WITH pivoted AS (
                SELECT
                    experiment_id,
                    MAX(CASE WHEN channel = 'field_max'            THEN value END) AS field_max,
                    MAX(CASE WHEN channel = 'field_mean'           THEN value END) AS field_mean,
                    MAX(CASE WHEN channel = 'field_std'            THEN value END) AS field_std,
                    MAX(CASE WHEN channel = 'field_median'         THEN value END) AS field_median,
                    MAX(CASE WHEN channel = 'duration_field_on_s'  THEN value END) AS field_time_on
                FROM exp_run_scalars
                GROUP BY experiment_id
            )
            UPDATE overview_experiments AS oe
            SET
                field_max     = p.field_max,
                field_mean    = p.field_mean,
                field_std     = p.field_std,
                field_median  = p.field_median,
                field_time_on = p.field_time_on
            FROM pivoted AS p
            WHERE oe.experiment_id = p.experiment_id
        """
    )

    n_with_exp = con.execute(
        "SELECT COUNT(*) FROM overview_experiments WHERE experiment_id IS NOT NULL"
    ).fetchone()[0]
    n_with_stats = con.execute(
        "SELECT COUNT(*) FROM overview_experiments WHERE field_max IS NOT NULL"
    ).fetchone()[0]

    print(f"\nField scalars filled in from exp_run_scalars: {n_with_stats} / {n_with_exp} "
          f"linked rows ({100 * n_with_stats / n_with_exp:.2f}%).")
    print("Rows with a linked experiment but no exp_run_scalars entry yet need "
          "compute_exp_stats.py run/reprocessed for that experiment.")

    # Compute field_signature for rows that have a Pupitre file but no
    # signature yet.

    rows = con.execute(
        """
            SELECT rowid, housing, pupitre_file
            FROM overview_experiments
            WHERE pupitre_file IS NOT NULL AND field_signature IS NULL
        """
    ).fetchall()

    start = time.perf_counter()

    with Progress() as progress:

        task = progress.add_task("Computing field signatures", total=len(rows))

        for rowid, housing, pupitre_file in rows:

            filepath = PUPITRE_DIR / housing / pupitre_file
            progress.update(task, description = f"{housing}/{pupitre_file}")

            if not filepath.exists():
                progress.advance(task)
                continue

            try:

                md = load_mrun(str(filepath), housing = housing).getMData()
                signature = Signature.from_mdata(md, "Field", "t", FIELD_THRESHOLD)
                field_signature = json.dumps({
                    "times": signature.times,
                    "values": signature.values,
                    "regimes": signature.regimes,
                })

                con.execute(
                    """
                        UPDATE overview_experiments
                        SET field_signature = ?
                        WHERE rowid = ?
                    """,
                    (field_signature, int(rowid))
                )

            except Exception as e:

                progress.console.print(f"[red]{pupitre_file}: {e}[/red]")

            progress.advance(task)

    end = time.perf_counter()
    print(f"Signatures updated in {int((end - start) // 60)} m {((end - start) % 60):.2f} s.")

    n_signatures = con.execute(
        "SELECT COUNT(field_signature) FROM overview_experiments"
    ).fetchone()[0]
    print(f"Field signatures in database: {n_signatures}")

    con.close()




if __name__ == "__main__":

    main()
