import logging
import plotly.graph_objects as go
import pandas as pd
from python_magnetrun.utils.downsampling import downsample_dataframe, DownsampleConfig

logger = logging.getLogger(__name__)

_METHOD_MAP = {
    'lttb': 'lttb', 'LTTB': 'lttb',
    'minmax': 'minmax',
    'm4': 'm4', 'M4': 'm4',
    'naive': 'stride', 'stride': 'stride',
}
_DEFAULT_N_OUT = 1000

def create_plot(df, x_col: str, y_cols: list, method: str, filename: str = "", mrun=None, group_name: str = "") -> go.Figure:
    """
    Gère le sous-échantillonnage et génère la figure Plotly pour Pupitre ET PigBrother.
    """
    if df is None or df.empty:
        return go.Figure()

    # 1. Récupération dynamique de l'unité
    unit = "Valeur"
    if mrun and len(y_cols) > 0:
        sensor = y_cols[0]
        try:
            _, unit_str = mrun.getUnit(sensor)
            if unit_str:
                unit = str(unit_str)
        except RuntimeError:
            try:
                _, unit_str = mrun.getUnit(f"{group_name}/{sensor}")
                if unit_str:
                    unit = str(unit_str)
            except RuntimeError:
                logger.debug(
                    "No unit found for sensor %r (group %r) in either Pupitre or PigBrother key format",
                    sensor, group_name,
                )

    # 2. Gestion du Downsampling
    downsample_method = 'none' if (not method or method in ['raw data', 'raw', 'none']) else method

    if downsample_method == 'none':
        df_plot = df
    else:
        try:
            config = DownsampleConfig(n_out=_DEFAULT_N_OUT, method=_METHOD_MAP.get(downsample_method, 'stride'))
            df_plot = downsample_dataframe(df, time_col=x_col, value_cols=list(y_cols), config=config)
        except Exception as e:
            print(f"Erreur downsampling sur {filename}: {e}")
            df_plot = df

    x_label_mapping = {'t': 't(s)', 'timestamp': 'Date / Time'}
    x_title = x_label_mapping.get(x_col, x_col)

    fig = go.Figure()

    # 3. Traitement robuste des colonnes (Gère 'Groupe/Capteur' ET 'Capteur')
    for sensor in y_cols:
        target_col = None
        
        # CAS A : Dictionnaire LTTB
        if isinstance(df_plot, dict):
            if sensor in df_plot:
                sub_df = df_plot[sensor]
                # Chercher le nom exact ou le nom court
                short_name = sensor.split('/')[-1]
                if sensor in sub_df.columns:
                    target_col = sensor
                elif short_name in sub_df.columns:
                    target_col = short_name

                if target_col and x_col in sub_df.columns:
                    fig.add_trace(go.Scattergl(
                        x=sub_df[x_col],
                        y=sub_df[target_col],
                        mode='lines',
                        name=sensor,
                        line=dict(width=2)
                    ))

        # CAS B : DataFrame classique (M4, MinMax, Naive, Raw)
        else:
            short_name = sensor.split('/')[-1]
            
            # Vérifier si la colonne s'appelle 'Group/Capteur' ou juste 'Capteur'
            if sensor in df_plot.columns:
                target_col = sensor
            elif short_name in df_plot.columns:
                target_col = short_name

            if target_col and x_col in df_plot.columns:
                fig.add_trace(go.Scattergl(
                    x=df_plot[x_col],
                    y=df_plot[target_col],
                    mode='lines',
                    name=sensor,
                    line=dict(width=2)
                ))

    # 4. Layout
    fig.update_layout(
        title=f"Visualization : {filename} (Algo: {method})",
        template="plotly_white",
        margin=dict(l=40, r=40, t=60, b=40),
        xaxis=dict(title=x_title),
        yaxis=dict(title=f"Value : {unit}"),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        uirevision='constant',
    )

    return fig