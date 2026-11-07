"""etl_spec: tags, check rules and record tags (PLAN_file_check_rules.md)."""

import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from etl_spec import (
    CHANNEL_TAG,
    add_rule,
    add_tag,
    build_pupitre_etl_spec,
    list_rules,
    list_tags,
    remove_rule,
    remove_tag,
    replace_record_tags,
    update_tag,
)
from tests.test_file_context import build_db

PARIS = ZoneInfo("Europe/Paris")
TAG = "check:current_mismatch"


@pytest.fixture()
def con():
    c = build_db()
    yield c
    c.close()


def _rules(con, assembly="M9_A260602_00", when=(2026, 6, 10)) -> dict:
    spec = build_pupitre_etl_spec(con, assembly, datetime(*when, tzinfo=PARIS))
    return {rule["name"]: rule for rule in spec["rules"]}


def _tags(con) -> dict:
    return {tag["name"]: tag for tag in list_tags(con)}


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------


def test_channel_tag_seeded(con):
    tag = _tags(con)[CHANNEL_TAG]
    assert (tag["color"], tag["severity"]) == ("#e2d9f3", 1)


def test_add_tag_normalises_colour(con):
    add_tag(con, TAG, "#CFE2FF", severity=2, description="Icoil vs Idcct")
    assert _tags(con)[TAG] == {
        "name": TAG, "color": "#cfe2ff", "severity": 2, "description": "Icoil vs Idcct",
    }


@pytest.mark.parametrize("name", ["current_mismatch", "Check:x", "check:", "check:a-b", "a:b:c"])
def test_bad_tag_name_refused(con, name):
    with pytest.raises(ValueError, match="name"):
        add_tag(con, name, "#cfe2ff")


@pytest.mark.parametrize(
    "color, match",
    [
        ("red", "colour"),
        ("#fff", "colour"),
        ("#F8D7DA", "geometry"),
        ("#fff3cd", "missing dates"),
        ("#e2d9f3", CHANNEL_TAG),
    ],
)
def test_bad_colour_refused(con, color, match):
    with pytest.raises(ValueError, match=match):
        add_tag(con, TAG, color)


def test_duplicate_tag_refused(con):
    add_tag(con, TAG, "#cfe2ff")
    with pytest.raises(ValueError, match="exists"):
        add_tag(con, TAG, "#d1e7dd")


def test_update_tag(con):
    update_tag(con, CHANNEL_TAG, color="#D1E7DD", severity=3)
    update_tag(con, CHANNEL_TAG, color="#d1e7dd")  # its own colour
    tag = _tags(con)[CHANNEL_TAG]
    assert (tag["color"], tag["severity"]) == ("#d1e7dd", 3)
    with pytest.raises(ValueError, match="geometry"):
        update_tag(con, CHANNEL_TAG, color="#f8d7da")
    with pytest.raises(ValueError, match="check:nope"):
        update_tag(con, "check:nope", severity=2)


def test_remove_tag(con):
    add_tag(con, TAG, "#cfe2ff")
    remove_tag(con, TAG)
    assert TAG not in _tags(con)
    with pytest.raises(ValueError, match=TAG):
        remove_tag(con, TAG)


def test_remove_channel_tag_refused(con):
    with pytest.raises(ValueError, match="channel"):
        remove_tag(con, CHANNEL_TAG)


def test_remove_tag_used_by_rule_refused(con):
    add_tag(con, TAG, "#cfe2ff")
    add_rule(con, "r", "IH - Icoil2", "max_abs", 5.0, housing="M9", tag=TAG)
    with pytest.raises(ValueError, match="rule"):
        remove_tag(con, TAG)


def test_remove_tag_used_by_record_refused(con):
    add_tag(con, TAG, "#cfe2ff")
    replace_record_tags(con, "experiments", "1", [
        {"kind": "rule", "name": "r", "value": 7.0, "tol": 5.0, "tag": TAG, "ok": False},
    ])
    with pytest.raises(ValueError, match="record"):
        remove_tag(con, TAG)


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


def test_housing_rule_in_spec(con):
    add_rule(con, "A1_vs_A2", "Idcct1 - Idcct2", "p99_abs", 10.0, housing="M9", unit="A")
    assert _rules(con)["A1_vs_A2"] == {
        "name": "A1_vs_A2", "expr": "Idcct1 - Idcct2", "stat": "p99_abs", "tol": 10.0,
        "unit": "A", "scope": "housing",
    }
    assert "A1_vs_A2" in _rules(con, "M9_B", (2025, 6, 1))
    assert "A1_vs_A2" not in _rules(con, "M10_B", (2026, 1, 1))


