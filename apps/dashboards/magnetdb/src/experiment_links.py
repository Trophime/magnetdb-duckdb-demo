from urllib.parse import quote

import pandas as pd


def file_viewer_href(assembly_name, filename):
    """Build a ``/file_viewer`` URL pre-loaded with *assembly_name* and *filename*.

    Parameters
    ----------
    assembly_name : str
        Assembly owning *filename*.
    filename : str
        Source filename to preselect.

    Returns
    -------
    str
        ``/file_viewer?assembly=...&file=...`` URL, query-escaped.
    """
    return f"/file_viewer?assembly={quote(str(assembly_name), safe='')}&file={quote(str(filename), safe='')}"


def overview_record_href(assembly_name, record):
    """Build a ``/overview-records`` URL pre-loaded with *assembly_name* and *record*.

    Parameters
    ----------
    assembly_name : str
        Assembly owning *record*.
    record : str
        ``overview_records.filename`` to preselect.

    Returns
    -------
    str
        ``/overview-records?assembly=...&record=...`` URL, query-escaped.
    """
    return (
        f"/overview-records?assembly={quote(str(assembly_name), safe='')}"
        f"&record={quote(str(record), safe='')}"
    )


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


def signal_stats_links(row):
    """Render a Signal stats cell as markdown links into ``/stats_viewer``.

    Parameters
    ----------
    row : :class:`~pandas.Series`
        Row with ``"Signal stats"`` (``", "``-joined
        ``overview_records.sources_signal_stats`` filenames) and
        ``"Assembly"`` entries.

    Returns
    -------
    str
        One markdown link per stats file to ``/stats_viewer`` pre-loaded with
        the row's assembly and that file, joined by ``", "``; an empty string
        if the row has no stats file.
    """
    stats = row["Signal stats"]
    if pd.isna(stats) or not stats:
        return ""
    assembly = quote(str(row["Assembly"]), safe="")
    return ", ".join(
        f"[{name}](/stats_viewer?assembly={assembly}&file={quote(name, safe='')})"
        for name in str(stats).split(", ")
    )


def assembly_link(row):
    """Render an Assembly cell as a markdown link into ``/assembly_stats`` pre-filtered to it.

    Parameters
    ----------
    row : :class:`~pandas.Series`
        Row with an ``"Assembly"`` entry.

    Returns
    -------
    str
        Markdown link to ``/assembly_stats`` pre-loaded with the row's
        assembly filter, or the plain label if the row has no assembly.
    """
    label = row["Assembly"]
    if pd.isna(label) or not label:
        return str(label)
    href = f"/assembly_stats?assembly={quote(str(label), safe='')}"
    return f"[{label}]({href})"


def magnet_link(row):
    """Render a Magnet cell as a markdown link into ``/magnet_stats`` pre-filtered to it.

    Parameters
    ----------
    row : :class:`~pandas.Series`
        Row with a ``"Magnet"`` entry.

    Returns
    -------
    str
        Markdown link to ``/magnet_stats`` pre-loaded with the row's
        magnet filter, or the plain label if the row has no magnet.
    """
    label = row["Magnet"]
    if pd.isna(label) or not label:
        return str(label)
    href = f"/magnet_stats?magnet={quote(str(label), safe='')}"
    return f"[{label}]({href})"


def part_link(row):
    """Render a Part cell as a markdown link into ``/part_stats`` pre-filtered to it.

    Parameters
    ----------
    row : :class:`~pandas.Series`
        Row with a ``"Part"`` entry.

    Returns
    -------
    str
        Markdown link to ``/part_stats`` pre-loaded with the row's
        part filter, or the plain label if the row has no part.
    """
    label = row["Part"]
    if pd.isna(label) or not label:
        return str(label)
    href = f"/part_stats?part={quote(str(label), safe='')}"
    return f"[{label}]({href})"
