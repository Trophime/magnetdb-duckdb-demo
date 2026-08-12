import argparse
import logging
from pathlib import Path
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pint
import scipy.signal as sg
from tabulate import tabulate
from python_magnetrun.analysis.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_PIGBROTHER_DATA_DIR,
    ThresholdConfig,
)
from python_magnetrun.analysis.processing import ProcessingConfig, process_overview_file
from python_magnetrun.analysis.field_comparison import (
    REFERENCE_LAG_KEYS,
    compare_all_fields,
    compute_reference_lag,
    discover_pupitre_pigbrother_fields,
    print_comparison_summary,
)
from python_magnetrun.analysis.loaders import load_files_data
from python_magnetrun.analysis.metrics import compare_series
from python_magnetrun.analysis.synchronization import (
    apply_lag_correction,
    check_lag_reliability,
    find_best_matching_regime,
)
from python_magnetrun.log_utils import LogConfig, setup_logging
from python_magnetrun.MagnetRun import load_mrun
from python_magnetrun.processing.plateaux import nplateaus
from python_magnetrun.plotting.backend import get_backend
from python_magnetrun.plotting.style import DEFAULT_STYLE
from python_magnetrun.plotting.timeseries import plot_overlay
from python_magnetrun.signature import Signature
from python_magnetrun.utils.timezone import series_utc_to_local_naive


def get_lag(
    df_pupitre,
    df_pb,
    column_current_pupitre="Idcct1",
    column_current_pigbrother="Courant_A1",
):
    """
    Calculate the time lag with high precision using FFT on normalized derivatives.
    """

    # 1.Convert timestamps to seconds and extract current values
    t_pupitre = df_pupitre["timestamp"].astype("int64") / 10**9
    t_pb = df_pb["timestamp"].astype("int64") / 10**9

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
    y_pup_norm = (y_pupitre_interp - np.mean(y_pupitre_interp)) / (
        np.std(y_pupitre_interp) + 1e-9
    )
    y_pb_norm = (y_pb_interp - np.mean(y_pb_interp)) / (np.std(y_pb_interp) + 1e-9)

    # 6. Compute the derivatives of the normalized signals
    dy_pupitre = np.gradient(y_pup_norm)
    dy_pb = np.gradient(y_pb_norm)

    # 7. Correlation using FFT
    correlation = sg.correlate(dy_pupitre, dy_pb, mode="full", method="fft")
    lags = sg.correlation_lags(len(dy_pupitre), len(dy_pb), mode="full")

    # 8. Extract best shift (lag) in seconds
    index_max = np.argmax(correlation)
    best_lag_indices = lags[index_max]

    # Convert in seconds
    lag_seconds = float(best_lag_indices * dt)

    return lag_seconds


