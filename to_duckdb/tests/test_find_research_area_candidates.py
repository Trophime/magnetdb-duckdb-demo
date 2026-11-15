"""Tests for demos/find_research_area_candidates.py: the LNCMI Tech Staff group (ROADMAP A23)."""

import duckdb
import pytest

from demos.find_research_area_candidates import (
    TECH_STAFF_RESEARCH_AREA,
    apply_tech_staff,
    fetch_tech_staff_rows,
)


@pytest.fixture
def users_con():
    """In-memory ``users`` with tech-staff, MAINTENANCE, normal and already-tagged rows."""
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE users (acronym VARCHAR, research_area VARCHAR, "
        "call_number VARCHAR, access_mode VARCHAR)"
    )
    con.executemany(
        "INSERT INTO users (acronym, research_area) VALUES (?, ?)",
        [
            ("EXPLOIT.", None),
            ("TEST", None),
            ("M10 TEST", None),
            ("MAINTENANCE", None),
            ("MAINTENABCE", None),  # typo found in EXPERIENCES_LOG (M10e, 2017-11-24)
            ("maintenance", None),
            ("GSO02", None),  # a normal acronym
            ("MAINTENANCE", "Magnetism"),  # already has a research area
        ],
    )
    yield con
    con.close()


def test_fetch_tech_staff_rows_includes_maintenance_codes(users_con):
    assert fetch_tech_staff_rows(users_con) == [
        ("EXPLOIT.", 1),
        ("M10 TEST", 1),
        ("MAINTENABCE", 1),
        ("MAINTENANCE", 1),
        ("TEST", 1),
        ("maintenance", 1),
    ]


def test_apply_tech_staff_tags_only_the_group(users_con):
    assert apply_tech_staff(users_con, verbose=False) == 6

    rows = users_con.execute(
        "SELECT acronym, research_area FROM users ORDER BY acronym, research_area"
    ).fetchall()
    assert ("GSO02", None) in rows
    assert ("MAINTENANCE", "Magnetism") in rows
    tagged = sorted(a for a, area in rows if area == TECH_STAFF_RESEARCH_AREA)
    assert tagged == sorted(
        ["EXPLOIT.", "TEST", "M10 TEST", "MAINTENANCE", "MAINTENABCE", "maintenance"]
    )
