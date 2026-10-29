"""suggest_rings.py — rings for insert magnets that have none (PLAN_insert_rings.md)."""

import json
from datetime import date

import duckdb
import pytest

import suggest_rings
from schema import ensure_schema
from suggest_rings import (
    Lifetime,
    RingInfo,
    Slot,
    drawing_number,
    existing_violations,
    format_report,
    load_lifetimes,
    ring_fits,
    suggest,
)

R12 = (10.0, 20.0, 21.0, 30.0)
R23 = (21.0, 30.0, 31.0, 40.0)
GEOM12 = "/p/FAM/Ring-H1H2.yaml"
GEOM23 = "/p/FAM/Ring-H2H3.yaml"
GEOMETRIES = {GEOM12: (R12, "FAM-001-A"), GEOM23: (R23, "FAM-002-A")}
MATERIAL = {"name": "MA26021002", "nuance": "CuCrZr"}


def _slot(magnet, index=1, r=R12):
    return Slot(magnet=magnet, index=index, helices=(f"{magnet}_a", f"{magnet}_b"), r=r, family="FAM")


def _ring(name, holders=(), r=R12, drawing="FAM-001-C", geometry=GEOM12):
    data = {"name": name, "type": "ring", "status": "in_stock",
            "design_office_reference": drawing, "material": MATERIAL, "geometry": geometry}
    return RingInfo(name=name, r=r, drawing=drawing, geometry=geometry, data=data, holders=tuple(holders))


def _life(start, end=None, dead=False):
    return Lifetime(date.fromisoformat(start), date.fromisoformat(end) if end else None, dead)


def _run(slots, rings, lifetimes, **kwargs):
    kwargs.setdefault("created", date(2026, 10, 29))
    return suggest(slots, {r.name: r for r in rings}, GEOMETRIES, lifetimes, **kwargs)


# ---------------------------------------------------------------------------
# Fit (rule 2)
# ---------------------------------------------------------------------------


def test_ring_fits_within_tolerance_and_rejects_beyond():
    assert ring_fits((10.1, 20.0, 21.0, 30.0), "FAM-001-A", R12, {"FAM-001"}, 0.1)
    assert not ring_fits((10.2, 20.0, 21.0, 30.0), "FAM-001-A", R12, {"FAM-001"}, 0.1)


def test_drawing_match_ignores_revision_and_rejects_other_number():
    assert drawing_number("HL-27-041-A") == drawing_number("HL-27-041-D") == "HL-27-041"
    assert drawing_number("HL-27-034C") == "HL-27-034"  # R21040901: revision without hyphen
    assert ring_fits(R12, "FAM-001-D", R12, {"FAM-001"}, 0.1)
    assert not ring_fits(R12, "FAM-009-A", R12, {"FAM-001"}, 0.1)
    assert ring_fits(R12, None, R12, {"FAM-001"}, 0.1)
    assert ring_fits(R12, "FAM-009-A", R12, set(), 0.1)


# ---------------------------------------------------------------------------
# Lifetimes and sharing (rules 3 and 4)
# ---------------------------------------------------------------------------


def test_overlap_allows_handover():
    assert not _life("2020-01-01", "2021-01-01").overlaps(_life("2021-01-01", "2022-01-01"))
    assert _life("2020-01-01", "2021-01-02").overlaps(_life("2021-01-01", "2022-01-01"))
    assert _life("2020-01-01").overlaps(_life("2030-01-01", "2031-01-01"))


def test_load_lifetimes_counts_in_stock_period(con):
    history = [
        {"status": "in_stock", "date": "2019-01-01 07:00:00"},
        {"status": "retired", "date": "2020-06-01 07:00:00"},
        {"status": "dead", "date": "2021-01-01 07:00:00"},
    ]
    con.execute(
        "INSERT INTO magnets (name, type, status, assembled_at, status_history) VALUES "
        "('M_A', 'insert', 'retired', '2018-01-01', ?), ('M_B', 'insert', 'in_stock', '2019-01-01', '[]')",
        [json.dumps(history)],
    )
    lifetimes = load_lifetimes(con)
    assert lifetimes["M_A"] == _life("2018-01-01", "2020-06-01")
    assert lifetimes["M_B"] == _life("2019-01-01")


