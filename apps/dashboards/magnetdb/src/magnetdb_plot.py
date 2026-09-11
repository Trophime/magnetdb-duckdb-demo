import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import numpy as np
import pandas as pd
import pint
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from python_magnetrun.utils.downsampling import DownsampleConfig, downsample_dataframe
from python_magnetrun.utils.files import classify_pigbrother_file
from python_magnetrun.utils.timestamps import parse_filename_timestamp
from python_magnetrun.utils.timezone import local_to_utc_naive, series_utc_to_local_naive

logger = logging.getLogger(__name__)

_METHOD_MAP = {
    'lttb': 'lttb', 'LTTB': 'lttb',
    'minmax': 'minmax',
    'm4': 'm4', 'M4': 'm4',
    'naive': 'stride', 'stride': 'stride',
}
_DEFAULT_N_OUT = 1000

# Tags create_annotated_plot's incident-overlay shapes so overview_records.py's
# cursor pin/clear callbacks can tell them apart from user-pinned cursor lines.
INCIDENT_SHAPE_NAME = "ov-incident"

# Human-readable text for the fault-subtype suffix carried by some "default"
# incident filenames (e.g. "M10_Default_260120-135125_DefautNums.tdms"),
# mirrors python_magnetrun.runlogs.pigbrother.DefautType.description. Suffixes
# not listed here (e.g. "PontAzero") are shown as their raw code with no
# description rather than guessing a translation.
_DEFAULT_TYPE_DESCRIPTIONS: dict[str, str] = {
    "DefautNums": "Défaut généré suite à un trigger matériel de l'installation (relais I_MAX)",
    "SpikeAimant": "Spike de courant anormal détecté sur capteurs aimant (internes ou externes)",
    "Courants50Hz": "Courant 50 Hz anormalement élevé (perturbation, bruit réseau, surtension)",
}

