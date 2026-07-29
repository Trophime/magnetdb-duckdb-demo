import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import pandas as pd
from python_magnetrun.utils.downsampling import downsample_dataframe, DownsampleConfig
from python_magnetrun.utils.files import classify_pigbrother_file

logger = logging.getLogger(__name__)

_METHOD_MAP = {
    'lttb': 'lttb', 'LTTB': 'lttb',
    'minmax': 'minmax',
    'm4': 'm4', 'M4': 'm4',
    'naive': 'stride', 'stride': 'stride',
}
_DEFAULT_N_OUT = 1000


@dataclass
class TraceStyle:
    """Plotly line style for one data-file type (matplotlib-like: color/dash/width/alpha)."""

    color: str = "#1f77b4"
    dash: str = "solid"
    width: float = 2
    opacity: float = 1.0


@dataclass
class FileTypeStyles:
    """Per data-file-type line styling, keyed by 'pupitre' or a classify_pigbrother_file() mode key."""

    pupitre: TraceStyle = field(default_factory=lambda: TraceStyle("#2ca02c", "solid", 2, 1.0))
    overview: TraceStyle = field(default_factory=lambda: TraceStyle("#1f77b4", "solid", 2, 1.0))
    archive: TraceStyle = field(default_factory=lambda: TraceStyle("#ff7f0e", "solid", 2, 1.0))
    default: TraceStyle = field(default_factory=lambda: TraceStyle("#9467bd", "dot", 1.5, 0.8))
    spike: TraceStyle = field(default_factory=lambda: TraceStyle("#d62728", "dash", 1.5, 0.9))
    trigger: TraceStyle = field(default_factory=lambda: TraceStyle("#8c564b", "dashdot", 1.5, 0.8))

    def get(self, file_type: str | None) -> TraceStyle | None:
        """Return the TraceStyle for *file_type*, or None if unset/unrecognised."""
        if file_type is None:
            return None
        return getattr(self, file_type, None)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FileTypeStyles":
        kwargs = {
            f.name: TraceStyle(**data[f.name])
            for f in fields(cls)
            if f.name in data
        }
        return cls(**kwargs)


def load_file_type_styles(path: str | Path) -> FileTypeStyles:
    """Load a :class:`FileTypeStyles` from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return FileTypeStyles.from_dict(data)


def save_file_type_styles(styles: FileTypeStyles, path: str | Path) -> None:
    """Save a :class:`FileTypeStyles` to a JSON file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(styles.to_dict(), f, indent=2)


def _load_default_file_type_styles() -> FileTypeStyles:
    """Return FileTypeStyles from $MAGNETDB_FILE_TYPE_STYLES, or package defaults."""
    path = os.environ.get("MAGNETDB_FILE_TYPE_STYLES")
    if path:
        try:
            return load_file_type_styles(path)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not load $MAGNETDB_FILE_TYPE_STYLES=%s: %s — using defaults", path, exc
            )
    return FileTypeStyles()


FILE_TYPE_STYLES = _load_default_file_type_styles()


def _resolve_file_style(filename: str) -> TraceStyle | None:
    """Return the FILE_TYPE_STYLES entry for *filename*, or None if unresolved.

    None (rather than a fallback style) lets callers keep Plotly's default
    per-trace color cycling for filenames that don't map to a known type —
    e.g. home.py passes a composite "file - group" string for the plot title.
    """
    if filename.endswith('.txt'):
        return FILE_TYPE_STYLES.get('pupitre')
    file_type = classify_pigbrother_file(filename)
    return FILE_TYPE_STYLES.get(file_type)

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

    # 2b. Style (color/dash/width/alpha) selon le type de fichier
    style = _resolve_file_style(filename)
    line_kwargs = dict(width=style.width, color=style.color, dash=style.dash) if style else dict(width=2)
    trace_opacity = style.opacity if style else 1.0

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
                        line=dict(line_kwargs),
                        opacity=trace_opacity
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
                    line=dict(line_kwargs),
                    opacity=trace_opacity
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


