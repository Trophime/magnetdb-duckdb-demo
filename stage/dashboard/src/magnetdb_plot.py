import logging
import plotly.graph_objects as go
import pandas as pd
from python_magnetrun.utils.downsampling import downsample_dataframe, DownsampleConfig

logger = logging.getLogger(__name__)

def create_plot(df, x_col: str, y_cols: list, method: str, filename: str = "", mrun=None, group_name: str = "") -> go.Figure:
    """
    Gère le sous-échantillonnage et génère la figure Plotly.
    """

    # 1. Récupération dynamique de l'unité
    unit = "Valeur"
    if mrun and len(y_cols) > 0:
        sensor = y_cols[0]
        try:
            # Tentative 1 : Format Pupitre (Recherche directe)
            _, unit_str = mrun.getUnit(sensor)
            if unit_str:
                unit = str(unit_str)
        except RuntimeError:
            try:
                # Tentative 2 : Format PigBrother (Groupe/Capteur)
                _, unit_str = mrun.getUnit(f"{group_name}/{sensor}")
                if unit_str:
                    unit = str(unit_str)
            except RuntimeError:
                logger.debug(
                    "No unit found for sensor %r (group %r) in either Pupitre or PigBrother key format",
                    sensor, group_name,
                )

    # 2. Gestion du Sous-échantillonnage
    # On vérifie bien qu'une méthode est choisie et que ce n'est PAS "raw data"
    if method and method != 'raw data':
        config = DownsampleConfig(method=method, n_out=1000)
        try:
            df_plot = downsample_dataframe(df, x_col, y_cols, config)
        except Exception as e:
            print(f"Erreur lors du downsampling avec {method}: {e}")
            df_plot = df
    else:
        # Si 'raw data' ou aucune méthode, on ne touche pas au DataFrame
        df_plot = df


    x_label_mapping = {
        't': 't(s)',
        'timestamp': 'Date / Time'
    }
    
    # On récupère le label personnalisé, ou on garde le nom de la colonne par défaut
    x_title = x_label_mapping.get(x_col, x_col)

    # 3. Création de la figure
    fig = go.Figure()


    # On boucle directement sur y_cols (qui est déjà garanti d'être une liste)
    for sensor in y_cols:
        if sensor in df_plot.columns: 
            fig.add_trace(go.Scattergl(
                x=df_plot[x_col],
                y=df_plot[sensor],
                mode='lines',
                name=sensor, # Utilise directement le nom du capteur
                line=dict(width=2)
            ))

    # 4. Mise en forme
    fig.update_layout(
        title=f"Visualization : {filename} (Algo: {method})",
        template="plotly_white",
        margin=dict(l=40, r=40, t=60, b=40),
        xaxis=dict(title=x_title), # Utilise directement le nom de la colonne X ('t' ou 'timestamp')
        yaxis=dict(title=f"Value : {unit}"),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified"
    )

    return fig