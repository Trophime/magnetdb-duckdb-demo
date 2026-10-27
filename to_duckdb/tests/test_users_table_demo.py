"""
Tests for demos/users_table_demo.py: session merging, acronym corrections,
and the experiments_ids fallback margin.
"""

import csv
from datetime import datetime

import pytest

from crud import insert_assembly
from demos.users_table_demo import (
    build_users,
    insert_users,
    load_acronym_corrections,
    load_log,
    update_experiments_ids,
)
from tests.conftest import ASSEMBLY_DATA

LOG_FIELDS = ["timestamp", "UserCode", "Magnet", "HStart", "HStop"]


def _ts(value: str) -> datetime:
    """Parse an ISO timestamp."""
    return datetime.fromisoformat(value)


def _build(records):
    """Run build_users on {acronym: [(housing, variant, hstart, hstop)]} with no proposals."""
    sessions = {
        acronym: [(h, v, _ts(s), _ts(e) if e else None) for h, v, s, e in items]
        for acronym, items in records.items()
    }
    timestamps = {acronym: [s[2] for s in items] for acronym, items in sessions.items()}
    users, _, _ = build_users(sessions, timestamps, {}, fuzzy_cutoff=0.8)
    return sorted(
        (u["acronym"], u["housing"], u["hstart"], u["hstop"]) for u in users
    )


# ---------------------------------------------------------------------------
# build_users: session merging
# ---------------------------------------------------------------------------


def test_overlapping_e_and_i_merge_into_one_row():
    rows = _build({"A": [
        ("M9", "e", "2024-01-01 10:00:00", "2024-01-01 12:00:00"),
        ("M9", "i", "2024-01-01 09:30:00", "2024-01-01 11:00:00"),
    ]})
    assert rows == [("A", "M9", _ts("2024-01-01 09:30:00"), _ts("2024-01-01 12:00:00"))]


def test_i_session_alone_creates_its_own_row():
    rows = _build({"A": [("M9", "i", "2024-01-01 10:00:00", "2024-01-01 11:00:00")]})
    assert rows == [("A", "M9", _ts("2024-01-01 10:00:00"), _ts("2024-01-01 11:00:00"))]


def test_non_overlapping_sessions_stay_separate():
    rows = _build({"A": [
        ("M9", "e", "2024-01-01 10:00:00", "2024-01-01 11:00:00"),
        ("M9", "i", "2024-01-01 11:30:00", "2024-01-01 12:00:00"),
    ]})
    assert len(rows) == 2


def test_overlapping_sessions_of_different_users_stay_separate():
    rows = _build({
        "A": [("M9", "e", "2024-01-01 10:00:00", "2024-01-01 12:00:00")],
        "B": [("M9", "i", "2024-01-01 10:00:00", "2024-01-01 12:00:00")],
    })
    assert [r[0] for r in rows] == ["A", "B"]


def test_open_session_starting_inside_a_row_is_absorbed():
    rows = _build({"A": [
        ("M9", "e", "2024-01-01 10:00:00", "2024-01-01 12:00:00"),
        ("M9", "i", "2024-01-01 10:01:00", None),
    ]})
    assert rows == [("A", "M9", _ts("2024-01-01 10:00:00"), _ts("2024-01-01 12:00:00"))]


def test_housing_without_variants_unchanged():
    rows = _build({"A": [
        ("M5", None, "2024-01-01 10:00:00", "2024-01-01 11:00:00"),
        ("M5", None, "2024-01-01 13:00:00", "2024-01-01 14:00:00"),
    ]})
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Acronym corrections
# ---------------------------------------------------------------------------


def _write_csv(path, fields, rows):
    """Write `rows` (list of dicts) as a CSV with header `fields`."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _log_row(timestamp, acronym, magnet, hstart, hstop):
    """Build one EXPERIENCES_LOG row with HStart/HStop in the log's own format."""
    fmt = "%m/%d/%y  %H:%M:%S.000 PM"
    return {
        "timestamp": timestamp,
        "UserCode": acronym,
        "Magnet": magnet,
        "HStart": _ts(hstart).strftime(fmt),
        "HStop": _ts(hstop).strftime(fmt),
    }


@pytest.fixture
def log_csv(tmp_path):
    """A log where GCS01-118 (M10e) is a typo of GSC01-118 (M10i) in one session."""
    return _write_csv(tmp_path / "log.csv", LOG_FIELDS, [
        _log_row("2018-12-06 15:05:24", "GCS01-118", "M10e",
                 "2018-12-06 15:05:24", "2018-12-06 22:58:01"),
        _log_row("2018-12-06 15:05:40", "GSC01-118", "M10i",
                 "2018-12-06 15:05:40", "2018-12-06 22:58:01"),
        _log_row("2018-12-07 10:00:00", "GCS01-118", "M10e",
                 "2018-12-07 10:00:00", "2018-12-07 11:00:00"),
    ])


CORRECTION_FIELDS = ["timestamp", "magnet", "acronym", "corrected_acronym", "reason"]
GOOD_CORRECTION = {
    "timestamp": "2018-12-06 15:05:24",
    "magnet": "M10e",
    "acronym": "GCS01-118",
    "corrected_acronym": "GSC01-118",
    "reason": "typo",
}


