import numpy as np
import scipy.signal as sg
import os
from datetime import datetime


OUTPUT_DIR = "/workspaces/2026-m1-hifimagnet/stage/dashboard/metrics_reports"  

def get_mean(signal):
    return np.nanmean(signal)

def get_variance(signal):
    return np.nanvar(signal)




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
        }
    }

def generate_metrics_report(file_ref, sensor_ref, file_sec, sensor_sec, results, lag_seconds, output_dir=OUTPUT_DIR):
    """
    Creates a text file in VSCode containing the observations.
    """
    import os
    from datetime import datetime

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
        f.write(f"  -> Mesured captor        : {sensor_ref}\n\n")
        f.write(f"Secondary file (PigBrother) : {file_sec}\n")
        f.write(f"  -> Mesured captor         : {sensor_sec}\n")
        
        # Écriture du lag
        f.write(f"  -> Applied gap     : {lag_seconds:.3f} secondes\n")

        f.write("--- MEAN ---\n")

        f.write("-" * 45 + "\n")
        f.write(f"Mean Reference             : {results['Mean']['Reference']:.4f}\n")
        f.write(f"Mean Secondary (Raw)       : {results['Mean']['Before Alignment']:.4f}\n")
        f.write(f"Mean Secondary (Lag)       : {results['Mean']['After Alignment']:.4f}\n")
        f.write("-" * 45 + "\n")

        f.write("--- VARIANCE ---\n")
        # On utilise le format exponentiel (.4e) car la variance peut être un très grand nombre
        f.write(f"Reference             : {results['Variance']['Reference']:.4e}\n")
        f.write(f"Secondary (Raw)       : {results['Variance']['Before Alignment']:.4e}\n")
        f.write(f"Secondary (Lag)       : {results['Variance']['After Alignment']:.4e}\n")
        f.write("-" * 45 + "\n")
        
    return complete_path