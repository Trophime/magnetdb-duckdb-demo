from urllib.parse import quote

import pandas as pd


def experiment_link(row):
    """Render an Experiment cell as a markdown link pre-loading Home with this row's assembly/file.

    Parameters
    ----------
    row : :class:`~pandas.Series`
        Row with ``"Experiment"`` (:class:`~pandas.Timestamp` or scalar),
        ``"File"``, and ``"Assembly"`` entries.

    Returns
    -------
    str
        Markdown link to ``/file_viewer`` pre-loaded with the row's assembly and file,
        or the plain label if no file is associated with the row.
    """
    label = (
        row["Experiment"].strftime("%Y-%m-%d - %H:%M:%S")
        if pd.notna(row["Experiment"])
        else str(row["Experiment"])
    )
    if pd.isna(row["File"]) or not row["File"]:
        return label
    href = f"/file_viewer?assembly={quote(str(row['Assembly']), safe='')}&file={quote(str(row['File']), safe='')}"
    return f"[{label}]({href})"


def overview_record_link(row):
    """Render an Overview Record cell as a markdown link into ``/overview-records``.

    Parameters
    ----------
    row : :class:`~pandas.Series`
        Row with ``"Overview Record"`` (``overview_records.filename``) and
        ``"Assembly"`` entries.

    Returns
    -------
    str
        Markdown link to ``/overview-records`` pre-loaded with the row's
        assembly and record filename, or the plain label if the row has no
        filename.
    """
    label = row["Overview Record"]
    if pd.isna(label) or not label:
        return str(label)
    href = (
        f"/overview-records?assembly={quote(str(row['Assembly']), safe='')}"
        f"&record={quote(str(label), safe='')}"
    )
    return f"[{label}]({href})"