def get_lag_per_pupitre_file(
    record,
    df_pb,
    group,
    column_current_pupitre,
    column_current_pigbrother,
    source="overview",
    lag_reference=None,
    pigbrother_unit=None,
    pupitre_unit=None,
    output_dir=None,
):
    """Compute get_lag() between df_pb and each pupitre file loaded individually.

    Loads each file in record.sources.pupitre on its own via load_files_data,
    rather than reading the already-concatenated record.get_pupitre(), so the
    per-file lag can be checked against the lag computed on the concatenated
    DataFrame -- i.e. whether concatenating pupitre files before running
    get_lag changes the result versus running it file-by-file.

    Parameters
    ----------
    record : OverviewRecord
        Record whose ``sources.pupitre`` files are processed individually.
    df_pb : :class:`~pandas.DataFrame`
        Pigbrother data (e.g. overview or archive) to compare each pupitre
        file against.
    group : str
        Pigbrother group name passed to ``load_files_data``.
    column_current_pupitre : str
        Pupitre current column used for lag computation.
    column_current_pigbrother : str
        Pigbrother current column used for lag computation.
    source : str, optional
        Pigbrother source name (``"overview"`` or ``"archive"``), forwarded
        to :func:`plot_lag_comparison` for the plot title/color.
    lag_reference : float, optional
        Reference lag [s], typically the single ``compute_reference_lag``
        result computed once on the concatenated pupitre data. When given
        together with ``output_dir``, a :func:`plot_lag_comparison` plot is
        saved for each file, reusing this same reference lag for every file.
    pigbrother_unit, pupitre_unit : str, optional
        Units forwarded to :func:`plot_lag_comparison` for axis conversion.
    output_dir : str or :class:`~pathlib.Path`, optional
        Directory to save per-file plots into. Plotting is skipped unless
        both ``output_dir`` and ``lag_reference`` are given.

    Returns
    -------
    list of tuple
        ``(filename, lag_seconds, n_rows)`` tuples; ``lag_seconds`` is
        ``None`` when the file failed to load or lacked
        ``column_current_pupitre``.
    """
    rows = []
    if record.sources is None:
        return rows
    for f in record.sources.pupitre:
        df_pupitre_i = load_files_data(
            [f], record.housing, group, [column_current_pupitre]
        )
        if df_pupitre_i.empty or column_current_pupitre not in df_pupitre_i.columns:
            rows.append((f, None, len(df_pupitre_i)))
            continue
        lag = get_lag(
            df_pupitre_i, df_pb, column_current_pupitre, column_current_pigbrother
        )
        rows.append((f, lag, len(df_pupitre_i)))

        if output_dir is not None and lag_reference is not None:
            plot_path = (
                Path(output_dir) / f"{Path(f).stem}_{column_current_pupitre}.png"
            )
            plot_lag_comparison(
                df_pb,
                column_current_pigbrother,
                df_pupitre_i,
                column_current_pupitre,
                lag,
                lag_reference,
                source,
                plot_path,
                pigbrother_unit=pigbrother_unit,
                pupitre_unit=pupitre_unit,
            )

    return rows


def get_plateaux_per_pupitre(
    record,
    column_current_pupitre,
    threshold=2.0e-2,
    num_points_threshold=600,
):
    """Compute nplateaus() for each pupitre file loaded individually.

    Loads each file in record.sources.pupitre on its own via load_mrun (the
    same helper load_files_data uses internally), mirroring
    get_lag_per_pupitre_file, then detects plateaux on column_current_pupitre
    with python_magnetrun.processing.plateaux.nplateaus.

    Returns a list of (filename, plateau_data, n_plateaus) tuples;
    plateau_data is None when the file failed to load or lacked
    column_current_pupitre.
    """
    rows = []
    if record.sources is None:
        return rows
    for f in record.sources.pupitre:
        print(
            f"get_plateaux_per_pupitre: processing {f} for {column_current_pupitre} (threshold={threshold}, num_points_threshold={num_points_threshold})..."
        )
        try:
            mrun = load_mrun(f, housing=record.housing)
            mdata = mrun.getMData()
        except (OSError, ValueError, RuntimeError, KeyError, UnicodeDecodeError) as e:
            print(f"get_plateaux_per_pupitre: failed to load {f}: {e}")
            rows.append((f, None, 0))
            continue
        if column_current_pupitre not in mdata.Keys:
            rows.append((f, None, 0))
            continue
        plateau_data = nplateaus(
            mdata,
            xField=("t", *mrun.getUnit("t")),
            yField=(column_current_pupitre, *mrun.getUnit(column_current_pupitre)),
            threshold=threshold,
            num_points_threshold=num_points_threshold,
            show=False,
            save=False,
        )
        rows.append((f, plateau_data, len(plateau_data)))
    return rows


def pick_columns(df_pupitre, df_pb):
    """Pick the current channel pair to use for lag computation.

    Prefers Idcct1/Courant_A1/Référence_A1; falls back to Idcct3/Courant_A3/Référence_A3 when either
    side lacks the first pair.
    """
    keys_pupitre = df_pupitre.columns
    keys_pb = df_pb.columns

    if "Idcct1" in keys_pupitre and "Courant_A1" in keys_pb:
        return "Idcct1", "Courant_A1", "Référence_A1"
    return "Idcct3", "Courant_A3", "Référence_A3"