def test_load_lifetimes_takes_earliest_end_and_flags_death(con):
    # a "Superseded" event logged before the (earlier) known death must not move the end
    history = [
        {"status": "retired", "date": "2025-01-20 07:00:00", "description": "Superseded by magnet 'X'."},
        {"status": "dead", "date": "2024-12-06 07:00:00"},
    ]
    con.execute(
        "INSERT INTO magnets (name, type, status, assembled_at, status_history) "
        "VALUES ('M_D', 'insert', 'dead', '2009-05-26', ?)",
        [json.dumps(history)],
    )
    assert load_lifetimes(con)["M_D"] == _life("2009-05-26", "2024-12-06", dead=True)


def test_overlapping_targets_never_share_a_ring():
    lifetimes = {"T1": _life("2020-01-01", "2022-01-01"), "T2": _life("2021-01-01", "2023-01-01")}
    s = _run([_slot("T1"), _slot("T2")], [_ring("R1")], lifetimes)
    assert s.chosen[("T1", 1)] == "R1"
    assert s.chosen[("T2", 1)] != "R1"
    assert len(s.placeholders) == 1


def test_back_to_back_chain_shares_a_ring():
    lifetimes = {"T1": _life("2020-01-01", "2021-01-01"), "T2": _life("2021-01-01", "2022-01-01")}
    s = _run([_slot("T1"), _slot("T2")], [_ring("R1")], lifetimes)
    assert s.chosen == {("T1", 1): "R1", ("T2", 1): "R1"}
    assert s.placeholders == []


def test_ring_that_died_with_its_holder_is_not_reused():
    lifetimes = {"D": _life("2018-01-01", "2020-01-01", dead=True), "T1": _life("2021-01-01", "2022-01-01")}
    s = _run([_slot("T1")], [_ring("R1", holders=["D"])], lifetimes)
    assert s.chosen[("T1", 1)] == s.placeholders[0].name
    assert "R1 [D] died in D" in format_report(s)


def test_dead_target_cannot_take_ring_of_later_magnet():
    lifetimes = {"T1": _life("2018-01-01", "2020-01-01", dead=True), "L": _life("2021-01-01")}
    s = _run([_slot("T1")], [_ring("R1", holders=["L"])], lifetimes)
    assert s.chosen[("T1", 1)] == s.placeholders[0].name
    assert "R1 [L] would die in T1" in format_report(s)


def test_dead_target_placeholder_not_shared_with_later_target():
    lifetimes = {"T1": _life("2018-01-01", "2020-01-01", dead=True), "T2": _life("2021-01-01", "2022-01-01")}
    s = _run([_slot("T1"), _slot("T2")], [], lifetimes)
    assert len(s.placeholders) == 2


def test_ring_of_retired_holder_is_reused():
    lifetimes = {"H": _life("2018-01-01", "2020-01-01"), "T1": _life("2021-01-01", "2022-01-01")}
    s = _run([_slot("T1")], [_ring("R1", holders=["H"])], lifetimes)
    assert s.chosen[("T1", 1)] == "R1"


def test_ring_blocked_by_overlapping_holder():
    lifetimes = {"T1": _life("2020-01-01", "2022-01-01"), "H": _life("2021-01-01")}
    s = _run([_slot("T1")], [_ring("R1", holders=["H"])], lifetimes)
    assert s.chosen[("T1", 1)] == s.placeholders[0].name


# ---------------------------------------------------------------------------
# Real rings first, minimal placeholders (rule 5)
# ---------------------------------------------------------------------------


def test_real_rings_used_before_placeholders():
    # Greedy oldest-first would give the free R1 to T1 and leave T2 without a ring.
    lifetimes = {"T1": _life("2020-01-01", "2022-01-01"), "T2": _life("2021-01-01", "2023-01-01"),
                 "H": _life("2022-06-01")}  # H blocks R2 for T2 only
    rings = [_ring("R1"), _ring("R2", holders=["H"])]
    s = _run([_slot("T1"), _slot("T2")], rings, lifetimes)
    assert s.chosen == {("T1", 1): "R2", ("T2", 1): "R1"}
    assert s.placeholders == []


