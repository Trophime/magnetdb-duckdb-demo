import pandas as pd
import numpy as np




def naive_downsampling(df, max_points=1000):
    step = len(df) // max_points
    downsampled_df = df.iloc[::step, :].copy()
    
    return downsampled_df

def min_max_bucketing(data_input, nb_buckets) : 

    df = data_input.copy()

    # Parameters
    M = len(df)
    W = M // nb_buckets
    selected_indexes = []
    column_y = df.columns[0]

    # Loop and dynamic cutting of the DataFrame into buckets
    for i in range(nb_buckets):
        # We determine the indexes of start and the indexes of end
        start_idx = i * W

        if i == nb_buckets - 1 :
            end_idx = M
        else :
            end_idx = start_idx + W

        # We create the bucket
        bucket = df.iloc[start_idx : end_idx]

        if not bucket.empty:
            # We extract the min and the max indexes
            min_idx = bucket[column_y].idxmin()
            max_idx = bucket[column_y].idxmax()
    
        
            # We add the min and the max in the selected_idx
            selected_indexes.append(min_idx)
            selected_indexes.append(max_idx)
        
        else:
        # In case the bucket is empty, we print a warning message with the indexes of the bucket
            print(f"Attention : bucket empty between {start_idx} and {end_idx}")

    # We delete the repetitives values
    uniques_idx = list(set(selected_indexes))
    uniques_idx = [idx for idx in uniques_idx if pd.notna(idx)]
    
    # We sort the list
    uniques_idx.sort()

    # I take in my original data frame the value wanted
    df_reduce = df.loc[uniques_idx]

    return df_reduce

def M4_aggregation(data_input, nb_buckets) : 

    df = data_input.copy()

    # Parameters
    M = len(df)
    W = M // nb_buckets
    selected_indexes = []
    column_y = df.columns[0]

    # Loop and dynamic cutting of the DataFrame into buckets
    for i in range(nb_buckets):
        # We determine the indexes of start and the indexes of end
        start_idx = i * W

        if i == nb_buckets - 1 :
            end_idx = M
        else :
            end_idx = start_idx + W

        # We create the bucket
        bucket = df.iloc[start_idx : end_idx]

        # We extract the min and the max indexes
        min_idx = bucket[column_y].idxmin()
        max_idx = bucket[column_y].idxmax()

        # We extract the first and the last indexes
        first_idx = bucket.index[0]
        last_idx = bucket.index[-1]

        # We add the min, the max, the first and the last in the selected_idx
        selected_indexes.append(min_idx)
        selected_indexes.append(max_idx)
        selected_indexes.append(first_idx)
        selected_indexes.append(last_idx)
    
    # We delete the repetitives values
    uniques_idx = list(set(selected_indexes))
    uniques_idx = [idx for idx in uniques_idx if pd.notna(idx)]

    # We sort the list
    uniques_idx.sort()

    # I take in my original data frame the value wanted
    df_reduce = df.loc[uniques_idx]


    return df_reduce


def LTTB_subsampling_pupitre(df, nb_points):
    """
    Subsampling LTTB pour les fichiers Pupitre.
    - Tous les calculs géométriques se font sur la colonne numérique 't'.
    - Chaque DataFrame du dictionnaire de sortie contient 3 colonnes : ['t', 'timestamp', col]
    """
    # Sécurité : Si le fichier a moins de points que demandé, on renvoie directement les 3 colonnes
    if len(df) <= nb_points:
        return {col: df[['t', 'timestamp', col]] for col in df.columns if col not in ['t', 'timestamp']}
    
    # On extrait la colonne X numérique ('t') pour TOUS les calculs géométriques
    x = df['t'].values
    
    # --- PRÉ-CALCULS COMMUNS (sur la colonne numérique 't') ---
    middle_data = np.arange(1, len(df) - 1)
    buckets = np.array_split(middle_data, nb_points - 2)
    
    # Pré-calcul des barycentres X
    x_C_array = np.zeros(len(buckets))
    for i in range(len(buckets)):
        if i + 1 < len(buckets):
            x_C_array[i] = np.mean(x[buckets[i + 1]])
        else:
            x_C_array[i] = x[-1]

    subsampled_dfs = {}
    
    # --- BOUCLE SUR LES COLONNES DE DONNÉES Y ---
    for col in df.columns:
        # Crucial : On ignore 't' ET 'timestamp' pour ne pas appliquer LTTB sur du temps
        if col in ['t', 'timestamp']:
            continue
            
        y = df[col].values
        if y.dtype.kind == 'M':
            y = y.astype('int64')

        indexes = [0]
        idx_A = 0

        # Calcul des aires des triangles (totalement numérique, donc aucun risque d'erreur)
        for i in range(len(buckets)):
            current_bucket = buckets[i]
            x_C = x_C_array[i]
            
            if i + 1 < len(buckets):
                y_C = np.mean(y[buckets[i + 1]])
            else:
                y_C = y[-1]

            x_A = x[idx_A]
            y_A = y[idx_A]

            x_B = x[current_bucket]
            y_B = y[current_bucket]

            area = 0.5 * np.abs((x_B - x_A) * (y_C - y_A) - (x_C - x_A) * (y_B - y_A))

            idx_max = current_bucket[np.argmax(area)]
            indexes.append(idx_max)
            idx_A = idx_max

        indexes.append(len(df) - 1)

        # C'est ici que ça change ! On extrait les 3 valeurs demandées pour cette colonne
        subsampled_dfs[col] = df.iloc[indexes][['t', 'timestamp', col]]

    return subsampled_dfs


def apply_downsampling(df, method='naive', max_points=500, nb_buckets=250, nb_buckets_M4=125):
    """
    Main function to reduce the size of the DataFrame.
    """
    # If the DataFrame is already small enough or if we don't want downsampling
    if method == 'none' or len(df) <= max_points:
        return df

    # Redirection vers le bon algorithme
    if method == 'minmax':
        return min_max_bucketing(df, nb_buckets)
    elif method == 'M4':
        return M4_aggregation(df, nb_buckets_M4)
    elif method == 'naive':
        return naive_downsampling(df, max_points)
    elif method == 'LTTB':
        return LTTB_subsampling_pupitre(df, max_points)
    else:
        print(f"Unknown method {method}. Returning raw data.")
        return df