def create_comparison_plot(df_unaligned, df_aligned, x_col: str, y_cols: list, method: str, filename: str = "", mrun=None, group_name: str = "") -> go.Figure:
    """
    Gère le sous-échantillonnage et génère une figure Plotly avec deux subplots (Avant / Après).
    Basé sur la logique stricte de create_plot.
    """
    if (df_unaligned is None or df_unaligned.empty) and (df_aligned is None or df_aligned.empty):
        return go.Figure()

    # 1. Récupération dynamique de l'unité
    unit = "Valeur"
    if mrun and len(y_cols) > 0:
        sensor = y_cols[0]
        try:
            _, unit_str = mrun.getUnit(sensor)
            if unit_str: unit = str(unit_str)
        except RuntimeError:
            try:
                _, unit_str = mrun.getUnit(f"{group_name}/{sensor}")
                if unit_str: unit = str(unit_str)
            except RuntimeError:
                pass # Fallback géré silencieusement

    x_label_mapping = {'t': 't(s)', 'timestamp': 'Date / Time'}
    x_title = x_label_mapping.get(x_col, x_col)

    # Création de la figure avec subplots. 
    # shared_xaxes=True est la magie qui synchronise le zoom avec la souris !
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        subplot_titles=("Signaux Bruts (Avant alignement)", "Signaux Synchronisés (Après alignement)")
    )

    # 2b. Style (color/dash/width/alpha)
    style = _resolve_file_style(filename)
    line_kwargs = dict(width=style.width, color=style.color, dash=style.dash) if style else dict(width=2)
    trace_opacity = style.opacity if style else 1.0

    downsample_method = 'none' if (not method or method in ['raw data', 'raw', 'none']) else method

    # --- BOUCLE SUR LES DEUX ÉTATS (Row 1 = Non Aligné, Row 2 = Aligné) ---
    for row, df_current in enumerate([df_unaligned, df_aligned], start=1):
        if df_current is None or df_current.empty:
            continue

        # 2. Gestion du Downsampling INDÉPENDANT pour chaque état
        if downsample_method == 'none':
            df_plot = df_current
        else:
            try:
                config = DownsampleConfig(n_out=_DEFAULT_N_OUT, method=_METHOD_MAP.get(downsample_method, 'stride'))
                df_plot = downsample_dataframe(df_current, time_col=x_col, value_cols=list(y_cols), config=config)
            except Exception as e:
                print(f"Erreur downsampling sur {filename} (row {row}): {e}")
                df_plot = df_current

        # 3. Traitement robuste des colonnes
        for sensor in y_cols:
            target_col = None

            # CAS A : Dictionnaire LTTB
            if isinstance(df_plot, dict):
                if sensor in df_plot:
                    sub_df = df_plot[sensor]
                    short_name = sensor.split('/')[-1]
                    if sensor in sub_df.columns: target_col = sensor
                    elif short_name in sub_df.columns: target_col = short_name

                    if target_col and x_col in sub_df.columns:
                        fig.add_trace(go.Scattergl(
                            x=sub_df[x_col],
                            y=sub_df[target_col],
                            mode='lines',
                            name=sensor if row == 1 else f"{sensor} (Aligné)",
                            line=dict(line_kwargs),
                            opacity=trace_opacity,
                            showlegend=(row == 1) # Affiche la légende 1 seule fois
                        ), row=row, col=1)

            # CAS B : DataFrame classique
            else:
                short_name = sensor.split('/')[-1]
                if sensor in df_plot.columns: target_col = sensor
                elif short_name in df_plot.columns: target_col = short_name

                if target_col and x_col in df_plot.columns:
                    fig.add_trace(go.Scattergl(
                        x=df_plot[x_col],
                        y=df_plot[target_col],
                        mode='lines',
                        name=sensor if row == 1 else f"{sensor} (Aligné)",
                        line=dict(line_kwargs),
                        opacity=trace_opacity,
                        showlegend=(row == 1)
                    ), row=row, col=1)

    # 4. Layout
    fig.update_layout(
        title=f"Visualization : {filename} (Algo: {method})",
        template="plotly_white",
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.1, xanchor="right", x=1),
        hovermode="x unified",
        uirevision='constant',
    )
    
    # Titres des axes Y et X
    fig.update_yaxes(title_text=f"Value : {unit}", row=1, col=1)
    fig.update_yaxes(title_text=f"Value : {unit}", row=2, col=1)
    fig.update_xaxes(title_text=x_title, row=2, col=1) 

    return fig