import argparse
import logging
import os
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import scipy.signal as sg
from python_magnetrun.MagnetRun import load_mrun
from python_magnetrun.analysis.loaders import load_files_data
from python_magnetrun.log_utils import LogConfig, setup_logging

DB_PATH = os.environ.get(
    "MAGNETDB_DB_PATH", "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb"
)


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


def pick_columns(df_pupitre, df_pb):
    """Pick the current channel pair to use for lag computation.

    Prefers Idcct1/Courant_A1; falls back to Idcct3/Courant_A3 when either
    side lacks the first pair.
    """
    keys_pupitre = df_pupitre.columns
    keys_pb = df_pb.columns

    if "Idcct1" in keys_pupitre and "Courant_A1" in keys_pb:
        return "Idcct1", "Courant_A1"
    return "Idcct3", "Courant_A3"


def get_record_sources(fichier_overview, db_path=DB_PATH):
    """Look up an overview_records row's source file lists.

    Parameters
    ----------
    fichier_overview : str
        Overview filename (with or without extension); matched against
        overview_records.filename.
    db_path : str, optional
        Path to the DuckDB database.

    Returns
    -------
    tuple
        (housing, sources_pupitre, sources_overview, sources_archive)

    Raises
    ------
    ValueError
        If no matching row is found.
    """
    filename = os.path.splitext(os.path.basename(fichier_overview))[0]

    conn = duckdb.connect(db_path, read_only=True)
    try:
        row = conn.execute(
            "SELECT housing, sources_pupitre, sources_overview, sources_archive "
            "FROM overview_records WHERE filename = ?",
            [filename],
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise ValueError(f"No overview_records row found for filename={filename!r}")

    return row


def main() -> None:
    parser = argparse.ArgumentParser()
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

    fichier_overview = args.fichier_overview
    targeted_group = "Courants_Alimentations"

    housing_db, sources_pupitre, sources_overview, sources_archive = get_record_sources(
        fichier_overview
    )
    housing = args.housing or housing_db

    print(
        f"Record downloaded... overview={fichier_overview}, housing={housing}\n"
        f"sources_pupitre={sources_pupitre}\n"
        f"sources_overview={sources_overview}\n"
        f"sources_archive={sources_archive}"
    )

    try:
        # --- Merged: concatenate every file per source, then compare once ---
        df_pupitre_m = load_files_data(
            sources_pupitre, housing, targeted_group, ["Idcct1", "Idcct3"]
        )
        df_overview_m = load_files_data(
            sources_overview, housing, targeted_group, ["Courant_A1", "Courant_A3"]
        )
        df_archive_m = load_files_data(
            sources_archive, housing, targeted_group, ["Courant_A1", "Courant_A3"]
        )

        print("\n" + "=" * 40)
        print("MERGED")
        print("=" * 40)

        if not df_pupitre_m.empty and not df_overview_m.empty:
            col_pup, col_ov = pick_columns(df_pupitre_m, df_overview_m)
            lag_merged_overview = get_lag(df_pupitre_m, df_overview_m, col_pup, col_ov)
            print(f"pupitre vs overview ({col_pup}/{col_ov}): lag={lag_merged_overview:.2f}s")

        if not df_pupitre_m.empty and not df_archive_m.empty:
            col_pup, col_arc = pick_columns(df_pupitre_m, df_archive_m)
            lag_merged_archive = get_lag(df_pupitre_m, df_archive_m, col_pup, col_arc)
            print(f"pupitre vs archive  ({col_pup}/{col_arc}): lag={lag_merged_archive:.2f}s")

        # --- Not merged: compare every pupitre file against every other file ---
        print("\n" + "=" * 40)
        print("NOT MERGED")
        print("=" * 40)

        for p_file in sources_pupitre:
            mrun_p = load_mrun(filename=p_file, housing=housing)
            df_p = mrun_p.MagnetData.get_group_data(targeted_group)

            for o_file in sources_overview:
                mrun_o = load_mrun(filename=o_file, housing=housing)
                df_o = mrun_o.MagnetData.get_group_data(targeted_group)
                col_pup, col_ov = pick_columns(df_p, df_o)
                lag = get_lag(df_p, df_o, col_pup, col_ov)
                print(
                    f"pupitre={p_file} vs overview={o_file} ({col_pup}/{col_ov}): lag={lag:.2f}s"
                )

            for a_file in sources_archive:
                mrun_a = load_mrun(filename=a_file, housing=housing)
                df_a = mrun_a.MagnetData.get_group_data(targeted_group)
                col_pup, col_arc = pick_columns(df_p, df_a)
                lag = get_lag(df_p, df_a, col_pup, col_arc)
                print(
                    f"pupitre={p_file} vs archive={a_file} ({col_pup}/{col_arc}): lag={lag:.2f}s"
                )

        print("\n" + "=" * 40 + "\n")

    except Exception as e:
        print(f"Error during test {e}")


if __name__ == "__main__":
    main()