def test_non_overlapping_magnets_share_one_placeholder():
    lifetimes = {"T1": _life("2020-01-01", "2021-01-01"), "T2": _life("2022-01-01", "2023-01-01")}
    s = _run([_slot("T1"), _slot("T2")], [], lifetimes)
    assert len(s.placeholders) == 1
    assert s.chosen[("T1", 1)] == s.chosen[("T2", 1)] == s.placeholders[0].name


@pytest.mark.parametrize("lifetimes, expected", [
    ({"T1": ("2020-01-01", "2023-01-01"), "T2": ("2020-06-01", "2023-01-01"),
      "T3": ("2021-01-01", "2023-01-01")}, 3),
    ({"T1": ("2020-01-01", "2021-01-01"), "T2": ("2021-01-01", "2022-01-01"),
      "T3": ("2022-01-01", "2023-01-01")}, 1),
])
def test_placeholder_count_equals_largest_overlap(lifetimes, expected):
    lifetimes = {k: _life(*v) for k, v in lifetimes.items()}
    s = _run([_slot(m) for m in lifetimes], [], lifetimes)
    assert len(s.placeholders) == expected


# ---------------------------------------------------------------------------
# Tie-break (rule 6) and excluded holders (rule 7)
# ---------------------------------------------------------------------------


def test_tie_break_prefers_handover_then_free_then_name():
    lifetimes = {"T1": _life("2020-01-01", "2021-01-01"),
                 "OLD": _life("2010-01-01", "2019-01-01"), "NEXT": _life("2021-01-01")}
    rings = [_ring("R1", holders=["OLD"]), _ring("R2"), _ring("R3", holders=["NEXT"])]
    assert _run([_slot("T1")], rings, lifetimes).chosen[("T1", 1)] == "R3"
    assert _run([_slot("T1")], rings[:2], lifetimes).chosen[("T1", 1)] == "R2"
    rings = [_ring("R5"), _ring("R4")]
    assert _run([_slot("T1")], rings, lifetimes).chosen[("T1", 1)] == "R4"


def test_excluded_holder_ring_never_chosen_and_reported():
    lifetimes = {"T1": _life("2020-01-01", "2021-01-01"), "MX": _life("2022-01-01")}
    s = _run([_slot("T1")], [_ring("R1", holders=["MX"])], lifetimes, excluded_holders=("MX",))
    assert s.chosen[("T1", 1)] == s.placeholders[0].name
    assert "R1" in s.excluded
    report = format_report(s)
    assert "R1 [MX]" in report and "excluded" in report


def test_report_shows_candidates_with_their_magnets():
    lifetimes = {"T1": _life("2020-01-01", "2021-01-01"), "H": _life("2020-06-01")}
    s = _run([_slot("T1")], [_ring("R1"), _ring("R2", holders=["H"])], lifetimes)
    report = format_report(s)
    assert "R1 [-]" in report
    assert "R2 [H]" in report and "overlaps H" in report


# ---------------------------------------------------------------------------
# Placeholders, empty slots, violations
# ---------------------------------------------------------------------------


def test_placeholder_json_fields():
    lifetimes = {"T1": _life("2020-01-01", "2021-01-01")}
    s = _run([_slot("T1")], [_ring("R9", r=R23, drawing="FAM-002-C", geometry=GEOM23)], lifetimes)
    data = json.loads(json.dumps(s.placeholders[0].to_json()))
    assert data["name"] == "R26102901"
    assert data["type"] == "ring" and data["status"] == "in_stock"
    assert data["geometry"] == GEOM12
    assert data["design_office_reference"] == "FAM-001-A"
    assert data["material"] == MATERIAL
    assert data["manufactured_at"] == "2020-01-01"
    assert data["description"] == suggest_rings.PLACEHOLDER_DESCRIPTION
    assert data["description"].startswith("IA guessed")


def test_placeholder_numbering_skips_existing_names():
    lifetimes = {"T1": _life("2020-01-01", "2021-01-01"), "T2": _life("2020-06-01", "2021-01-01")}
    s = _run([_slot("T1"), _slot("T2")], [], lifetimes, existing_names={"R26102901"})
    assert [p.name for p in s.placeholders] == ["R26102902", "R26102903"]


def test_slot_without_geometry_file_is_reported_and_left_empty():
    lifetimes = {"T1": _life("2020-01-01", "2021-01-01")}
    s = _run([_slot("T1", r=(50.0, 60.0, 61.0, 70.0))], [], lifetimes)
    assert ("T1", 1) not in s.chosen
    assert s.placeholders == []
    assert "no ring geometry" in s.empty[("T1", 1)]
    assert "no ring geometry" in format_report(s)


