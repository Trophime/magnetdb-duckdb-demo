#!/usr/bin/env python
"""Archive every data file recorded while a magnet was part of an assembly.

The magnet's history is read from ``assembly_magnets``. For each assembly it
belonged to, the magnet's window is::

    start = COALESCE(assembly_magnets.commissioned_at,   assemblies.commissioned_at)
    end   = COALESCE(assembly_magnets.decommissioned_at, assemblies.decommissioned_at)

A NULL ``start`` means no lower bound; a NULL ``end`` means "until now".
Commission dates are interpreted in ``--db-tz`` (default UTC). Within each
window (bounds inclusive) the script collects:

  - ``experiments`` of the assembly, dated by the Europe/Paris timestamp
    embedded in the pupitre filename (``"YYYY.MM.DD - HH:MM:SS.txt"``);
  - live ``overview_records`` (``merged_into IS NULL``) of the assembly,
    dated by ``t0`` (stored in UTC), with all files of their ``sources_*``
    columns.

Records whose date cannot be determined are excluded with a warning.
``sources_hybrid_*`` and ``sources_*_runlog`` files are skipped (no on-disk
layout is defined for them yet, see ``PLAN_archive_magnet_hybrid_runlog.md``).

Files are stored with their path relative to the records root, so the
archive can be extracted straight into it::

    srv-data-install/<housing>/<YYYY.MM.DD - HH:MM:SS>.txt
    pbsurv/<housing>/<Overview|Fichiers_Archive|...>/<file>.tdms

The archive is a ``.tar.xz`` (xz beats zstd on TDMS files, see
``PLAN_archive_magnet_data.md``), compressed by the system ``xz -T0`` when
available, else by Python's single-threaded ``lzma``. Two manifests are
appended at the archive root:

  - ``MANIFEST_<magnet>.md5`` — ``md5sum -c`` format, one line per file;
  - ``MANIFEST_<magnet>.csv`` — provenance, one row per (record, file).

Run from the repository root, e.g.::

    python to_duckdb/demos/archive_magnet_data.py --magnet M10Bitters --dry-run
    python to_duckdb/demos/archive_magnet_data.py --magnet M19061901 \\
        --db to_duckdb/magnetdb.duckdb --output stage/M19061901.tar.xz
"""

