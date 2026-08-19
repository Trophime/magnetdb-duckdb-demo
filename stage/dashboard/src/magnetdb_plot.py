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
    e.g. file_viewer.py passes a composite "file - group" string for the plot title.
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

    # 1. Récupération dynamique du symbole et de l'unité
    ylabel = "Value"
    if mrun and len(y_cols) > 0:
        sensor = y_cols[0]
        symbol, unit_str = None, None
        try:
            symbol, unit_str = mrun.getUnit(sensor)
        except RuntimeError:
            try:
                symbol, unit_str = mrun.getUnit(f"{group_name}/{sensor}")
            except RuntimeError:
                logger.debug(
                    "No unit found for sensor %r (group %r) in either Pupitre or PigBrother key format",
                    sensor, group_name,
                )

        if symbol and unit_str is not None:
            ylabel = f"{symbol} [{unit_str:~P}]"
        elif symbol:
            ylabel = symbol

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
        yaxis=dict(title=ylabel),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        uirevision='constant',
    )

    return fig


def create_comparison_plot(files_data: list, x_col: str, method: str, t0_absolu=None) -> go.Figure:
    """
    Creates a single figure with 2 subplots (Before / After alignment).
    files_data contains a list of dicts :
    [{'file': name, 'df': df, 'is_pupitre': bool, 'sensors': [...], 'lag': float, 'mrun': obj, 'group_name': str}, ...]
    """
    if not files_data:
        return go.Figure()

    # 1. TRI CHRONOLOGIQUE
    files_data = sorted(
        files_data, 
        key=lambda item: item['df']['timestamp'].min() if item['df'] is not None and not item['df'].empty and 'timestamp' in item['df'].columns else item['file']
    )

    # 2. IDENTIFICATION DU T0 GLOBAL (Uniquement pour tracer l'axe 't' de base continu)
    global_t0 = None
    for item in files_data:
        df_temp = item.get('df')
        if df_temp is not None and not df_temp.empty and 'timestamp' in df_temp.columns:
            min_ts = df_temp['timestamp'].min()
            if global_t0 is None or min_ts < global_t0:
                global_t0 = min_ts

    # 3. RÉCUPÉRATION DE L'UNITÉ Y
    ylabel = "Value"
    for item in files_data:
        mrun_obj = item.get('mrun')
        sensors_list = item.get('sensors', [])
        group_name = item.get('group_name', "")
        
        if mrun_obj and sensors_list:
            sensor = sensors_list[0]
            symbol, unit_str = None, None
            try:
                symbol, unit_str = mrun_obj.getUnit(sensor)
            except RuntimeError:
                try:
                    if group_name:
                        symbol, unit_str = mrun_obj.getUnit(f"{group_name}/{sensor}")
                except RuntimeError:
                    pass
            
            if symbol and unit_str is not None:
                ylabel = f"{symbol} [{unit_str:~P}]"
                break
            elif symbol:
                ylabel = symbol
                break

    # 4. CRÉATION DES SUBPLOTS
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        shared_yaxes='all',
        vertical_spacing=0.1,
        subplot_titles=("Raw Signals (Before alignment)", "Synchronized Signals (After alignment)")
    )

    downsample_method = 'none' if (not method or method in ['raw data', 'raw', 'none']) else method
    event_counters = {'default': 0, 'spike': 0, 'trigger': 0}

    # 5. BOUCLE SUR CHAQUE FICHIER
    for item in files_data:
        file = item['file']
        df_raw = item['df']
        sensors = item['sensors']
        lag_val = item['lag']
        style = _resolve_file_style(file)
        line_kwargs = dict(width=style.width, color=style.color, dash=style.dash) if style else dict(width=2)
        trace_opacity = style.opacity if style else 1.0

        if df_raw is None or df_raw.empty or not sensors:
            continue

        # --- Classification Événements ---
        file_type = classify_pigbrother_file(file)
        is_event = file_type in ['default', 'spike', 'trigger']
        
        event_label = ""
        if is_event:
            event_counters[file_type] += 1
            event_label = f"#{file_type}{event_counters[file_type]}"

        # --- Downsampling ---
        if is_event or downsample_method == 'none':
            df_plot = df_raw.copy()
        else:
            try:
                config = DownsampleConfig(n_out=_DEFAULT_N_OUT, method=_METHOD_MAP.get(downsample_method, 'stride'))
                df_plot = downsample_dataframe(df_raw, time_col=x_col, value_cols=list(sensors), config=config)
            except Exception as e:
                df_plot = df_raw.copy()

        # --- Tracé sur les 2 Lignes ---
        for row in [1, 2]:
            for sensor in sensors:
                target_col = None
                sub_df = df_plot[sensor] if (isinstance(df_plot, dict) and sensor in df_plot) else df_plot
                short_name = sensor.split('/')[-1]
                
                if sensor in sub_df.columns: 
                    target_col = sensor
                elif short_name in sub_df.columns: 
                    target_col = short_name

                if target_col and x_col in sub_df.columns:
                    
                    # =================================================================
                    # LA CORRECTION DÉFINITIVE MATHÉMATIQUE
                    # =================================================================
                    file_t0 = sub_df['timestamp'].min() if 'timestamp' in sub_df.columns else None
                    
                    # Calcul de la "Vraie Dérive" des horloges matérielles
                    if is_event:
                        true_drift = 0.0  # Les événements sont absolus, pas de correction
                    else:
                        true_drift = lag_val

                    if row == 1:
                        # LIGNE 1 : RAW (La réalité physique inaltérée)
                        if x_col == 'timestamp':
                            x_data = sub_df['timestamp'].copy()
                        elif x_col == 't' and global_t0 is not None and 'timestamp' in sub_df.columns:
                            x_data = (sub_df['timestamp'] - global_t0).dt.total_seconds()
                        else:
                            x_data = sub_df[x_col].copy()
                    
                    elif row == 2:
                        # LIGNE 2 : ALIGNED (Décalage local appliqué)
                        if x_col == 'timestamp':
                            x_data = sub_df['timestamp'] + pd.to_timedelta(true_drift, unit='s')
                        elif x_col == 't' and global_t0 is not None and 'timestamp' in sub_df.columns:
                            x_data = (sub_df['timestamp'] - global_t0).dt.total_seconds() + true_drift
                        else:
                            # Fallback (temps relatif simple qui commence à 0)
                            t_base = sub_df['t'] if 't' in sub_df.columns else sub_df.index
                            x_data = t_base + true_drift
                    # =================================================================

                    # TRACER UN ÉVÉNEMENT
                    if is_event:
                        max_idx = sub_df[target_col].abs().values.argmax()
                        x_point = x_data.iloc[max_idx]
                        y_point = sub_df[target_col].iloc[max_idx]

                        fig.add_trace(go.Scatter(
                            x=[x_point], 
                            y=[y_point], 
                            mode='markers+text',
                            text=[event_label],
                            textposition="top center",
                            textfont=dict(color=style.color if style else "red", size=11, family="Arial Black"),
                            marker=dict(
                                size=14, 
                                symbol='x' if file_type == 'default' else 'star',
                                color=style.color if style else "red",
                                line=dict(width=2, color='DarkSlateGrey')
                            ),
                            name=f"{file} - {sensor}" if row == 1 else f"{file} - {sensor} (Aligned)",
                            legendgroup=file,
                            showlegend=(row == 1)
                        ), row=row, col=1)

                    # TRACER UNE COURBE NORMALE
                    else:
                        fig.add_trace(go.Scatter(
                            x=x_data, 
                            y=sub_df[target_col], 
                            mode='lines',
                            name=f"{file} - {sensor}" if row == 1 else f"{file} - {sensor} (Aligned)",
                            legendgroup=file,
                            line=line_kwargs, 
                            opacity=trace_opacity, 
                            showlegend=(row == 1)
                        ), row=row, col=1)

    # 6. GLOBAL LAYOUT AND STYLING
    x_label_mapping = {'t': 't(s)', 'timestamp': 'Date / Time'}
    fig.update_layout(
        template="plotly_white",
        margin=dict(t=50, b=20, l=40, r=20),
        hovermode="x unified",
        uirevision='constant',
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1)
    )
    
    fig.update_xaxes(title_text=x_label_mapping.get(x_col, x_col), row=2, col=1)
    fig.update_yaxes(title_text=ylabel)
    
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        showline=True,
        spikedash="solid",
        spikecolor="#FF0000",
        spikethickness=1
    )

    return fig


