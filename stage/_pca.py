from _common import *

from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA




def load_data():

    # Load experiments for which all required field statistics, research area 
    # and field signature are available.

    con = duckdb.connect(DB)

    df = con.execute(
        """
            SELECT *
            FROM overview_experiments
            WHERE
                research_area IS NOT NULL
                AND field_max IS NOT NULL
                AND field_mean IS NOT NULL
                AND field_std IS NOT NULL
                AND field_median IS NOT NULL
                AND field_time_on IS NOT NULL
                AND field_signature IS NOT NULL
        """
    ).fetchdf()

    con.close()

    return df


def get_pca_features(df, scenario_number):

    # Build the feature matrix for one of the three PCA scenarios.
    # Each scenario uses a different description of the magnetic field.

    if scenario_number == 1:

        # Use the global field statistics already stored in housing_summary.

        columns = ["field_max", "field_mean",  
                "field_std", "field_median",
                "field_time_on"]

        X = df[columns]

    else:

        # Use additional characteristics extracted from the compressed field 
        # signature.

        raw_params = []

        for _, row in df.iterrows():

            signature = json.loads(row["field_signature"])

            times = signature["times"]
            values  = signature["values"]

            # Compute the duration and the number of changes represented by the 
            # field signature.

            duration = times[-1] - times[0]
            n_changes = len(times) - 1

            if scenario_number == 2:

                # Use maximum magnetic field and the basic characteristics of 
                # the field signature.

                field_range = max(values) - min(values)

                raw_params.append([row["field_max"], duration, n_changes, max(values), field_range])
                columns = ["field_max", "duration", "n_changes", "signature_max", "signature_range"]

            elif scenario_number == 3:

                # Use the density and the rate of the changes in magnetic 
                # field.

                change_density = n_changes / duration if duration > 0 else 0

                slopes = []
                total_variation = 0

                for i in range(n_changes):

                    # Compute the absolute field variation rate between two 
                    # consecutive points of the signature, then accumulate the 
                    # total absolute change in the field.

                    if times[i + 1] - times[i] > 0:
                        slopes.append(abs((values[i + 1] - values[i]) / (times[i + 1] - times[i])))
                    total_variation += abs((values[i + 1] - values[i]))

                max_slope = max(slopes) if slopes else 0
                mean_slope = sum(slopes) / len(slopes) if slopes else 0

                raw_params.append([row["field_max"], duration, change_density, max_slope, mean_slope, total_variation])
                columns = ["field_max", "duration", "change_density", "max_slope", "mean_slope", "total_variation"]

            X = pd.DataFrame(raw_params, columns = columns)

    return X, columns

def run_pca(X):

    # Standardise the features so that the contribution of the variables is
    # is commensurate with their scales.

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    pca = PCA(n_components = 2)
    X_pca = pca.fit_transform(X_scaled)

    return pca, X_pca

def print_pca_results(pca, columns):

    # Report the amount of variance explained by each principal component.

    print("\nExplained variance ratio:\n",
        pd.DataFrame(
            {
                "Component": ["PC1", "PC2"],
                "Variance": pca.explained_variance_ratio_
            }
        )
    )

    # Report the contribution of each original feature to the principal 
    # components (loadings).

    loadings = pd.DataFrame(
        pca.components_.T,
        index = columns,
        columns = ["PC1", "PC2"]
    )

    print("\nPCA loadings:\n", loadings)

def plot_pca_results(df, X_pca, pca, png_name, title):

    # Plot the PCA representation and colour the experiments by research area.

    plt.figure(figsize = (10, 6))

    for area in sorted(df["research_area"].unique()):

        mask = df["research_area"] == area

        plt.scatter(X_pca[mask, 0], X_pca[mask, 1], s = 25, alpha = 0.8, label = area)

    plt.xlabel(f"PC1 ({100 * pca.explained_variance_ratio_[0]:.2f}% variance)")
    plt.ylabel(f"PC2 ({100 * pca.explained_variance_ratio_[1]:.2f}% variance)")
    plt.title(title)
    plt.legend(fontsize = 8, loc = "best")
    plt.tight_layout()

    png_name = RESULTS_DIR / png_name
    plt.savefig(png_name, dpi = 500)
    plt.close()

    print(f"\nPCA result is saved to {RESULTS_DIR / png_name}.")




def main():

    # Perform PCA on three different feature sets describing the magnetic 
    # field experiments.

    print_title("PCA")

    df = load_data()
    print(f"Loaded {len(df)} experiment records from overview_experiments.")

    # Run the three scenarios using the same set of experiments.

    for scenario in [1, 2, 3]:

        print_title(f"PCA-{scenario}")

        X, columns = get_pca_features(df, scenario)
        print("Features:", columns)
        pca, X_pca = run_pca(X)

        print_pca_results(pca, columns)

        if scenario == 1:
            png_name = "pca_research_area.png"

        elif scenario == 2:
            png_name = "pca_research_area2.png"

        elif scenario == 3:
            png_name = "pca_research_area3.png"

        plot_pca_results(df, X_pca, pca, png_name, f"PCA of experiments grouped by research area (scenario {scenario}).")




if __name__ == "__main__":

    main()