import argparse
import contextlib
import csv
import hashlib
import io
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import duckdb
from python_magnetrun.utils.files import (
    DIR_ARCHIVE,
    DIR_DEFAULT,
    DIR_SPIKE,
    DIR_STATS,
    DIR_TRIGGER,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB  # noqa: E402
from populate import (  # noqa: E402
    _PBSURV,
    _RECORDS_BASE,
    _SRV_SUBDIR,
    FILE_TZ,
    as_aware,
    parse_pupitre_file_ts,
)

_UTC = ZoneInfo("UTC")

# TDMS mode (2nd underscore-part of the filename) -> subdirectory under pbsurv/<housing>/
_TDMS_MODE_DIRS = {
    "Overview": "Overview",
    "Archive": DIR_ARCHIVE,
    "Default": DIR_DEFAULT,
    "Spikes": DIR_SPIKE,
    "ManuelTrig": DIR_TRIGGER,
    "Stats": DIR_STATS,
}

# overview_records source columns whose on-disk layout is known
_ARCHIVED_SOURCES = ("overview", "archive", "pupitre", "default", "trigger", "spike", "stats")
# ... and those skipped for now (no layout defined)
_SKIPPED_SOURCES = (
    "hybrid_kHz", "hybrid_rms", "hybrid_trigger", "hybrid_vprocess",
    "pigbrother_runlog", "pupitre_runlog",
)

_CSV_FIELDS = ["assembly", "record_kind", "record_name", "source_type", "path", "size_bytes", "md5", "status"]


def _in_window(ts: datetime, start: datetime | None, end: datetime) -> bool:
    """Return True if tz-aware *ts* lies in ``[start, end]`` (no lower bound if *start* is None)."""
    return (start is None or ts >= start) and ts <= end


def get_magnet_windows(con, magnet: str, db_tz: ZoneInfo) -> list[dict]:
    """Return the assemblies a magnet belonged to, with the magnet's time window.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    magnet : str
        Magnet name (``magnets.name``).
    db_tz : zoneinfo.ZoneInfo
        Timezone of the stored ``commissioned_at``/``decommissioned_at``.

    Returns
    -------
    list of dict
        One dict per assembly with keys ``assembly``, ``housing``, ``start``
        (tz-aware or None) and ``end`` (tz-aware; "now" when not
        decommissioned), ordered by ``start``.
    """
    rows = con.execute(
        """
        SELECT am.assembly_name, a.housing,
               COALESCE(am.commissioned_at, a.commissioned_at)     AS t_start,
               COALESCE(am.decommissioned_at, a.decommissioned_at) AS t_end
        FROM assembly_magnets am
        JOIN assemblies a ON a.name = am.assembly_name
        WHERE am.magnet_name = ?
        ORDER BY t_start NULLS FIRST, am.assembly_name
        """,
        [magnet],
    ).fetchall()
    now = datetime.now(tz=db_tz)
    return [
        {
            "assembly": assembly,
            "housing": housing,
            "start": as_aware(t_start, db_tz),
            "end": as_aware(t_end, db_tz) if t_end is not None else now,
        }
        for assembly, housing, t_start, t_end in rows
    ]


def get_experiments(con, window: dict) -> list[tuple[str, str]]:
    """Return the experiments of an assembly that fall in the magnet's window.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    window : dict
        One item of :func:`get_magnet_windows`.

    Returns
    -------
    list of tuple of str
        ``(experiments.name, experiments.file)`` pairs.
    """
    rows = con.execute(
        "SELECT name, file FROM experiments WHERE assembly_name = ? ORDER BY file",
        [window["assembly"]],
    ).fetchall()
    kept = []
    for name, file in rows:
        ts = parse_pupitre_file_ts(Path(file).name)
        if ts is None:
            print(f"  [WARN] experiment {name!r}: no timestamp in filename {file!r}, excluded")
            continue
        if _in_window(ts, window["start"], window["end"]):
            kept.append((name, file))
    return kept


def get_overview_records(con, window: dict) -> list[tuple[str, dict[str, list[str]]]]:
    """Return the live overview records of an assembly that fall in the magnet's window.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    window : dict
        One item of :func:`get_magnet_windows`.

    Returns
    -------
    list of tuple
        ``(overview_records.filename, sources)`` pairs, where ``sources`` maps
        a source type (e.g. ``"archive"``) to its list of filenames. Only the
        ``sources_*`` columns present in the database are included.
    """
    existing = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'overview_records' AND column_name LIKE 'sources_%'"
        ).fetchall()
    }
    source_types = [s for s in _ARCHIVED_SOURCES + _SKIPPED_SOURCES if f"sources_{s}" in existing]
    columns = ", ".join(f'"sources_{s}"' for s in source_types)
    rows = con.execute(
        f"SELECT filename, t0, {columns} FROM overview_records "
        "WHERE assembly_name = ? AND merged_into IS NULL ORDER BY t0",
        [window["assembly"]],
    ).fetchall()
    kept = []
    for filename, t0, *lists in rows:
        if t0 is None:
            print(f"  [WARN] overview record {filename!r}: t0 is NULL, excluded")
            continue
        if _in_window(as_aware(t0, _UTC), window["start"], window["end"]):
            kept.append((filename, {s: list(v or []) for s, v in zip(source_types, lists)}))
    return kept