# Forces every field in a group onto one display/plot unit, so fields that are
# recorded in different (but dimensionally compatible) native units - e.g.
# "debitbrut" in m3/h vs. "FlowH"/"FlowB" in l/s, both in "Hydraulics" - don't
# show up side by side in mismatched units. Sensors whose native unit isn't
# dimensionally compatible with the override (e.g. a group mixing var and W)
# are left in their own unit rather than converted; see group_display_unit().
GROUP_UNIT_OVERRIDES: dict[str, str] = {
    "Hydraulics": "liter / second",
    "Magnetic_Field": "tesla",
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


def group_display_unit(mrun, group_name: str, sensor: str, native_group: str | None = None):
    """Return the (symbol, pint.Unit) to display for *sensor*, honoring :data:`GROUP_UNIT_OVERRIDES`.

    Parameters
    ----------
    mrun : MagnetRun
        Loaded run object to query for units.
    group_name : str
        Display block *sensor* belongs to — used to look up
        :data:`GROUP_UNIT_OVERRIDES`.
    sensor : str
        Sensor/column name.
    native_group : str, optional
        *sensor*'s own format-native group, used instead of *group_name* to
        resolve its unit when they differ (a cross-format-matched entry's
        pigbrother side lives in its own tdms group, not the display block's
        pupitre-named group — see :func:`magnetdb_analysis.get_overview_group_entries`).
        Defaults to *group_name* when not given.

    Returns
    -------
    tuple
        ``(symbol, unit)``. If ``group_name`` has an override and *sensor*'s
        own unit is dimensionally compatible with it, ``unit`` is the
        overridden unit; otherwise it's the sensor's own native unit
        (or ``(None, None)`` if unresolvable).
    """
    symbol, unit = resolve_sensor_unit(mrun, sensor, native_group if native_group is not None else group_name)
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


def field_histogram_figure(field_stats):
    """Build a small histogram figure of the Field/Champ_magn values in *field_stats*.

    Parameters
    ----------
    field_stats : dict or None
        Result of :func:`magnetdb_analysis.get_field_column_stats`. ``None``
        yields an empty placeholder figure.

    Returns
    -------
    :class:`~plotly.graph_objects.Figure`
        A single-trace histogram figure, or an empty placeholder if
        *field_stats* is ``None``.
    """
    if field_stats is None:
        fig = go.Figure()
        fig.update_layout(
            annotations=[
                {
                    "text": "No Field/Champ_magn data",
                    "xref": "paper",
                    "yref": "paper",
                    "showarrow": False,
                    "font": {"color": "#888888"},
                }
            ],
            xaxis={"visible": False},
            yaxis={"visible": False},
            template="plotly_white",
            margin={"l": 20, "r": 20, "t": 30, "b": 20},
        )
        return fig

    unit_suffix = f" [{field_stats['unit']}]" if field_stats["unit"] else ""
    fig = go.Figure(go.Histogram(x=field_stats["values"], marker={"color": "#1f77b4"}))
    fig.update_layout(
        title=f"{field_stats['column']} histogram",
        template="plotly_white",
        margin={"l": 40, "r": 20, "t": 40, "b": 40},
        xaxis={"title": f"{field_stats['column']}{unit_suffix}"},
        yaxis={"title": "Count"},
        bargap=0.02,
    )
    return fig


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

    line_kwargs = {'width': width}
    if color is not None:
        line_kwargs["color"] = color
    if dash is not None:
        line_kwargs["dash"] = dash

    kwargs = {'mode': "lines", 'line': line_kwargs, 'opacity': opacity}

    if marker_symbol:
        kwargs["mode"] = "lines+markers"
        if marker_every and marker_every > 1 and n_points > 0:
            kwargs["marker"] = {
                'symbol': marker_symbol,
                'size': [8 if i % marker_every == 0 else 0 for i in range(n_points)],
            }
        else:
            kwargs["marker"] = {'symbol': marker_symbol}

    return kwargs


def _display_x_series(df, x_col: str):
    """Return df[x_col], converted from naive UTC to Europe/Paris local time for display.

    The "timestamp" column is stored as naive UTC (see
    :mod:`python_magnetrun.utils.timezone`); "t" (elapsed seconds) needs no
    conversion.
    """
    return series_utc_to_local_naive(df[x_col]) if x_col == "timestamp" else df[x_col]


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

    x_label_mapping = {'t': 't(s)', 'timestamp': 'Date / Time (local)'}
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
                        x=_display_x_series(sub_df, x_col),
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
                    x=_display_x_series(df_plot, x_col),
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
        margin={'l': 40, 'r': 40, 't': 60, 'b': 40},
        xaxis={'title': x_title},
        yaxis={'title': ylabel},
        showlegend=True,
        legend={'orientation': "h", 'yanchor': "bottom", 'y': 1.02, 'xanchor': "right", 'x': 1},
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
            except Exception:
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
                            textfont={'color': style.color if style else "red", 'size': 11, 'family': "Arial Black"},
                            marker={
                                'size': 14, 
                                'symbol': 'x' if file_type == 'default' else 'star',
                                'color': style.color if style else "red",
                                'line': {'width': 2, 'color': 'DarkSlateGrey'}
                            },
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
        margin={'t': 50, 'b': 20, 'l': 40, 'r': 20},
        hovermode="x unified",
        uirevision='constant',
        legend={'orientation': "h", 'yanchor': "bottom", 'y': 1.05, 'xanchor': "right", 'x': 1}
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


def _add_incident_overlays(fig: go.Figure, event_files: list, x_col: str, record_t0_utc) -> None:
    """Add one dashed full-height overlay line per incident file to *fig*, in place.

    Positions come from the filename alone (never from loading the incident
    file's data): :func:`~python_magnetrun.utils.timestamps.parse_filename_timestamp`
    for the local timestamp. In ``"timestamp"`` mode that local value is used
    directly, matching the regular files' ``timestamp`` column (naive UTC,
    converted to local for display — see :func:`_display_x_series`). In
    ``"t"`` mode it's converted to naive UTC via
    :func:`~python_magnetrun.utils.timezone.local_to_utc_naive` to subtract
    against *record_t0_utc*, which is also naive UTC.

    Parameters
    ----------
    fig : :class:`~plotly.graph_objects.Figure`
        Figure to annotate, mutated in place.
    event_files : list of str
        Incident (default/spike) filenames.
    x_col : str
        ``"timestamp"`` or ``"t"``. In ``"t"`` mode, a line is only added
        when *record_t0_utc* is available; unresolvable files are skipped
        silently (the caller is responsible for surfacing one warning).
    record_t0_utc : :class:`~pandas.Timestamp` or None
        Naive-UTC ``t=0`` reference, required only for ``x_col="t"``.
    """
    event_counters: dict[str, int] = {}
    for file in event_files:
        file_type = classify_pigbrother_file(file)
        if file_type not in ("default", "spike", "trigger"):
            continue

        dt_local = parse_filename_timestamp(file)
        if dt_local is None:
            continue
        dt_utc = pd.Timestamp(local_to_utc_naive(dt_local, "Europe/Paris"))

        if x_col == "timestamp":
            event_x = pd.Timestamp(dt_local).isoformat()
        elif x_col == "t" and record_t0_utc is not None:
            event_x = (dt_utc - pd.Timestamp(record_t0_utc)).total_seconds()
        else:
            continue

        event_counters[file_type] = event_counters.get(file_type, 0) + 1
        label = f"{file_type.capitalize()} #{event_counters[file_type]}"
        hover = label

        if file_type == "default":
            name_parts = os.path.splitext(os.path.basename(file))[0].split("_")
            subtype = name_parts[3] if len(name_parts) > 3 and name_parts[3] else None
            if subtype:
                label += f" — {subtype}"
                description = _DEFAULT_TYPE_DESCRIPTIONS.get(subtype)
                if description:
                    hover = f"{label}<br>{description}"
                else:
                    hover = label

        style = _resolve_file_style(file)
        color = style.color if style else "red"

        fig.add_shape(
            type="line", x0=event_x, x1=event_x, y0=0, y1=1,
            xref="x", yref="paper", name=INCIDENT_SHAPE_NAME,
            line={"color": color, "width": 1.5, "dash": "dash"},
        )
        fig.add_annotation(
            x=event_x, y=1, yref="paper", yanchor="bottom",
            text=label, showarrow=False,
            hovertext=hover, captureevents=True,
            font={"color": color, "size": 10},
        )


def create_annotated_plot(
    files_data: list,
    x_col: str,
    method: str,
    group_name: str = "",
    event_files: list | None = None,
    record_t0_utc=None,
) -> go.Figure:
    """Single-subplot overlay of several files' data for one group.

    Regular/pupitre/overview/archive files are drawn as line traces. Incident
    (default/spike) files are never loaded — they're drawn as dashed
    full-height overlay lines positioned from their filename alone, via
    *event_files* (see :func:`_add_incident_overlays`).

    Parameters
    ----------
    files_data : list of dict
        One dict per regular file: ``{'file': str, 'df': pandas.DataFrame,
        'sensors': list[str], 'mrun': MagnetRun or None}``.
    x_col : str
        Column to use for the x-axis (``"timestamp"`` or ``"t"``).
    method : str
        Downsampling method name, or ``"raw data"``/``"none"`` to disable.
    group_name : str, optional
        Used as the figure title.
    event_files : list of str, optional
        Incident (default/spike) filenames to draw as overlay lines. Ignored
        in ``x_col="t"`` mode when *record_t0_utc* is ``None``.
    record_t0_utc : :class:`~pandas.Timestamp`, optional
        Naive-UTC ``t=0`` reference for placing *event_files* when
        ``x_col="t"``; unused for ``x_col="timestamp"``.

    Returns
    -------
    :class:`~plotly.graph_objects.Figure`
        One line trace per regular file/sensor, plus one overlay line per
        incident file. Empty figure if both *files_data* and *event_files*
        are empty.
    """
    if not files_data and not event_files:
        return go.Figure()

    ylabel = "Value"
    target_unit = None
    for item in files_data:
        mrun_obj = item.get('mrun')
        sensors_list = item.get('sensors', [])
        if mrun_obj and sensors_list:
            symbol, target_unit = group_display_unit(
                mrun_obj, group_name, sensors_list[0], native_group=item.get('native_group')
            )

            if symbol and target_unit is not None:
                ylabel = f"{symbol} [{target_unit:~P}]"
                break
            elif symbol:
                ylabel = symbol
                break

    fig = go.Figure()
    downsample_method = 'none' if (not method or method in ['raw data', 'raw', 'none']) else method

    for item in files_data:
        file = item['file']
        df_raw = item.get('df')
        sensors = item.get('sensors') or []
        mrun_obj = item.get('mrun')

        if df_raw is None or df_raw.empty or not sensors:
            continue

        style = _resolve_file_style(file)

        if downsample_method == 'none':
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

            x_data = _display_x_series(sub_df, x_col)

            sensor_unit = None
            if mrun_obj and target_unit is not None:
                _, sensor_unit = resolve_sensor_unit(mrun_obj, sensor, item.get('native_group', group_name))
            y_data = np.asarray(convert_values_to_unit(sub_df[target_col], sensor_unit, target_unit))

            override = _resolve_field_override(group_name, sensor)
            fig.add_trace(go.Scatter(
                x=x_data,
                y=y_data,
                name=f"{file} - {sensor}",
                legendgroup=file,
                **_apply_style(style, override, len(y_data)),
            ))

    if event_files:
        _add_incident_overlays(fig, event_files, x_col, record_t0_utc)

    x_label_mapping = {'t': 't(s)', 'timestamp': 'Date / Time (local)'}
    fig.update_layout(
        title=group_name,
        template="plotly_white",
        margin={'l': 40, 'r': 40, 't': 60, 'b': 40},
        xaxis={'title': x_label_mapping.get(x_col, x_col)},
        yaxis={'title': ylabel},
        showlegend=True,
        legend={'orientation': "h", 'yanchor': "bottom", 'y': 1.02, 'xanchor': "right", 'x': 1},
        hovermode="x unified",
        uirevision='constant',
    )

    return fig