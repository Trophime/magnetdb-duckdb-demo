import argparse
import logging
from pathlib import Path

import numpy as np
import scipy.signal as sg
from python_magnetrun.log_utils import LogConfig, setup_logging
from python_magnetrun.MagnetRun import load_mrun


def get_lag(
    df_pupitre,
    df_pb,
    column_current_pupitre="Idcct1",
    column_current_pigbrother="Courant_A1",
):
    """
    Calculate the time lag with high precision using FFT on normalized derivatives.
    """

    # 1.Convert timestamps to seconds and extract current values
    t_pupitre = df_pupitre["timestamp"].astype("int64") / 10**9
    t_pb = df_pb["timestamp"].astype("int64") / 10**9

    y_pupitre = df_pupitre[column_current_pupitre].values
    y_pb = df_pb[column_current_pigbrother].values

    # 2. Identify the TRUE overlap zone (INTERSECTION, not union)
    t_min = max(t_pupitre.min(), t_pb.min())
    t_max = min(t_pupitre.max(), t_pb.max())

    if t_max - t_min < 10.0:
        return 0.0

    # 3. Create a common time vector with a fixed step (dt) for interpolation
    dt = 0.05
    t_commun = np.arange(t_min, t_max, dt)

    # 4. Linear interpolation of both signals onto the common time vector
    y_pupitre_interp = np.interp(t_commun, t_pupitre, y_pupitre)
    y_pb_interp = np.interp(t_commun, t_pb, y_pb)

    # 5. Normalization of both signals
    y_pup_norm = (y_pupitre_interp - np.mean(y_pupitre_interp)) / (
        np.std(y_pupitre_interp) + 1e-9
    )
    y_pb_norm = (y_pb_interp - np.mean(y_pb_interp)) / (np.std(y_pb_interp) + 1e-9)

    # 6. Compute the derivatives of the normalized signals
    dy_pupitre = np.gradient(y_pup_norm)
    dy_pb = np.gradient(y_pb_norm)

    # 7. Correlation using FFT
    correlation = sg.correlate(dy_pupitre, dy_pb, mode="full", method="fft")
    lags = sg.correlation_lags(len(dy_pupitre), len(dy_pb), mode="full")

    # 8. Extract best shift (lag) in seconds
    index_max = np.argmax(correlation)
    best_lag_indices = lags[index_max]

    # Convert in seconds
    lag_seconds = float(best_lag_indices * dt)

    return lag_seconds


def main() -> None:
    # 1. Renseigne les chemins des fichiers de test
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fichier-pupitre",
        default="2025.12.02 - 14:30:46.txt",
    )
    parser.add_argument(
        "--fichier-overview",
        default="M9_Overview_251202-1430.tdms",
    )
    parser.add_argument(
        "--housing",
        default=None,
    )
    parser.add_argument(
        "--log-file",
        default=str(Path(__file__).with_suffix(".log")),
    )
    args = parser.parse_args()

    setup_logging(config=LogConfig(level=logging.INFO, console=False, log_file=Path(args.log_file)))

    fichier_pupitre = args.fichier_pupitre
    fichier_overview = args.fichier_overview
    housing = args.housing or fichier_overview.split("_")[0]

    targeted_group = "Courants_Alimentations"

    print(
        f"Files downloading... pupitre={fichier_pupitre}, overview={fichier_overview}, housing={housing}"
    )

    try:
        # 2. Chargement des données
        mrun_pupitre = load_mrun(filename=fichier_pupitre, housing=housing)
        df_pupitre = mrun_pupitre.MagnetData.get_group_data(
            targeted_group
        )  # Adapte le nom du groupe si besoin

        mrun_pb = load_mrun(filename=fichier_overview, housing=housing)
        df_pb = mrun_pb.MagnetData.get_group_data(
            targeted_group
        )  # Adapte le nom du groupe si besoin

        # 3. Lancement du calcul
        keys_pupitre = df_pupitre.columns
        keys_pb = df_pb.columns

        if "Idcct1" in keys_pupitre and "Courant_A1" in keys_pb:
            column_current_pupitre = "Idcct1"
            column_current_pigbrother = "Courant_A1"
        else:
            column_current_pupitre = "Idcct3"
            column_current_pigbrother = "Courant_A3"

        print(
            f"Lag calculation for {column_current_pupitre} vs {targeted_group}/{column_current_pigbrother} in progress..."
        )
        lag = get_lag(
            df_pupitre,
            df_pb,
            column_current_pupitre=column_current_pupitre,
            column_current_pigbrother=column_current_pigbrother,
        )

        print("\n" + "=" * 40)
        print(f"LAG RESULT: {lag:.2f} seconds")
        print("=" * 40 + "\n")

        
    except Exception as e:
        print(f"Error during test {e}")


if __name__ == "__main__":
    main()