def resolve_path(name: str, housing: str, records_base: Path) -> tuple[Path, str] | None:
    """Resolve a stored data filename to its on-disk path and archive member name.

    Parameters
    ----------
    name : str
        Value stored in the DB: a bare pupitre ``.txt`` or TDMS filename, or
        an absolute path.
    housing : str
        Housing of the assembly (used for pupitre files).
    records_base : :class:`~pathlib.Path`
        Root of the records tree.

    Returns
    -------
    tuple of (:class:`~pathlib.Path`, str) or None
        ``(source path, archive member name relative to records_base)``, or
        None when the filename matches no known layout.
    """
    path = Path(name)
    if path.is_absolute():
        try:
            return path, str(path.relative_to(records_base))
        except ValueError:
            return path, str(path.relative_to(path.anchor))
    if path.suffix.lower() == ".txt":
        rel = Path(_SRV_SUBDIR) / housing / name
    elif path.suffix.lower() == ".tdms":
        parts = path.name.split("_")
        if len(parts) < 2 or parts[1] not in _TDMS_MODE_DIRS:
            return None
        rel = Path(_PBSURV) / parts[0] / _TDMS_MODE_DIRS[parts[1]] / name
    else:
        return None
    return records_base / rel, str(rel)


class _HashingReader:
    """File wrapper that updates an md5 digest with everything read through it."""

    def __init__(self, fileobj):
        self._fileobj = fileobj
        self.md5 = hashlib.md5()

    def read(self, size=-1):
        data = self._fileobj.read(size)
        self.md5.update(data)
        return data