def create_annotated_plot(files_data: list, x_col: str, method: str, group_name: str = "") -> go.Figure:
    """Single-subplot overlay of several files' data for one group.

    Regular/pupitre/overview/archive files are drawn as line traces;
    default/spike/trigger event files are drawn as a single marker+text
    annotation at their peak absolute value instead of a line — same
    classification (:func:`~python_magnetrun.utils.files.classify_pigbrother_file`)
    and styling (`FILE_TYPE_STYLES`) as :func:`create_comparison_plot`, but
    without its lag/sync correction and two-row raw/aligned layout: this is
    a single shared-axis overlay for files that are already time-aligned to
    a common wall-clock axis (``x_col="timestamp"``), as used by the
    overview-records file-viewer page.

    Parameters
    ----------
    files_data : list of dict
        One dict per file: ``{'file': str, 'df': pandas.DataFrame, 'sensors':
        list[str], 'mrun': MagnetRun or None}``.
    x_col : str
        Column to use for the x-axis (``"timestamp"`` or ``"t"``).
    method : str
        Downsampling method name, or ``"raw data"``/``"none"`` to disable.
        Event files are never downsampled, regardless of this value.
    group_name : str, optional
        Used as the figure title.

    Returns
    -------
    :class:`~plotly.graph_objects.Figure`
        One line trace per non-event file/sensor, one marker+text trace per
        event file/sensor. Empty figure if *files_data* is empty.
    """
    if not files_data:
        return go.Figure()

    ylabel = "Value"
    for item in files_data:
        mrun_obj = item.get('mrun')
        sensors_list = item.get('sensors', [])
        if mrun_obj and sensors_list:
            sensor = sensors_list[0]
            symbol, unit_str = None, None
            try:
                symbol, unit_str = mrun_obj.getUnit(sensor)
            except RuntimeError:
                try:
                    if group_name:
                        symbol, unit_str = mrun_obj.getUnit(f"{group_name}/{sensor}")
                except RuntimeError:
                    pass

            if symbol and unit_str is not None:
                ylabel = f"{symbol} [{unit_str:~P}]"
                break
            elif symbol:
                ylabel = symbol
                break

    fig = go.Figure()
    downsample_method = 'none' if (not method or method in ['raw data', 'raw', 'none']) else method
    event_counters = {'default': 0, 'spike': 0, 'trigger': 0}

    for item in files_data:
        file = item['file']
        df_raw = item.get('df')
        sensors = item.get('sensors') or []

        if df_raw is None or df_raw.empty or not sensors:
            continue

        style = _resolve_file_style(file)
        line_kwargs = dict(width=style.width, color=style.color, dash=style.dash) if style else dict(width=2)
        trace_opacity = style.opacity if style else 1.0

        file_type = classify_pigbrother_file(file)
        is_event = file_type in ('default', 'spike', 'trigger')

        event_label = ""
        if is_event:
            event_counters[file_type] += 1
            event_label = f"#{file_type}{event_counters[file_type]}"

        if is_event or downsample_method == 'none':
            df_plot = df_raw.copy()
        else:
            try:
                config = DownsampleConfig(n_out=_DEFAULT_N_OUT, method=_METHOD_MAP.get(downsample_method, 'stride'))
                df_plot = downsample_dataframe(df_raw, time_col=x_col, value_cols=list(sensors), config=config)
            except Exception:
                df_plot = df_raw.copy()

        for sensor in sensors:
            target_col = None
            sub_df = df_plot[sensor] if (isinstance(df_plot, dict) and sensor in df_plot) else df_plot
            short_name = sensor.split('/')[-1]

            if sensor in sub_df.columns:
                target_col = sensor
            elif short_name in sub_df.columns:
                target_col = short_name

            if not (target_col and x_col in sub_df.columns):
                continue

            x_data = sub_df[x_col]

            if is_event:
                max_idx = sub_df[target_col].abs().values.argmax()
                fig.add_trace(go.Scatter(
                    x=[x_data.iloc[max_idx]],
                    y=[sub_df[target_col].iloc[max_idx]],
                    mode='markers+text',
                    text=[event_label],
                    textposition="top center",
                    textfont=dict(color=style.color if style else "red", size=11, family="Arial Black"),
                    marker=dict(
                        size=14,
                        symbol='x' if file_type == 'default' else 'star',
                        color=style.color if style else "red",
                        line=dict(width=2, color='DarkSlateGrey'),
                    ),
                    name=f"{file} - {sensor}",
                    legendgroup=file,
                ))
            else:
                fig.add_trace(go.Scatter(
                    x=x_data,
                    y=sub_df[target_col],
                    mode='lines',
                    name=f"{file} - {sensor}",
                    legendgroup=file,
                    line=line_kwargs,
                    opacity=trace_opacity,
                ))

    x_label_mapping = {'t': 't(s)', 'timestamp': 'Date / Time'}
    fig.update_layout(
        title=group_name,
        template="plotly_white",
        margin=dict(l=40, r=40, t=60, b=40),
        xaxis=dict(title=x_label_mapping.get(x_col, x_col)),
        yaxis=dict(title=ylabel),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        uirevision='constant',
    )

    return fig