def test_rule_applies_to_all_versions_by_default(con):
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M8")
    assert "r" in _rules(con, "M8_A230919_00", (2026, 3, 5, 15, 56))  # M8-211225
    assert "r" in _rules(con, "M8_A230919_00", (2026, 3, 6))  # M8-260305


def test_rule_restricted_to_one_version(con):
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M8", version="M8-260305")
    assert "r" not in _rules(con, "M8_A230919_00", (2026, 3, 5, 15, 56))
    assert "r" in _rules(con, "M8_A230919_00", (2026, 3, 6))


def test_override_order(con):
    """magnet over assembly over housing; at one level, version-specific over all versions."""
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M9")
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 9.0, housing="M9", version="M9-181109")
    assert _rules(con)["r"]["tol"] == 9.0
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 7.0, assembly="M9_A260602_00")
    assert (_rules(con)["r"]["tol"], _rules(con)["r"]["scope"]) == (7.0, "assembly")
    add_rule(con, "r", "IH - Icoil2", "max_abs", 5.0, assembly="M9_A260602_00", magnet="M25032101")
    assert _rules(con)["r"]["scope"] == "magnet:M25032101"
    assert _rules(con, "M9_B", (2025, 6, 1))["r"]["tol"] == 9.0  # other assembly


def test_add_rule_replaces_same_scope(con):
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M9")
    add_rule(con, "r", "Idcct1 - Idcct2", "p99_abs", 8.0, housing="M9")
    assert [(r["name"], r["stat"], r["tol"]) for r in list_rules(con)] == [("r", "p99_abs", 8.0)]


def test_rule_with_tag(con):
    add_tag(con, TAG, "#cfe2ff")
    add_rule(con, "r", "IH - Icoil2", "max_abs", 5.0, housing="M9", tag=TAG)
    assert _rules(con)["r"]["tag"] == TAG


def test_rule_tag_must_exist(con):
    with pytest.raises(ValueError, match="check:nope"):
        add_rule(con, "r", "IH - Icoil2", "max_abs", 5.0, housing="M9", tag="check:nope")


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({}, "housing"),
        ({"housing": "M9", "assembly": "M9_A260602_00"}, "housing"),
        ({"magnet": "M25032101"}, "assembly"),
        ({"housing": "M99"}, "M99"),
        ({"assembly": "NOPE"}, "NOPE"),
        ({"assembly": "M9_A260602_00", "magnet": "M8Bi"}, "M8Bi"),
        ({"housing": "M9", "version": "M8-260305"}, "M8"),
        ({"housing": "M9", "version": "M9-999999"}, "M9-999999"),
        ({"housing": "M9", "sources": ["pupitre", "pigbrother"]}, "sources"),
        ({"housing": "M9", "applies_to": "overview_records"}, "applies_to"),
    ],
)
def test_bad_scope_refused(con, kwargs, match):
    with pytest.raises(ValueError, match=match):
        add_rule(con, "r", "IH - Icoil2", "max_abs", 5.0, **kwargs)
    assert list_rules(con) == []


def test_bad_expr_refused(con):
    with pytest.raises(ValueError, match="@"):
        add_rule(con, "r", "IH - @x", "max_abs", 5.0, housing="M9")


def test_same_name_on_two_magnets_refused(con):
    add_rule(con, "cur", "IH - Icoil2", "max_abs", 5.0, assembly="M9_A260602_00", magnet="M25032101")
    with pytest.raises(ValueError, match="M25032101"):
        add_rule(con, "cur", "IB - Icoil15", "max_abs", 5.0, assembly="M9_A260602_00", magnet="M9Bi")


def test_remove_rule(con):
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M9")
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 5.0, assembly="M9_A260602_00")
    remove_rule(con, "r", housing="M9")
    assert [r["assembly_name"] for r in list_rules(con)] == ["M9_A260602_00"]
    with pytest.raises(ValueError, match="no rule"):
        remove_rule(con, "r", housing="M9")


