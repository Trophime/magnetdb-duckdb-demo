import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
import numpy as np
import pint
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

# Forces every field in a group onto one display/plot unit, so fields that are
# recorded in different (but dimensionally compatible) native units - e.g.
# "debitbrut" in m3/h vs. "FlowH"/"FlowB" in l/s, both in "Hydraulics" - don't
# show up side by side in mismatched units. Sensors whose native unit isn't
# dimensionally compatible with the override (e.g. a group mixing var and W)
# are left in their own unit rather than converted; see group_display_unit().
GROUP_UNIT_OVERRIDES: dict[str, str] = {
    "Hydraulics": "liter / second",
}


def resolve_sensor_unit(mrun, sensor: str, group_name: str = ""):
    """Return the (symbol, pint.Unit) for *sensor*, trying the plain and 'Group/Sensor' keys.

    Parameters
    ----------
    mrun : MagnetRun
        Loaded run object to query for units.
    sensor : str
        Sensor/column name.
    group_name : str, optional
        Group name, used to retry as ``f"{group_name}/{sensor}"`` (TDMS-style
        keys) if the plain name isn't recognised.

    Returns
    -------
    tuple
        ``(symbol, unit)``, or ``(None, None)`` if neither key resolves.
    """
    for key in (sensor, f"{group_name}/{sensor}"):
        try:
            result = mrun.getUnit(key)
        except RuntimeError:
            continue
        # Some MagnetData.getUnitKey() backends return () (not a RuntimeError)
        # for a TDMS channel name that matches no known keyword.
        if isinstance(result, tuple) and len(result) == 2:
            return result
    return None, None


def group_display_unit(mrun, group_name: str, sensor: str):
    """Return the (symbol, pint.Unit) to display for *sensor*, honoring :data:`GROUP_UNIT_OVERRIDES`.

    Parameters
    ----------
    mrun : MagnetRun
        Loaded run object to query for units.
    group_name : str
        Group *sensor* belongs to.
    sensor : str
        Sensor/column name.

    Returns
    -------
    tuple
        ``(symbol, unit)``. If ``group_name`` has an override and *sensor*'s
        own unit is dimensionally compatible with it, ``unit`` is the
        overridden unit; otherwise it's the sensor's own native unit
        (or ``(None, None)`` if unresolvable).
    """
    symbol, unit = resolve_sensor_unit(mrun, sensor, group_name)
    if unit is None:
        return symbol, unit
    target = GROUP_UNIT_OVERRIDES.get(group_name)
    if target is not None:
        try:
            unit = (1 * unit).to(target).units
        except pint.errors.DimensionalityError:
            pass
    return symbol, unit


def convert_values_to_unit(values, unit, target_unit):
    """Convert a numeric array from *unit* to *target_unit*.

    Parameters
    ----------
    values : :class:`~numpy.ndarray` or :class:`~pandas.Series`
        Values expressed in *unit*.
    unit : pint.Unit or None
        *values*' current unit.
    target_unit : pint.Unit or None
        Unit to convert to.

    Returns
    -------
    :class:`~numpy.ndarray` or :class:`~pandas.Series`
        Converted values, or *values* unchanged if either unit is ``None``,
        they're already equal, or they're not dimensionally compatible.
    """
    if unit is None or target_unit is None or unit == target_unit:
        return values
    try:
        # Coerce to a plain ndarray first: multiplying a pandas Series by a
        # pint.Unit silently strips the unit (UnitStrippedWarning) instead of
        # producing a Quantity, so .to() would fail below.
        return (np.asarray(values) * unit).to(target_unit).magnitude
    except pint.errors.DimensionalityError:
        return values


def format_sensor_label(base_label: str, symbol: str | None, unit) -> str:
    """Append a "(symbol [unit])" suffix to *base_label* when resolvable.

    Parameters
    ----------
    base_label : str
        Sensor name or other label text to annotate.
    symbol : str or None
        Physical-quantity symbol (e.g. ``"Q"``), or ``None`` if unresolved.
    unit : pint.Unit or None
        Unit to display, or ``None`` if unresolved.

    Returns
    -------
    str
        ``"{base_label} ({symbol} [{unit:~P}])"``, ``"{base_label} ({symbol})"``
        if only *symbol* is known, or *base_label* unchanged if neither is.
    """
    if symbol and unit is not None:
        return f"{base_label} ({symbol} [{unit:~P}])"
    elif symbol:
        return f"{base_label} ({symbol})"
    return base_label