@contextlib.contextmanager
def _open_archive(output: Path, level: int):
    """Yield a writable tarfile compressed with xz (multi-threaded when the xz binary exists)."""
    xz = shutil.which("xz")
    if xz is None:
        print("[WARN] xz binary not found, falling back to single-threaded Python lzma (slow)")
        with tarfile.open(output, "w:xz", preset=level, dereference=True) as tar:
            yield tar
        return
    with open(output, "wb") as out:
        proc = subprocess.Popen([xz, f"-{level}", "-T0", "-c"], stdin=subprocess.PIPE, stdout=out)
        try:
            with tarfile.open(fileobj=proc.stdin, mode="w|", dereference=True) as tar:
                yield tar
        except BaseException:
            proc.kill()
            raise
        finally:
            proc.stdin.close()
            returncode = proc.wait()
    if returncode != 0:
        raise RuntimeError(f"xz exited with status {returncode}")


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add an in-memory file to *tar*."""
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def _csv_text(rows: list[dict]) -> str:
    """Render manifest rows as CSV text."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def write_archive(
    output: Path, level: int, files: dict[str, Path], rows: list[dict], magnet: str,
) -> dict[str, str]:
    """Write the files and the two manifests into an xz-compressed tarball.

    Parameters
    ----------
    output : :class:`~pathlib.Path`
        Archive to create.
    level : int
        xz preset, 0–9.
    files : dict of str to :class:`~pathlib.Path`
        Archive member name -> existing source path; each file is read once.
    rows : list of dict
        CSV manifest rows; their ``md5`` field is filled in place.
    magnet : str
        Magnet name, used to name the manifests.

    Returns
    -------
    dict of str to str
        Archive member name -> md5 hex digest.
    """
    digests: dict[str, str] = {}
    with _open_archive(output, level) as tar:
        for i, (arcname, src) in enumerate(files.items(), 1):
            print(f"  [{i}/{len(files)}] {arcname}")
            info = tar.gettarinfo(str(src), arcname=arcname)
            with open(src, "rb") as f:
                reader = _HashingReader(f)
                tar.addfile(info, reader)
            digests[arcname] = reader.md5.hexdigest()
        for row in rows:
            if row["status"] == "archived":
                row["md5"] = digests[row["path"]]
        md5_text = "".join(f"{digests[a]}  {a}\n" for a in files)
        _add_bytes(tar, f"MANIFEST_{magnet}.md5", md5_text.encode())
        _add_bytes(tar, f"MANIFEST_{magnet}.csv", _csv_text(rows).encode())
    return digests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--magnet", required=True, help="Magnet name (magnets.name)")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})")
    parser.add_argument(
        "--db-tz", default="UTC", dest="db_tz",
        help="Timezone of commissioned_at / decommissioned_at in the DB (default: UTC)",
    )
    parser.add_argument(
        "--records-base", default=str(_RECORDS_BASE), dest="records_base",
        help=f"Root of the records tree (default: {_RECORDS_BASE})",
    )
    parser.add_argument("--output", default=None, help="Output archive (default: <magnet>.tar.xz)")
    parser.add_argument(
        "--level", type=int, default=6, choices=range(10), metavar="{0..9}",
        help="xz compression preset (default: 6)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the selection and the CSV manifest, write no archive",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    try:
        db_tz = ZoneInfo(args.db_tz)
    except ZoneInfoNotFoundError:
        print(f"Error: Unknown timezone '{args.db_tz}'")
        sys.exit(1)
    records_base = Path(args.records_base).expanduser()
    output = Path(args.output) if args.output else Path(f"{args.magnet}.tar.xz")

    rows: list[dict] = []
    files: dict[str, Path] = {}
    skipped: dict[str, int] = {}

    def add(assembly: str, kind: str, record: str, source: str, name: str, housing: str) -> None:
        resolved = resolve_path(name, housing, records_base)
        if resolved is None:
            print(f"  [WARN] {kind} {record!r}: unknown layout for {source} file {name!r}, skipped")
            skipped[source] = skipped.get(source, 0) + 1
            return
        src, arcname = resolved
        exists = src.is_file()
        if exists:
            files.setdefault(arcname, src)
        rows.append({
            "assembly": assembly, "record_kind": kind, "record_name": record,
            "source_type": source, "path": arcname,
            "size_bytes": src.stat().st_size if exists else "", "md5": "",
            "status": "archived" if exists else "missing",
        })

    with duckdb.connect(str(db_path), read_only=True) as con:
        if con.execute("SELECT 1 FROM magnets WHERE name = ?", [args.magnet]).fetchone() is None:
            print(f"Error: magnet '{args.magnet}' not found in magnets table.")
            sys.exit(1)
        windows = get_magnet_windows(con, args.magnet, db_tz)
        if not windows:
            print(f"Error: magnet '{args.magnet}' has no assembly history (assembly_magnets).")
            sys.exit(1)

        print(f"Magnet {args.magnet}: {len(windows)} assembly(ies)")
        for w in windows:
            start = w["start"].astimezone(FILE_TZ).strftime("%Y-%m-%d %H:%M") if w["start"] else "-"
            end = w["end"].astimezone(FILE_TZ).strftime("%Y-%m-%d %H:%M")
            print(f"[{w['assembly']}] housing={w['housing']}  window {start} -> {end} (Europe/Paris)")
            experiments = get_experiments(con, w)
            overviews = get_overview_records(con, w)
            n_rows = len(rows)
            for name, file in experiments:
                add(w["assembly"], "experiment", name, "pupitre", file, w["housing"])
            for filename, sources in overviews:
                for source, names in sources.items():
                    for name in names:
                        if source in _SKIPPED_SOURCES:
                            skipped[source] = skipped.get(source, 0) + 1
                        else:
                            add(w["assembly"], "overview", filename, source, name, w["housing"])
            new = rows[n_rows:]
            found = len({r["path"] for r in new if r["status"] == "archived"})
            missing = len({r["path"] for r in new if r["status"] == "missing"})
            print(f"  {len(experiments)} experiment(s), {len(overviews)} overview record(s): "
                  f"{found} file(s) found, {missing} missing")

    missing_paths = sorted({r["path"] for r in rows if r["status"] == "missing"})
    if missing_paths:
        print(f"\n[WARN] {len(missing_paths)} file(s) not found under {records_base}:")
        for p in missing_paths:
            print(f"  {p}")
    if skipped:
        print(f"\n[WARN] skipped files (no known on-disk layout): {skipped}")

    total_bytes = sum(src.stat().st_size for src in files.values())
    print(f"\n{len(files)} unique file(s) to archive, {total_bytes / 1e6:.1f} MB")

    if args.dry_run:
        print()
        print(_csv_text(rows), end="")
        return
    if not files:
        print("Error: no data file found on disk, no archive written.")
        sys.exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {output} (xz -{args.level})")
    try:
        write_archive(output, args.level, files, rows, args.magnet)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    size = output.stat().st_size
    print(f"Archive written: {output}  {size / 1e6:.1f} MB  (ratio {total_bytes / max(size, 1):.2f})")


if __name__ == "__main__":
    main()
