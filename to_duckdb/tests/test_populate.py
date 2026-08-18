"""Unit tests for populate.py's operationaldata path handling."""

from pathlib import Path

from populate import _insert_operationaldata, resolve_operationaldata_path


# ---------------------------------------------------------------------------
# resolve_operationaldata_path
# ---------------------------------------------------------------------------


def test_resolve_operationaldata_path_joins_records_base():
    path = resolve_operationaldata_path(
        "pbsurv/M10/Overview/250101-0000.tdms", records_base=Path("/records"),
    )
    assert path == Path("/records/pbsurv/M10/Overview/250101-0000.tdms")


def test_resolve_operationaldata_path_passes_through_absolute_legacy_value():
    legacy = "/mnt/LNCMIG-Data/records/pbsurv/M10/Overview/250101-0000.tdms"
    path = resolve_operationaldata_path(legacy, records_base=Path("/records"))
    assert path == Path(legacy)


# ---------------------------------------------------------------------------
# _insert_operationaldata
# ---------------------------------------------------------------------------


def test_insert_operationaldata_strips_records_base(con_populated):
    records_base = Path("/mnt/LNCMIG-Data/records")
    fpath = records_base / "pbsurv" / "M10" / "Overview" / "250101-0000.tdms"
    inserted = _insert_operationaldata(con_populated, "ASSEMBLY_01", fpath, "Overview", records_base)
    assert inserted
    row = con_populated.execute(
        "SELECT file FROM operationaldata WHERE assembly_name = 'ASSEMBLY_01'"
    ).fetchone()
    assert row[0] == "pbsurv/M10/Overview/250101-0000.tdms"


def test_insert_operationaldata_dedup(con_populated):
    records_base = Path("/mnt/LNCMIG-Data/records")
    fpath = records_base / "pbsurv" / "M10" / "Overview" / "250101-0000.tdms"
    assert _insert_operationaldata(con_populated, "ASSEMBLY_01", fpath, "Overview", records_base)
    assert not _insert_operationaldata(con_populated, "ASSEMBLY_01", fpath, "Overview", records_base)