def test_existing_violation_reported():
    lifetimes = {"A": _life("2020-01-01", "2022-01-01"), "B": _life("2021-01-01"),
                 "C": _life("2022-01-01")}
    holders = {"R1": ["A", "B"], "R2": ["A", "C"]}
    assert existing_violations(holders, lifetimes) == [("R1", "A", "B")]


def test_existing_reuse_after_death_reported():
    lifetimes = {"D": _life("2018-01-01", "2020-01-01", dead=True), "L": _life("2021-01-01")}
    assert existing_violations({"R1": ["D", "L"]}, lifetimes) == [("R1", "D", "L")]


# ---------------------------------------------------------------------------
# CLI: --write
# ---------------------------------------------------------------------------


def _write_yaml(path, tag, r, cad=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"!<{tag}>\nname: {path.stem}\nr: [{', '.join(str(x) for x in r)}]\n"
    if cad:
        text += f"cad: {cad}\n"
    path.write_text(text)


@pytest.fixture
def project(tmp_path):
    """Project dir with one 3-helix target T1 (no rings) and one free ring R1 for H1H2."""
    root = tmp_path / "projects"
    json_dir = root / "magnetdb.json"
    json_dir.mkdir(parents=True)
    helices = []
    for i, r in enumerate([(10.0, 20.0), (21.0, 30.0), (31.0, 40.0)], start=1):
        _write_yaml(root / "FAM" / f"H{i}.yaml", "Helix", r)
        helices.append({"name": f"HX{i}", "type": "helix", "status": "in_stock",
                        "geometry": str(root / "FAM" / f"H{i}.yaml")})
    _write_yaml(root / "FAM" / "Ring-H1H2.yaml", "Ring", R12, "FAM-001-A")
    _write_yaml(root / "FAM" / "Ring-H2H3.yaml", "Ring", R23, "FAM-002-A")
    magnet = {"name": "T1", "status": "in_stock", "parts": helices}
    (json_dir / "T1.json").write_text(json.dumps(magnet, indent=4))
    ring = {"name": "R1", "type": "ring", "status": "in_stock", "design_office_reference": "FAM-001-A",
            "material": MATERIAL, "geometry": str(root / "FAM" / "Ring-H1H2.yaml")}
    (json_dir / "R1.json").write_text(json.dumps(ring, indent=4))

    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    con.execute("INSERT INTO magnets (name, type, status, assembled_at) VALUES ('T1', 'insert', 'in_stock', '2020-01-01')")
    for i in (1, 2, 3):
        con.execute("INSERT INTO parts (name, type) VALUES (?, 'helix')", [f"HX{i}"])
        con.execute("INSERT INTO magnet_parts VALUES ('T1', ?, ?, ?)", [f"HX{i}", i - 1, i])
    con.close()
    return db, json_dir


def test_write_inserts_after_last_helix_and_is_idempotent(project, capsys):
    db, json_dir = project
    args = ["--db", str(db), "--json-dir", str(json_dir), "--write"]
    assert suggest_rings.main(args) == 0
    parts = json.loads((json_dir / "T1.json").read_text())["parts"]
    name = f"R{date.today():%y%m%d}01"
    assert [p["name"] for p in parts] == ["HX1", "HX2", "HX3", "R1", name]
    assert parts[3] == json.loads((json_dir / "R1.json").read_text())
    placeholder = json.loads((json_dir / f"{name}.json").read_text())
    assert parts[4] == placeholder
    assert placeholder["design_office_reference"] == "FAM-002-A"

    before = {p.name: p.read_text() for p in json_dir.iterdir()}
    assert suggest_rings.main(args) == 0
    assert {p.name: p.read_text() for p in json_dir.iterdir()} == before
    assert "no target" in capsys.readouterr().out


def test_report_without_write_changes_nothing(project):
    db, json_dir = project
    before = {p.name: p.read_text() for p in json_dir.iterdir()}
    assert suggest_rings.main(["--db", str(db), "--json-dir", str(json_dir)]) == 0
    assert {p.name: p.read_text() for p in json_dir.iterdir()} == before