def interpolate_onto(reference_df, reference_channel, other_df, other_key):
    """Interpolate other_df[other_key] onto reference_df's own timestamps.

    Both series are restricted to their overlapping time window. Mirrors
    python_magnetrun.analysis.field_comparison._interpolate_onto.
    """
    ref = reference_df[["timestamp", reference_channel]].dropna()
    oth = other_df[["timestamp", other_key]].dropna()

    origin = min(ref["timestamp"].iloc[0], oth["timestamp"].iloc[0])
    x_ref = ((ref["timestamp"] - origin) / pd.Timedelta(seconds=1)).to_numpy()
    x_oth = ((oth["timestamp"] - origin) / pd.Timedelta(seconds=1)).to_numpy()

    overlap_start = max(x_ref[0], x_oth[0])
    overlap_end = min(x_ref[-1], x_oth[-1])
    mask = (x_ref >= overlap_start) & (x_ref <= overlap_end)

    actual = ref[reference_channel].to_numpy(dtype=float)[mask]
    predicted = np.interp(x_ref[mask], x_oth, oth[other_key].to_numpy(dtype=float))
    return actual, predicted


def convert_units(values, from_unit, to_unit):
    """Convert values from from_unit to to_unit via pint."""
    ureg = pint.get_application_registry()
    return (values * ureg.Unit(from_unit)).to(ureg.Unit(to_unit)).magnitude


def compare_group_fields(df_pupitre, df_other, fields):
    """Compare every aliased field between (lag-corrected) pupitre and one pigbrother source.

    Pigbrother is the reference ("actual"); pupitre is interpolated onto it
    ("predicted"), matching field_comparison.py's compare_field convention.
    """
    rows = []
    for af in fields:
        if (
            af.pupitre_key not in df_pupitre.columns
            or af.pigbrother_channel not in df_other.columns
        ):
            continue
        actual, predicted = interpolate_onto(
            df_other, af.pigbrother_channel, df_pupitre, af.pupitre_key
        )
        if len(actual) < 2:
            continue

        if (
            af.pupitre_unit
            and af.pigbrother_unit
            and af.pupitre_unit != af.pigbrother_unit
        ):
            actual = convert_units(actual, af.pigbrother_unit, af.pupitre_unit)

        dist = compare_series(actual, predicted)["distances"]
        rows.append(
            [
                af.pupitre_key,
                f"{af.pigbrother_group}/{af.pigbrother_channel}",
                len(actual),
                f"{dist.correlation:.3f}",
                f"{dist.mape:.2f}",
                f"{dist.euclidean:.3f}",
                f"{dist.rmse:.3f}",
                f"{dist.mae:.3f}",
            ]
        )
    return rows


def fill_small_gaps(df, tkey="timestamp", max_gap_seconds=30.0):
    """Interpolate across small timing gaps so dt stays close to uniform.

    Inserts evenly-spaced, linearly-interpolated rows only inside gaps
    larger than 1.5x the median dt; existing rows are left untouched.
    Gaps larger than max_gap_seconds are left unfilled.
    """
    df = df.sort_values(tkey).reset_index(drop=True)
    dt = df[tkey].diff().dt.total_seconds()
    dt_median = dt.median()

    gap_positions = dt[(dt > dt_median * 1.5) & (dt <= max_gap_seconds)]
    if gap_positions.empty:
        return df

    print(
        f"Warning: interpolating across {len(gap_positions)} gap(s) up to "
        f"{gap_positions.max():.1f}s (median dt={dt_median:.2f}s)"
    )

    numeric_cols = df.select_dtypes(include="number").columns
    new_rows = []
    for idx, gap in gap_positions.items():
        i0, i1 = idx - 1, idx
        n_fill = int(round(gap / dt_median)) - 1
        for k in range(1, n_fill + 1):
            frac = k / (n_fill + 1)
            row = df.iloc[i0].copy()
            row[tkey] = df[tkey].iloc[i0] + pd.to_timedelta(frac * gap, unit="s")
            for col in numeric_cols:
                row[col] = df[col].iloc[i0] + frac * (
                    df[col].iloc[i1] - df[col].iloc[i0]
                )
            new_rows.append(row)

    return (
        pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        .sort_values(tkey)
        .reset_index(drop=True)
    )


