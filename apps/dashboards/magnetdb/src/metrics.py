import numpy as np
import scipy.signal as sg
import os
from datetime import datetime
import pandas as pd


OUTPUT_DIR = "/workspaces/magnetdb-duckdb-demo/apps/dashboards/magnetdb/metrics_reports"

def get_mean(signal):
    return np.nanmean(signal)

def get_variance(signal):
    return np.nanvar(signal)

def get_rmse(y_ref, y_sec):
    """Calculate the Root Mean Square Error between two signals of the same size."""
    return np.sqrt(np.nanmean((y_ref - y_sec)**2))

def get_mae(y_ref, y_sec):
    """Calculate the Mean Absolute Error between two signals of the same size."""
    return np.nanmean(np.abs(y_ref - y_sec))

def get_pearson_correlation(y_ref, y_sec):
    """Calculate the Pearson correlation coefficient between two signals of the same size."""
    df = pd.DataFrame({'Ref': y_ref, 'Sec': y_sec})
    return df['Ref'].corr(df['Sec'])


def evaluate_metrics(y_ref, y_sec_unaligned, y_sec_aligned):
    """
    Compare results of the mean of the Reference signal with the Secondary signal, before and after applying the lag.
    """
    return {
        "Mean": {
            "Reference": get_mean(y_ref),
            "Before Alignment": get_mean(y_sec_unaligned),
            "After Alignment": get_mean(y_sec_aligned)
        },
        "Variance": {
            "Reference": get_variance(y_ref),
            "Before Alignment": get_variance(y_sec_unaligned),
            "After Alignment": get_variance(y_sec_aligned)
        },
        "Distance_RMSE": {
            "Before Alignment": get_rmse(y_ref, y_sec_unaligned),
            "After Alignment": get_rmse(y_ref, y_sec_aligned)
        },
        "Distance_MAE": {
            "Before Alignment": get_mae(y_ref, y_sec_unaligned),
            "After Alignment": get_mae(y_ref, y_sec_aligned)
        },
        "Pearson_Correlation": {
            "Before Alignment": get_pearson_correlation(y_ref, y_sec_unaligned),
            "After Alignment": get_pearson_correlation(y_ref, y_sec_aligned)
        }
    }

def generate_metrics_report(file_ref, sensor_ref, file_sec, sensor_sec, results, lag_seconds, output_dir=OUTPUT_DIR):
    """
    Creates a text file in VSCode containing the observations.
    """

    # Creation of the folder if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # File name with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"metrics_{file_ref}_vs_{file_sec}_{timestamp}.txt"
    complete_path = os.path.join(output_dir, file_name)
    
    # Writing the results
    with open(complete_path, "w", encoding="utf-8") as f:
        f.write("=== ALIGNEMENT REPORT ===\n")
        f.write(f"Reference file (Pupitre)    : {file_ref}\n")
        f.write(f"  -> Mesured captor         : {sensor_ref}\n")
        f.write(f"Secondary file (PigBrother) : {file_sec}\n")
        f.write(f"  -> Mesured captor         : {sensor_sec}\n")
        f.write(f"  -> Applied gap            : {lag_seconds:.3f} secondes\n\n")

        f.write("--- MEAN ---\n")
        f.write("-" * 45 + "\n")
        f.write(f"Mean Reference              : {results['Mean']['Reference']:.4f}\n")
        f.write(f"Mean Secondary (Raw)        : {results['Mean']['Before Alignment']:.4f}\n")
        f.write(f"Mean Secondary (Lag)        : {results['Mean']['After Alignment']:.4f}\n")
        f.write("-" * 45 + "\n\n")

        f.write("--- VARIANCE ---\n")
        f.write("-" * 45 + "\n")
        f.write(f"Reference                   : {results['Variance']['Reference']:.4e}\n")
        f.write(f"Secondary (Raw)             : {results['Variance']['Before Alignment']:.4e}\n")
        f.write(f"Secondary (Lag)             : {results['Variance']['After Alignment']:.4e}\n")
        f.write("-" * 45 + "\n\n")

        f.write("--- DISTANCE TO REFERENCE ---\n")
        f.write("-" * 45 + "\n")
        f.write(f"RMSE Before Alignment       : {results['Distance_RMSE']['Before Alignment']:.4f}\n")
        f.write(f"RMSE After Alignment        : {results['Distance_RMSE']['After Alignment']:.4f}\n")
        f.write(f"MAE Before Alignment        : {results['Distance_MAE']['Before Alignment']:.4f}\n")
        f.write(f"MAE After Alignment         : {results['Distance_MAE']['After Alignment']:.4f}\n")
        f.write("-" * 45 + "\n\n")

        f.write(f"SHAPE SIMILARITY (Pearson Correlation)\n")
        f.write(f"Before Alignment              : {results['Pearson_Correlation']['Before Alignment']:.4f}\n")
        f.write(f"After Alignment               : {results['Pearson_Correlation']['After Alignment']:.4f}\n")
        
    print(f"[metrics.py] Report generated: {complete_path}")
    return complete_path