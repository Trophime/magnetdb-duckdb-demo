import duckdb
import matplotlib.pyplot as plt
from _common import DB


def plot_stats_per_research_field(stats, title, ylabel, field2, png_name):

    plt.figure(figsize = (10, 6))
    bars = plt.bar(stats["research_area"], stats[field2])

    for bar in bars:

        value = bar.get_height()

        label = f"{int(value)}" if value.is_integer() else f"{value:.2f}"

        plt.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            label,
            ha = "center", va = "bottom"
        )

    plt.title(title)
    plt.ylabel(ylabel)
    plt.xticks(rotation = 30)
    plt.grid(axis = "y", alpha = 0.3)
    plt.tight_layout()

    plt.savefig(png_name, dpi = 500)
    plt.close()

    print("Figure saved to ", png_name)


def main():

    # Link overview_experiments to users directly via
    # users.overview_records_ids (already maintained by
    # to_duckdb/demos/users_table_demo.py) -- no proposals.csv/
    # EXPERIENCES_LOG.csv and no experiment_id detour needed.

    con = duckdb.connect(DB)

    con.execute(
        """
            UPDATE overview_experiments AS oe
            SET
                user_acronym  = u.acronym,
                research_area = u.research_area,
                country       = u.country,
                access_mode   = u.access_mode,
                user_type     = u.type
            FROM users AS u
            WHERE list_contains(u.overview_records_ids, oe.filename)
        """
    )

    # Validation

    n_total = con.execute(
        """
            SELECT COUNT(*)
            FROM overview_experiments
        """
    ).fetchone()[0]
    n_linked = con.execute(
        """
            SELECT COUNT(*)
            FROM overview_experiments
            WHERE user_acronym IS NOT NULL
        """
    ).fetchone()[0]
    print(f"\nLinked users: {n_linked} / {n_total} ({n_linked / n_total * 100 :.2f}%)")

    n_matches = 20
    print("\n" + f" FIRST {n_matches} MATCHES ".center(80, "=") + "\n",
        con.execute(
            f"""
                SELECT
                    experiment_id, filename, user_acronym,
                    research_area, access_mode, user_type
                FROM overview_experiments
                WHERE user_acronym IS NOT NULL
                LIMIT {n_matches}
            """
        ).fetchdf()
    )

    print("\n" + " MATCHES PER RESEARCH AREA ".center(80, "=") + "\n",
        con.execute(
            """
                SELECT research_area, COUNT(*) AS n
                FROM overview_experiments
                WHERE research_area IS NOT NULL
                GROUP BY research_area
                ORDER BY n DESC
            """
        ).fetchdf()
    )

    print("\n" + " UNLINKED RECORDS BY HOUSING AND YEAR ".center(80, "=") + "\n",
        con.execute(
            """
                SELECT
                    housing, year, COUNT(*) AS n
                FROM overview_experiments
                WHERE user_acronym IS NULL
                GROUP BY housing, year
                ORDER BY year, housing
            """
        ).fetchdf()
    )

    stats = con.execute(
        """
            SELECT
                research_area,
                MIN(year) AS first_year, MAX(year) AS last_year,
                MIN(e.name) AS first_experiment, MAX(e.name) AS last_experiment,
                COUNT(*) AS n_experiments, COUNT(DISTINCT user_acronym) AS n_users,
                AVG(field_max) AS mean_field_T,
                MAX(field_max) AS max_field_T,
                AVG(field_mean) AS mean_field_avg_T,
                AVG(field_time_on) AS mean_field_time_s,
                SUM(field_time_on) AS total_field_time_s
            FROM overview_experiments AS oe
            JOIN experiments AS e
            ON oe.experiment_id = e.id
            WHERE research_area IS NOT NULL
            GROUP BY research_area
            ORDER BY n_experiments DESC
        """
    ).fetchdf()

    print("\n" + " STATISTICS PER RESEARCH AREA ".center(80, "=") + "\n",
        stats.to_string(index = False))

    # Visulalise the statistics per research area

    plot_stats_per_research_field(stats,
        "Experiments per research area",
        "Number of experiments", "n_experiments",
        "research_area_experiments.png")
    plot_stats_per_research_field(stats,
        "Total field time per research area",
        "Total field time (s)", "total_field_time_s",
        "research_area_field_time.png")
    plot_stats_per_research_field(stats,
        "Mean magnetic field per research area",
        "Mean field (T)", "mean_field_T",
        "research_area_mean_field.png")

    con.close()




if __name__ == "__main__":

    main()