def plot_lag_comparison(
    df_pigbrother,
    pigbrother_channel,
    df_pupitre,
    pupitre_channel,
    lag_get_lag,
    lag_reference,
    source,
    output_path,
    pigbrother_unit=None,
    pupitre_unit=None,
):
    """Overlay pigbrother reference against pupitre raw and shifted by each lag method."""
    df_pupitre_get_lag = apply_lag_correction(df_pupitre, lag_get_lag)
    df_pupitre_ref_lag = apply_lag_correction(df_pupitre, lag_reference)

    ref_label = f"pigbrother/{source}"
    raw_label = "pupitre (raw, no lag)"
    getlag_label = f"pupitre (get_lag={lag_get_lag:.2f}s)"
    reflag_label = f"pupitre (compute_reference_lag={lag_reference:.2f}s)"

    s_ref = df_pigbrother[["timestamp", pigbrother_channel]].rename(
        columns={pigbrother_channel: ref_label}
    )
    if pigbrother_unit and pupitre_unit and pigbrother_unit != pupitre_unit:
        s_ref[ref_label] = convert_units(
            s_ref[ref_label].to_numpy(dtype=float), pigbrother_unit, pupitre_unit
        )
    display_unit = pupitre_unit or pigbrother_unit

    s_raw = df_pupitre[["timestamp", pupitre_channel]].rename(
        columns={pupitre_channel: raw_label}
    )
    s_getlag = df_pupitre_get_lag[["timestamp", pupitre_channel]].rename(
        columns={pupitre_channel: getlag_label}
    )
    s_reflag = df_pupitre_ref_lag[["timestamp", pupitre_channel]].rename(
        columns={pupitre_channel: reflag_label}
    )

    merged = (
        pd.concat([s_ref, s_raw, s_getlag, s_reflag], ignore_index=True)
        .sort_values("timestamp", kind="stable")
        .reset_index(drop=True)
    )
    if display_unit:
        unit = pint.get_application_registry().Unit(display_unit)
        merged.attrs["units"] = {
            label: (display_unit, unit)
            for label in (ref_label, raw_label, getlag_label, reflag_label)
        }
    merged["timestamp"] = mdates.date2num(
        series_utc_to_local_naive(merged["timestamp"])
    )

    source_color = "blue" if source == "overview" else "red"
    fig = plot_overlay(
        merged,
        [ref_label, raw_label, getlag_label, reflag_label],
        t_col="timestamp",
        style=DEFAULT_STYLE,
        title=f"{pupitre_channel} vs {source}/{pigbrother_channel}: raw vs get_lag vs compute_reference_lag",
        colors=[source_color, "gray", "green", "orange"],
        field_styles=[
            (None, None, None, None),
            ("-.", None, None, None),
            ("--", None, None, None),
            (":", None, None, None),
        ],
    )
    for ax in getattr(fig, "_magnetrun_axes", None) or fig.axes:
        ax.xaxis_date()
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M:%S"))
    fig.autofmt_xdate()

    get_backend("matplotlib").save(fig, Path(output_path), dpi=DEFAULT_STYLE.dpi)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fichier-overview",
        default="M9_Overview_251202-1430.tdms",
    )
    parser.add_argument(
        "--pupitre-datadir",
        default=DEFAULT_DATA_DIR,
    )
    parser.add_argument(
        "--pigbrother-datadir",
        default=DEFAULT_PIGBROTHER_DATA_DIR,
    )
    parser.add_argument(
        "--log-file",
        default=str(Path(__file__).with_suffix(".log")),
    )
    args = parser.parse_args()

    setup_logging(
        config=LogConfig(
            level=logging.INFO, console=False, log_file=Path(args.log_file)
        )
    )

    fichier_overview_pattern = args.fichier_overview
    targeted_group = "Courants_Alimentations"
    housing = fichier_overview_pattern.split("_")[0]

    overview_dir = Path(args.pigbrother_datadir) / housing / "Overview"
    matches = sorted(overview_dir.glob(fichier_overview_pattern))

    if not matches:
        print(
            f"No overview files matching {fichier_overview_pattern!r} found in {overview_dir}"
        )
        return

    config = ProcessingConfig(
        pupitre_datadir=args.pupitre_datadir,
        pigbrother_datadir=args.pigbrother_datadir,
        group=targeted_group,
        synchronize=False,
    )

    for fichier_overview in matches:
        print(f"Discovering and processing {fichier_overview}...")
        try:
            record = process_overview_file(str(fichier_overview), config)

            print(f"Processed overview file: {record.filename}")
            print(f"  t0={record.t0}, duration={record.duration}s")
            print(f"  pupitre file: {record.sources.pupitre}")
            print(f"  archive file: {record.sources.archive}")
            print(f"  overview file: {record.sources.overview}")

            df_pupitre = record.get_pupitre()
            df_overview = record.get_overview()
            df_archive = record.get_archive()
            print(
                f"overview df: {len(df_overview)} rows, columns={list(df_overview.columns)}",
                flush=True,
            )

            all_fields = discover_pupitre_pigbrother_fields()
            reference_fields = {
                af.pupitre_key: af
                for af in all_fields
                if af.pupitre_key in REFERENCE_LAG_KEYS
            }
            fields = [af for af in all_fields if af.pigbrother_group == targeted_group]

            metrics_headers = [
                "pupitre_key",
                "pigbrother_alias",
                "n",
                "correlation",
                "mape [%]",
                "euclidean",
                "rmse",
                "mae",
            ]

            print("\n" + "=" * 40)

            if not df_pupitre.empty and not df_overview.empty:
                rows = compare_group_fields(df_pupitre, df_overview, fields)
                print(f"\nper-field metrics vs overview:")
                print(tabulate(rows, headers=metrics_headers, tablefmt="simple"))

                col_pup, col_ov, col_ref_ov = pick_columns(df_pupitre, df_overview)
                lag_overview = get_lag(df_pupitre, df_overview, col_pup, col_ov)
                ref_lag, ref_field = compute_reference_lag(
                    record,
                    "overview",
                    df_pupitre,
                    df_overview,
                    reference_fields,
                    lag_method="interpolated",
                )
                print(
                    f"pupitre vs overview ({col_pup}/{col_ov}): "
                    f"get_lag={lag_overview:.2f}s | "
                    f"compute_reference_lag={ref_lag.seconds:.2f}s "
                    f"({ref_lag.method}, field={ref_field.pupitre_key}/{ref_field.pigbrother_channel}, "
                    f"corr={ref_lag.correlation:.2f}, conf={ref_lag.confidence:.2f})"
                )

                per_file_plot_dir = Path(__file__).with_name(
                    f"{Path(__file__).stem}_{fichier_overview.stem}_overview_perfile_plots"
                )
                per_file_plot_dir.mkdir(parents=True, exist_ok=True)
                per_file_rows = get_lag_per_pupitre_file(
                    record,
                    df_overview,
                    targeted_group,
                    col_pup,
                    col_ov,
                    source="overview",
                    lag_reference=ref_lag.seconds,
                    pigbrother_unit=ref_field.pigbrother_unit,
                    pupitre_unit=ref_field.pupitre_unit,
                    output_dir=str(per_file_plot_dir),
                )
                print(
                    f"\nget_lag vs overview, per individual pupitre file "
                    f"(concatenated get_lag={lag_overview:.2f}s):"
                )
                print(
                    tabulate(
                        [
                            [
                                Path(f).name,
                                n,
                                f"{lag:.2f}" if lag is not None else "n/a",
                            ]
                            for f, lag, n in per_file_rows
                        ],
                        headers=["pupitre file", "n", "get_lag [s]"],
                        tablefmt="simple",
                    )
                )
                per_file_lags = [lag for _, lag, _ in per_file_rows if lag is not None]
                if per_file_lags:
                    max_dev = max(abs(lag - lag_overview) for lag in per_file_lags)
                    print(
                        f"max |per-file get_lag - concatenated get_lag| = {max_dev:.2f}s "
                        f"over {len(per_file_lags)}/{len(per_file_rows)} file(s)"
                    )

                df_pupitre_aligned = apply_lag_correction(
                    df_pupitre, lag_overview, reference_t0=record.t0
                )
                rows = compare_group_fields(df_pupitre_aligned, df_overview, fields)
                print(
                    f"\nget_lag-based per-field metrics vs overview (lag={lag_overview:.2f}s):"
                )
                print(tabulate(rows, headers=metrics_headers, tablefmt="simple"))

                for af in all_fields:
                    if (
                        af.pupitre_key not in df_pupitre.columns
                        or af.pigbrother_channel not in df_overview.columns
                    ):
                        continue
                    plot_path = Path(__file__).with_name(
                        f"{Path(__file__).stem}_{fichier_overview.stem}_overview_{af.pupitre_key}.png"
                    )
                    plot_lag_comparison(
                        df_overview,
                        af.pigbrother_channel,
                        df_pupitre,
                        af.pupitre_key,
                        lag_overview,
                        ref_lag.seconds,
                        "overview",
                        plot_path,
                        pigbrother_unit=af.pigbrother_unit,
                        pupitre_unit=af.pupitre_unit,
                    )
                    print(f"Saved comparison plot: {plot_path}")

                sig_pupitre_df = fill_small_gaps(df_pupitre_aligned)
                sig_overview_df = fill_small_gaps(df_overview)
                unit = pint.get_application_registry().Unit(
                    ref_field.pupitre_unit or "dimensionless"
                )
                thresholds = ThresholdConfig.default()
                pupitre_threshold = (
                    10  # thresholds.get(col_pup, thresholds.get(col_pup, 10.0))
                )
                pigbrother_threshold = (
                    10  # thresholds.get(col_ov, thresholds.get(col_ov, 5.))
                )
                print(
                    f"col_pup={col_pup}, pupitre_threshold={pupitre_threshold}, col_ov={col_ov}, pigbrother_threshold={pigbrother_threshold}"
                )

                sig_pupitre = Signature.from_df(
                    filename=str(fichier_overview),
                    t0=record.t0,
                    df=sig_pupitre_df,
                    key=col_pup,
                    symbol=col_pup,
                    unit=unit,
                    tkey="t",
                    threshold=pupitre_threshold,
                )
                sig_overview = Signature.from_df(
                    filename=str(fichier_overview),
                    t0=record.t0,
                    df=sig_overview_df,
                    key=col_ov,
                    symbol=col_ov,
                    unit=unit,
                    tkey="t",
                    threshold=pigbrother_threshold,
                )
                print(
                    f"\nPupitre {col_pup} signature (len={len(sig_pupitre.regimes)}): {''.join(sig_pupitre.regimes)}"
                )
                print(
                    f"Overview {col_ov} signature (len={len(sig_overview.regimes)}): {''.join(sig_overview.regimes)}"
                )
                sig_pupitre.compact()
                sig_overview.compact()
                print(
                    f"\nPupitre {col_pup} signature compact(len={len(sig_pupitre.regimes)}): {''.join(sig_pupitre.regimes)}"
                )
                print(
                    f"Overview {col_ov} signature compact(len={len(sig_overview.regimes)}): {''.join(sig_overview.regimes)}"
                )

                sig_ref_overview = Signature.from_df(
                    filename=str(fichier_overview),
                    t0=record.t0,
                    df=sig_overview_df,
                    key=col_ref_ov,
                    symbol=col_ov,
                    unit=unit,
                    tkey="t",
                    threshold=pigbrother_threshold,
                )
                print(
                    f"Overview {col_ref_ov} signature (len={len(sig_ref_overview.regimes)}): {''.join(sig_ref_overview.regimes)}"
                )
                sig_ref_overview.compact()
                print(
                    f"Overview {col_ref_ov} signature compact(len={len(sig_ref_overview.regimes)}): {''.join(sig_ref_overview.regimes)}"
                )

                """
                regime_matches = find_best_matching_regime(sig_pupitre, sig_overview)
                print("\nRegime match (pupitre vs overview signatures):")
                for m in regime_matches:
                    reliable = check_lag_reliability(m.lags, duration=record.duration)
                    print(
                        f"  {m.regime}->{m.match_regime}: score={m.score:.3f}, "
                        f"lags=(start={m.lags[0]:.2f}s, end={m.lags[1]:.2f}s), "
                        f"reliable={reliable}"
                    )
                """

                # add compute plateaux for df_pupitre_aligned["Field"]
                # see python_magnetrun.processing.plateaux -- nplateaux
                # thresholds: see python_magnetrun.analysis.config.ThresholdConfig.default()
                pupitre_field_threshold = (
                    1.0e-3  # thresholds.get("Field", thresholds.get("Field", 1.0e-3))
                )
                plateaux_per_pupitre = get_plateaux_per_pupitre(
                    record,
                    "Field",
                    threshold=pupitre_field_threshold,
                    num_points_threshold=10,
                )
                print(
                    f"\nget_plateaux_per_pupitre (threshold={pupitre_field_threshold}, num_points_threshold=10):"
                )
                for f, plateau_data, n_plateaus in plateaux_per_pupitre:
                    if plateau_data is None:
                        print(
                            f"  {Path(f).name}: failed to load or missing Field column"
                        )
                    else:
                        print(
                            f"  {Path(f).name}: n_plateaus={n_plateaus}, plateau_data={plateau_data}"
                        )

            else:
                print("pupitre vs overview: no data")

            print()

            if not df_pupitre.empty and not df_archive.empty:
                col_pup, col_arc, col_ref_arc = pick_columns(df_pupitre, df_archive)
                lag_archive = get_lag(df_pupitre, df_archive, col_pup, col_arc)
                ref_lag, ref_field = compute_reference_lag(
                    record,
                    "archive",
                    df_pupitre,
                    df_archive,
                    reference_fields,
                    lag_method="interpolated",
                )
                print(
                    f"pupitre vs archive  ({col_pup}/{col_arc}): "
                    f"get_lag={lag_archive:.2f}s | "
                    f"compute_reference_lag={ref_lag.seconds:.2f}s "
                    f"({ref_lag.method}, field={ref_field.pupitre_key}/{ref_field.pigbrother_channel}, "
                    f"corr={ref_lag.correlation:.2f}, conf={ref_lag.confidence:.2f})"
                )

                df_pupitre_aligned = apply_lag_correction(df_pupitre, lag_archive)
                rows = compare_group_fields(df_pupitre_aligned, df_archive, fields)
                print(
                    f"\nget_lag-based per-field metrics vs archive (lag={lag_archive:.2f}s):"
                )
                print(tabulate(rows, headers=metrics_headers, tablefmt="simple"))

                for af in all_fields:
                    if (
                        af.pupitre_key not in df_pupitre.columns
                        or af.pigbrother_channel not in df_archive.columns
                    ):
                        continue
                    plot_path = Path(__file__).with_name(
                        f"{Path(__file__).stem}_{fichier_overview.stem}_archive_{af.pupitre_key}.png"
                    )
                    plot_lag_comparison(
                        df_archive,
                        af.pigbrother_channel,
                        df_pupitre,
                        af.pupitre_key,
                        lag_archive,
                        ref_lag.seconds,
                        "archive",
                        plot_path,
                        pigbrother_unit=af.pigbrother_unit,
                        pupitre_unit=af.pupitre_unit,
                    )
                    print(f"Saved comparison plot: {plot_path}")
            else:
                print("pupitre vs archive: no data")

            print("\n" + "=" * 40 + "\n")

            plot_dir = Path(__file__).with_name(
                f"{Path(__file__).stem}_{fichier_overview.stem}_plots"
            )
            plot_dir.mkdir(parents=True, exist_ok=True)
            results = compare_all_fields(
                record,
                fields=fields,
                sources=("overview", "archive"),
                lag_method="interpolated",
                plot=True,
                output_dir=str(plot_dir),
            )
            print_comparison_summary(results)

            for results_for_key in results.values():
                for result in results_for_key.values():
                    if result.plot_path:
                        print(f"Saved field_comparison plot: {result.plot_path}")

        except Exception as e:
            print(f"Error during test {e}")


if __name__ == "__main__":
    main()