@dataclass
class TraceStyle:
    """Plotly line style for one data-file type (matplotlib-like: color/dash/width/alpha)."""

    color: str = "#1f77b4"
    dash: str = "solid"
    width: float = 2
    opacity: float = 1.0
    marker_symbol: str | None = None
    marker_every: int | None = None


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


@dataclass
class FieldStyleOverride:
    """Optional per-(group, sensor) override of color/dash/width/marker properties.

    Any property left as ``None`` falls back to the resolved source-type
    :class:`TraceStyle`. Opacity is deliberately not included — it stays a
    pure per-source-type property, not overridable per field.
    """

    color: str | None = None
    dash: str | None = None
    width: float | None = None
    marker_symbol: str | None = None
    marker_every: int | None = None

    def to_dict(self) -> dict:
        """Return only the properties actually set (skips ``None`` values)."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "FieldStyleOverride":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class StyleConfig:
    """Top-level style config: per-source-type styles plus per-(group, field) overrides."""

    file_type_styles: FileTypeStyles = field(default_factory=FileTypeStyles)
    field_overrides: dict[str, dict[str, FieldStyleOverride]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = self.file_type_styles.to_dict()
        data["field_overrides"] = {
            group_name: {
                sensor: override.to_dict() for sensor, override in sensors.items()
            }
            for group_name, sensors in self.field_overrides.items()
        }
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "StyleConfig":
        field_overrides = {
            group_name: {
                sensor: FieldStyleOverride.from_dict(override)
                for sensor, override in sensors.items()
            }
            for group_name, sensors in data.get("field_overrides", {}).items()
        }
        return cls(file_type_styles=FileTypeStyles.from_dict(data), field_overrides=field_overrides)


def load_style_config(path: str | Path) -> StyleConfig:
    """Load a :class:`StyleConfig` (source-type styles + field overrides) from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return StyleConfig.from_dict(data)