def test_list_rules_filters(con):
    add_rule(con, "h", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M9")
    add_rule(con, "a", "Idcct1 - Idcct2", "max_abs", 5.0, assembly="M9_A260602_00")
    add_rule(con, "m", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M8")
    assert {r["name"] for r in list_rules(con, housing="M9")} == {"h", "a"}
    assert {r["name"] for r in list_rules(con, assembly="M9_A260602_00")} == {"h", "a"}


def test_rule_changes_logged(con):
    add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M9")
    with pytest.raises(ValueError):
        add_rule(con, "r", "Idcct1 - Idcct2", "max_abs", 5.0, housing="M99")
    remove_rule(con, "r", housing="M9")
    rows = con.execute(
        "SELECT operation, record_name, status FROM operation_log "
        "WHERE table_name = 'check_rules' ORDER BY id"
    ).fetchall()
    assert rows == [("upsert", "M9:r", "ok"), ("upsert", "M99:r", "error"), ("delete", "M9:r", "ok")]


# ---------------------------------------------------------------------------
# record tags
# ---------------------------------------------------------------------------


def _checks() -> list[dict]:
    return [
        {"kind": "housing_version", "spec": "v1", "data": "v2", "ok": False},
        {"kind": "rule", "name": "IH_vs_Icoil2", "value": 13.2, "tol": 5.0, "tag": TAG, "ok": False},
        {"kind": "rule", "name": "untagged", "value": 9.0, "tol": 5.0, "tag": None, "ok": False},
        {"kind": "rule", "name": "passing", "value": 1.0, "tol": 5.0, "tag": TAG, "ok": True},
        {"kind": "rule", "name": "missing", "value": None, "tol": 5.0, "tag": TAG, "ok": None},
        {"kind": "channel", "channel": 5, "fields": {"Tcal5": 9.3, "Ucoil5": 0.03}, "ok": False},
        {"kind": "channel", "channel": 6, "fields": {}, "ok": True},
    ]


def _record_tags(con, key="1"):
    return con.execute(
        "SELECT tag, rule, value, tolerance FROM record_tags "
        "WHERE record_table = 'experiments' AND record_key = ? ORDER BY tag, rule",
        [key],
    ).fetchall()


def test_record_tags_from_failed_checks(con):
    add_tag(con, TAG, "#cfe2ff")
    replace_record_tags(con, "experiments", "1", _checks())
    assert _record_tags(con) == [(CHANNEL_TAG, "ch5", 9.3, 0.0), (TAG, "IH_vs_Icoil2", 13.2, 5.0)]


def test_record_tags_replaced(con):
    add_tag(con, TAG, "#cfe2ff")
    replace_record_tags(con, "experiments", "1", _checks())
    replace_record_tags(con, "experiments", "2", _checks())
    replace_record_tags(con, "experiments", "1", [])
    assert _record_tags(con, "1") == []
    assert len(_record_tags(con, "2")) == 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run(monkeypatch, *argv):
    import magnetdb

    monkeypatch.setattr(sys, "argv", ["magnetdb", *argv])
    magnetdb.main()


def test_cli_tag_and_rule(tmp_path, monkeypatch, capsys):
    db = tmp_path / "test.duckdb"
    build_db(str(db)).close()
    _run(monkeypatch, "tag", "add", TAG, "--color", "#cfe2ff", "--severity", "2", "--db", str(db))
    _run(monkeypatch, "tag", "update", TAG, "--description", "Icoil vs Idcct", "--db", str(db))
    _run(
        monkeypatch, "rule", "add", "IH_vs_Icoil2", "--expr", "IH - Icoil2", "--stat", "max_abs",
        "--tol", "5", "--unit", "A", "--assembly", "M9_A260602_00", "--magnet", "M25032101",
        "--tag", TAG, "--db", str(db),
    )
    capsys.readouterr()
    _run(monkeypatch, "tag", "list", "--db", str(db))
    _run(monkeypatch, "rule", "show", "--assembly", "M9_A260602_00", "--db", str(db))
    out = capsys.readouterr().out
    assert TAG in out and "Icoil vs Idcct" in out and "IH_vs_Icoil2" in out

    _run(monkeypatch, "etl", "show", "M9_A260602_00", "--db", str(db))
    spec = json.loads(capsys.readouterr().out)
    assert spec["rules"] == [{
        "name": "IH_vs_Icoil2", "expr": "IH - Icoil2", "stat": "max_abs", "tol": 5.0,
        "unit": "A", "tag": TAG, "scope": "magnet:M25032101",
    }]

    _run(monkeypatch, "rule", "remove", "IH_vs_Icoil2", "--assembly", "M9_A260602_00",
         "--magnet", "M25032101", "--db", str(db))
    _run(monkeypatch, "tag", "remove", TAG, "--db", str(db))
    capsys.readouterr()
    _run(monkeypatch, "rule", "show", "--db", str(db))
    assert "IH_vs_Icoil2" not in capsys.readouterr().out
