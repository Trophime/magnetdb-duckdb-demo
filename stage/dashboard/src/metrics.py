import os
from datetime import datetime

import numpy as np

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")


def evaluate_mean(ref_y, sec_y_unaligned, sec_y_aligned):
    """Compare the mean of a reference signal against a secondary signal.

    Computes the mean of each series and the absolute/relative difference
    between the reference mean and the secondary mean, before and after
    time alignment. Comparing scalar means (rather than a point-by-point
    error) avoids issues from ``ref_y`` and ``sec_y_*`` having different
    lengths, which happens when pupitre and pigbrother files are sampled
    at different rates.

    Parameters
    ----------
    ref_y : :class:`~numpy.ndarray`
        Reference signal values.
    sec_y_unaligned : :class:`~numpy.ndarray`
        Secondary signal values before time alignment.
    sec_y_aligned : :class:`~numpy.ndarray`
        Secondary signal values after time alignment.

    Returns
    -------
    dict
        Keys ``ref_mean``, ``sec_mean_unaligned``, ``sec_mean_aligned``,
        ``abs_diff_unaligned``, ``abs_diff_aligned``, ``rel_diff_unaligned``
        [%], ``rel_diff_aligned`` [%].
    """
    ref_mean = float(np.nanmean(ref_y))
    sec_mean_unaligned = float(np.nanmean(sec_y_unaligned))
    sec_mean_aligned = float(np.nanmean(sec_y_aligned))

    abs_diff_unaligned = abs(sec_mean_unaligned - ref_mean)
    abs_diff_aligned = abs(sec_mean_aligned - ref_mean)

    if ref_mean != 0:
        rel_diff_unaligned = 100 * abs_diff_unaligned / abs(ref_mean)
        rel_diff_aligned = 100 * abs_diff_aligned / abs(ref_mean)
    else:
        rel_diff_unaligned = float("nan")
        rel_diff_aligned = float("nan")

    return {
        "ref_mean": ref_mean,
        "sec_mean_unaligned": sec_mean_unaligned,
        "sec_mean_aligned": sec_mean_aligned,
        "abs_diff_unaligned": abs_diff_unaligned,
        "abs_diff_aligned": abs_diff_aligned,
        "rel_diff_unaligned": rel_diff_unaligned,
        "rel_diff_aligned": rel_diff_aligned,
    }


def generate_metrics_report(ref_file, sec_file, results):
    """Write a plain-text mean-comparison report to disk.

    Parameters
    ----------
    ref_file : str
        Path or name of the reference file.
    sec_file : str
        Path or name of the secondary file.
    results : dict
        Output of :func:`evaluate_mean`.

    Returns
    -------
    str
        Absolute path to the written report file.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)

    ref_basename = os.path.splitext(os.path.basename(ref_file))[0]
    sec_basename = os.path.splitext(os.path.basename(sec_file))[0]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = os.path.join(
        REPORTS_DIR, f"comparison_{ref_basename}_vs_{sec_basename}_{timestamp}.txt"
    )

    lines = [
        "Metrics report",
        "==============",
        f"Reference file : {ref_file}",
        f"Secondary file : {sec_file}",
        "",
        f"Reference mean            : {results['ref_mean']:.6g}",
        f"Secondary mean (unaligned): {results['sec_mean_unaligned']:.6g}",
        f"Secondary mean (aligned)  : {results['sec_mean_aligned']:.6g}",
        "",
        f"Absolute diff (unaligned) : {results['abs_diff_unaligned']:.6g}",
        f"Absolute diff (aligned)   : {results['abs_diff_aligned']:.6g}",
        f"Relative diff (unaligned) : {results['rel_diff_unaligned']:.2f} %",
        f"Relative diff (aligned)   : {results['rel_diff_aligned']:.2f} %",
    ]

    with open(report_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return report_path
