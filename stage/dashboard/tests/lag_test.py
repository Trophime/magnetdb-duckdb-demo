import numpy as np
import pandas as pd
import scipy.signal as sg
from python_magnetrun.MagnetRun import load_mrun

def get_lag(df_pupitre, df_pb, column_current_pupitre='Idcct1', column_current_pigbrother='Courant_A1'):
    """
    Calculate the time lag with high precision using FFT on normalized derivatives.
    """

    # 1.Convert timestamps to seconds and extract current values
    t_pupitre = df_pupitre['timestamp'].astype('int64') / 10**9
    t_pb = df_pb['timestamp'].astype('int64') / 10**9

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
    y_pup_norm = (y_pupitre_interp - np.mean(y_pupitre_interp)) / (np.std(y_pupitre_interp) + 1e-9)
    y_pb_norm = (y_pb_interp - np.mean(y_pb_interp)) / (np.std(y_pb_interp) + 1e-9)

    # 6. Compute the derivatives of the normalized signals
    dy_pupitre = np.gradient(y_pup_norm)
    dy_pb = np.gradient(y_pb_norm)

    # 7. Correlation using FFT 
    correlation = sg.correlate(dy_pupitre, dy_pb, mode='full', method='fft')
    lags = sg.correlation_lags(len(dy_pupitre), len(dy_pb), mode='full')

    # 8. Extract best shift (lag) in seconds
    index_max = np.argmax(correlation)
    best_lag_indices = lags[index_max]

    # Convert in seconds
    lag_seconds = float(best_lag_indices * dt)

    return lag_seconds

if __name__ == "__main__":
    
    # 1. Renseigne les chemins des fichiers de test
    fichier_pupitre = "2025.12.02 - 14:30:46.txt"
    fichier_overview = "M9_Overview_251202-1430.tdms"
    housing = "M9" 

    targeted_group = "Courants_Alimentations"
    
    print(f"Files downloading...")
    
    try:
        # 2. Chargement des données 
        mrun_pupitre = load_mrun(filename=fichier_pupitre, housing=housing)
        df_pupitre = mrun_pupitre.MagnetData.get_group_data(targeted_group) # Adapte le nom du groupe si besoin
        
        mrun_pb = load_mrun(filename=fichier_overview, housing=housing)
        df_pb = mrun_pb.MagnetData.get_group_data(targeted_group) # Adapte le nom du groupe si besoin
        
        # 3. Lancement du calcul
        print(f"Lag calculation in progress...")
        lag = get_lag(df_pupitre, df_pb)
        
        print("\n" + "="*40)
        print(f"LAG RESULT: {lag:.2f} seconds")
        print("="*40 + "\n")
        
    except Exception as e:
        print(f"Error during test {e}")