def save_style_config(config: StyleConfig, path: str | Path) -> None:
    """Save a :class:`StyleConfig` (source-type styles + field overrides) to a JSON file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config.to_dict(), f, indent=2)


USER_STYLE_CONFIG_PATH = Path.home() / ".config" / "magnetdb" / "style.json"
_BUNDLED_STYLE_PATH = Path(__file__).parent / "style.json"


def _load_default_style_config() -> StyleConfig:
    """Return StyleConfig, resolved in order: env var, user config dir, bundled default.

    1. ``$MAGNETDB_FILE_TYPE_STYLES``, if set.
    2. ``~/.config/magnetdb/style.json``, if it exists.
    3. The bundled ``style.json`` shipped next to this module.
    4. In-code :class:`StyleConfig` defaults, as a last resort if even the
       bundled file is somehow missing or unreadable — startup never crashes.
    """
    env_path = os.environ.get("MAGNETDB_FILE_TYPE_STYLES")
    if env_path:
        try:
            return load_style_config(env_path)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not load $MAGNETDB_FILE_TYPE_STYLES=%s: %s — trying next source", env_path, exc
            )

    if USER_STYLE_CONFIG_PATH.exists():
        try:
            return load_style_config(USER_STYLE_CONFIG_PATH)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not load %s: %s — trying next source", USER_STYLE_CONFIG_PATH, exc
            )

    try:
        return load_style_config(_BUNDLED_STYLE_PATH)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "Could not load bundled %s: %s — using in-code defaults", _BUNDLED_STYLE_PATH, exc
        )
    return StyleConfig()


_STYLE_CONFIG = _load_default_style_config()
FILE_TYPE_STYLES = _STYLE_CONFIG.file_type_styles
FIELD_STYLE_OVERRIDES = _STYLE_CONFIG.field_overrides


def reload_style_config() -> None:
    """Re-resolve the style config from disk and refresh the module-level globals.

    Called by the style-editor modal's Save action so the running app picks up
    changes immediately, without a restart.
    """
    global _STYLE_CONFIG, FILE_TYPE_STYLES, FIELD_STYLE_OVERRIDES
    _STYLE_CONFIG = _load_default_style_config()
    FILE_TYPE_STYLES = _STYLE_CONFIG.file_type_styles
    FIELD_STYLE_OVERRIDES = _STYLE_CONFIG.field_overrides


def resolve_file_type_key(filename: str) -> str | None:
    """Return the FILE_TYPE_STYLES key for *filename* ('pupitre' or a pigbrother mode).

    Parameters
    ----------
    filename : str
        Source data filename.

    Returns
    -------
    str or None
        ``'pupitre'`` for a ``.txt`` file, the normalized
        :func:`~python_magnetrun.utils.files.classify_pigbrother_file` mode
        for a ``.tdms`` file, or ``None`` if unresolved.
    """
    if filename.endswith('.txt'):
        return 'pupitre'
    return classify_pigbrother_file(filename)


def _resolve_file_style(filename: str) -> TraceStyle | None:
    """Return the FILE_TYPE_STYLES entry for *filename*, or None if unresolved.

    None (rather than a fallback style) lets callers keep Plotly's default
    per-trace color cycling for filenames that don't map to a known type,
    e.g. an unrecognised extension or a synthetic/composite name.
    """
    return FILE_TYPE_STYLES.get(resolve_file_type_key(filename))


def _resolve_field_override(group_name: str, sensor: str) -> FieldStyleOverride | None:
    """Return the FIELD_STYLE_OVERRIDES entry for (*group_name*, *sensor*), or None if unset."""
    return FIELD_STYLE_OVERRIDES.get(group_name, {}).get(sensor)


def _apply_style(
    style: TraceStyle | None,
    override: FieldStyleOverride | None,
    n_points: int,
) -> dict:
    """Merge a base source-type style with an optional field override into trace kwargs.

    Parameters
    ----------
    style : TraceStyle, optional
        Base per-source-type style, or ``None`` if the source file type is
        unresolved (falls back to Plotly's default color cycling, as today).
    override : FieldStyleOverride, optional
        Per-(group, sensor) override; properties left ``None`` fall back to
        *style*. Opacity is never taken from *override* — see
        :class:`FieldStyleOverride`.
    n_points : int
        Number of points in the trace, used to size the ``marker_every`` mask.

    Returns
    -------
    dict
        ``mode``, ``line``, ``opacity``, and (only when markers are enabled)
        ``marker`` — ready to splat into a
        :class:`~plotly.graph_objects.Scatter`/``Scattergl`` call.
    """
    color = (override.color if override else None) or (style.color if style else None)
    dash = (override.dash if override else None) or (style.dash if style else None)
    width = (override.width if override and override.width is not None else None)
    if width is None:
        width = style.width if style else 2
    marker_symbol = (override.marker_symbol if override else None) or (
        style.marker_symbol if style else None
    )
    marker_every = (override.marker_every if override else None) or (
        style.marker_every if style else None
    )
    opacity = style.opacity if style else 1.0

    line_kwargs = dict(width=width)
    if color is not None:
        line_kwargs["color"] = color
    if dash is not None:
        line_kwargs["dash"] = dash

    kwargs = dict(mode="lines", line=line_kwargs, opacity=opacity)

    if marker_symbol:
        kwargs["mode"] = "lines+markers"
        if marker_every and marker_every > 1 and n_points > 0:
            kwargs["marker"] = dict(
                symbol=marker_symbol,
                size=[8 if i % marker_every == 0 else 0 for i in range(n_points)],
            )
        else:
            kwargs["marker"] = dict(symbol=marker_symbol)

    return kwargs

def create_plot(df, x_col: str, y_cols: list, method: str, filename: str = "", mrun=None, group_name: str = "") -> go.Figure:
    """
    Gère le sous-échantillonnage et génère la figure Plotly pour Pupitre ET PigBrother.
    """
    if df is None or df.empty:
        return go.Figure()

    # 1. Récupération dynamique du symbole et de l'unité (forcée sur tout le
    #    groupe pour les groupes listés dans GROUP_UNIT_OVERRIDES)
    ylabel = "Value"
    target_unit = None
    if mrun and len(y_cols) > 0:
        sensor = y_cols[0]
        symbol, target_unit = group_display_unit(mrun, group_name, sensor)
        if target_unit is None:
            logger.debug(
                "No unit found for sensor %r (group %r) in either Pupitre or PigBrother key format",
                sensor, group_name,
            )

        if symbol and target_unit is not None:
            ylabel = f"{symbol} [{target_unit:~P}]"
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

    # 3. Traitement robuste des colonnes (Gère 'Groupe/Capteur' ET 'Capteur')
    for sensor in y_cols:
        target_col = None
        override = _resolve_field_override(group_name, sensor)

        # Convertit les valeurs de ce capteur vers l'unité de l'axe (target_unit)
        # si le groupe force une unité commune (GROUP_UNIT_OVERRIDES).
        sensor_unit = None
        if mrun and target_unit is not None:
            _, sensor_unit = resolve_sensor_unit(mrun, sensor, group_name)

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
                    y_values = convert_values_to_unit(sub_df[target_col], sensor_unit, target_unit)
                    fig.add_trace(go.Scattergl(
                        x=sub_df[x_col],
                        y=y_values,
                        name=sensor,
                        **_apply_style(style, override, len(y_values)),
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
                y_values = convert_values_to_unit(df_plot[target_col], sensor_unit, target_unit)
                fig.add_trace(go.Scattergl(
                    x=df_plot[x_col],
                    y=y_values,
                    name=sensor,
                    **_apply_style(style, override, len(y_values)),
                ))

    # 4. Layout
    title = f"Visualization : {filename}"
    if group_name:
        title += f" - {group_name}"
    title += f" (Algo: {method})"
    fig.update_layout(
        title=title,
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
        group_name = item.get('group_name', "")
        style = _resolve_file_style(file)

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
                        override = _resolve_field_override(group_name, sensor)
                        fig.add_trace(go.Scatter(
                            x=x_data,
                            y=sub_df[target_col],
                            name=f"{file} - {sensor}" if row == 1 else f"{file} - {sensor} (Aligned)",
                            legendgroup=file,
                            showlegend=(row == 1),
                            **_apply_style(style, override, len(x_data)),
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
    target_unit = None
    for item in files_data:
        mrun_obj = item.get('mrun')
        sensors_list = item.get('sensors', [])
        if mrun_obj and sensors_list:
            symbol, target_unit = group_display_unit(mrun_obj, group_name, sensors_list[0])

            if symbol and target_unit is not None:
                ylabel = f"{symbol} [{target_unit:~P}]"
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
        mrun_obj = item.get('mrun')

        if df_raw is None or df_raw.empty or not sensors:
            continue

        style = _resolve_file_style(file)

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

            sensor_unit = None
            if mrun_obj and target_unit is not None:
                _, sensor_unit = resolve_sensor_unit(mrun_obj, sensor, group_name)
            y_data = np.asarray(convert_values_to_unit(sub_df[target_col], sensor_unit, target_unit))

            if is_event:
                max_idx = np.abs(y_data).argmax()
                event_x = x_data.iloc[max_idx]
                event_y = y_data[max_idx]
                event_color = style.color if style else "red"
                fig.add_trace(go.Scatter(
                    x=[event_x],
                    y=[event_y],
                    mode='markers',
                    marker=dict(
                        size=14,
                        symbol='x' if file_type == 'default' else 'star',
                        color=event_color,
                        line=dict(width=2, color='DarkSlateGrey'),
                    ),
                    name=f"{file} - {sensor}",
                    showlegend=False,
                    hovertext=f"{event_label}<br>{file}<br>{sensor}: {event_y:.3g}",
                    hovertemplate="%{hovertext}<extra></extra>",
                ))
                fig.add_annotation(
                    x=event_x,
                    y=event_y,
                    text=event_label,
                    showarrow=True,
                    arrowhead=2,
                    arrowcolor=event_color,
                    ax=20,
                    ay=-30,
                    bgcolor="white",
                    bordercolor=event_color,
                    borderwidth=1,
                    font=dict(color=event_color, size=11, family="Arial Black"),
                )
            else:
                override = _resolve_field_override(group_name, sensor)
                fig.add_trace(go.Scatter(
                    x=x_data,
                    y=y_data,
                    name=f"{file} - {sensor}",
                    legendgroup=file,
                    **_apply_style(style, override, len(y_data)),
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