def test_correction_merges_row_with_its_partner(tmp_path, log_csv):
    corrections = load_acronym_corrections(
        _write_csv(tmp_path / "c.csv", CORRECTION_FIELDS, [GOOD_CORRECTION])
    )
    sessions, timestamps, *_ = load_log(log_csv, None, None, corrections)
    users, _, _ = build_users(sessions, timestamps, {}, fuzzy_cutoff=0.8)
    keys = sorted((u["acronym"], u["hstart"]) for u in users)
    # Corrected row merged with GSC01-118's M10i; the same acronym on
    # another timestamp is left alone.
    assert keys == [
        ("GCS01-118", _ts("2018-12-07 10:00:00")),
        ("GSC01-118", _ts("2018-12-06 15:05:24")),
    ]


def test_correction_with_other_magnet_is_not_applied(tmp_path, log_csv, capsys):
    corrections = load_acronym_corrections(_write_csv(
        tmp_path / "c.csv", CORRECTION_FIELDS, [{**GOOD_CORRECTION, "magnet": "M10i"}]
    ))
    sessions, *_ = load_log(log_csv, None, None, corrections)
    assert len(sessions["GCS01-118"]) == 2
    assert "matched no EXPERIENCES_LOG row" in capsys.readouterr().out


@pytest.mark.parametrize(
    "rows",
    [
        [GOOD_CORRECTION, GOOD_CORRECTION],
        [{**GOOD_CORRECTION, "reason": " "}],
    ],
    ids=["duplicate", "empty-reason"],
)
def test_invalid_corrections_file_raises(tmp_path, rows):
    with pytest.raises(ValueError):
        load_acronym_corrections(_write_csv(tmp_path / "c.csv", CORRECTION_FIELDS, rows))


def test_correction_to_unknown_acronym_raises(tmp_path, log_csv):
    corrections = load_acronym_corrections(_write_csv(
        tmp_path / "c.csv", CORRECTION_FIELDS,
        [{**GOOD_CORRECTION, "corrected_acronym": "NOPE-999"}],
    ))
    with pytest.raises(ValueError, match="NOPE-999"):
        load_log(log_csv, None, None, corrections)


# ---------------------------------------------------------------------------
# update_experiments_ids: fallback margin
# ---------------------------------------------------------------------------


def _user(acronym, hstart, hstop):
    """A minimal users row on housing M10."""
    return {
        "acronym": acronym, "research_area": None, "type": None, "country": None,
        "local_contact": None, "call_number": None, "access_mode": None,
        "housing": "M10", "hstart": _ts(hstart), "hstop": _ts(hstop),
    }


@pytest.fixture
def con_linking(con):
    """In-memory DB with one M10 assembly, ready for users/experiments rows."""
    insert_assembly(con, {**ASSEMBLY_DATA, "name": "M10_A250101_00"}, verbose=False)
    return con


def _add_experiments(con, files):
    """Insert experiments with ids 1..n for the given pupitre filenames."""
    for i, file in enumerate(files, start=1):
        con.execute(
            "INSERT INTO experiments (id, name, file, assembly_name) VALUES (?, ?, ?, ?)",
            [i, file, file, "M10_A250101_00"],
        )


def _links(con):
    """Return {acronym: experiments_ids} for every users row."""
    return dict(con.execute("SELECT acronym, experiments_ids FROM users").fetchall())


def test_margin_links_file_just_before_hstart(con_linking):
    insert_users(con_linking, [_user("A", "2025-01-01 10:00:00", "2025-01-01 11:00:00")],
                 verbose=False)
    _add_experiments(con_linking, ["2025.01.01 - 09:57:00.txt"])
    update_experiments_ids(con_linking, verbose=False, margin=0)
    assert _links(con_linking) == {"A": None}
    update_experiments_ids(con_linking, verbose=False, margin=5)
    assert _links(con_linking) == {"A": [1]}


def test_margin_does_not_touch_exact_links(con_linking):
    insert_users(con_linking, [
        _user("A", "2025-01-01 10:00:00", "2025-01-01 11:00:00"),
        _user("B", "2025-01-01 11:02:00", "2025-01-01 12:00:00"),
    ], verbose=False)
    _add_experiments(con_linking, ["2025.01.01 - 11:03:00.txt"])
    stats = update_experiments_ids(con_linking, verbose=False, margin=5)
    assert _links(con_linking) == {"A": None, "B": [1]}
    assert stats["fallback"] == 0


def test_margin_skips_file_near_two_users(con_linking):
    insert_users(con_linking, [
        _user("A", "2025-01-01 10:00:00", "2025-01-01 11:00:00"),
        _user("B", "2025-01-01 11:04:00", "2025-01-01 12:00:00"),
    ], verbose=False)
    _add_experiments(con_linking, ["2025.01.01 - 11:02:00.txt"])
    stats = update_experiments_ids(con_linking, verbose=False, margin=5)
    assert _links(con_linking) == {"A": None, "B": None}
    assert stats["fallback_ambiguous"] == 1


def test_margin_picks_nearest_row_of_same_user(con_linking):
    insert_users(con_linking, [
        _user("A", "2025-01-01 10:00:00", "2025-01-01 11:00:00"),
        _user("A", "2025-01-01 11:05:00", "2025-01-01 12:00:00"),
    ], verbose=False)
    _add_experiments(con_linking, ["2025.01.01 - 11:04:00.txt"])
    update_experiments_ids(con_linking, verbose=False, margin=5)
    rows = con_linking.execute(
        "SELECT hstart, experiments_ids FROM users ORDER BY hstart"
    ).fetchall()
    assert [ids for _, ids in rows] == [None, [1]]
