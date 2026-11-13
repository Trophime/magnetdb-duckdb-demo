"""File quality and ETL check display in the experiment tables (PLAN_file_check_rules.md step 6)."""

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from dash.dash_table import DataTable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dash_selectors as selectors  # noqa: E402
import magnetdb_analysis as db  # noqa: E402

DCCT = {"tag": "check:dcct_mismatch", "rule": "A1_vs_A2", "value": 3099.9, "tolerance": 42.0,
        "color": "#d1e7dd", "severity": 1, "description": "The two DCCTs of one group differ"}
CHANNEL = {"tag": "check:channel_not_empty", "rule": "ch2", "value": 14.4, "tolerance": 0.0,
           "color": "#e2d9f3", "severity": 1, "description": "A removed channel is not 0"}
SEVERE = {"tag": "check:severe", "rule": "r", "value": 9.0, "tolerance": 1.0,
          "color": "#cfe2ff", "severity": 3, "description": "severe"}

RULE_FAILED = {"kind": "rule", "name": "A1_vs_A2", "stat": "p99_abs", "value": 3099.92, "tol": 42.0,
               "unit": "A", "tag": "check:dcct_mismatch", "missing": [], "ok": False}
RULE_UNTAGGED = {"kind": "rule", "name": "Flow", "stat": "max_abs", "value": 2.5, "tol": 1.0,
                 "unit": "l/s", "tag": None, "missing": [], "ok": False}
RULE_OK = {"kind": "rule", "name": "A3_vs_A4", "stat": "p99_abs", "value": 1.0, "tol": 36.0,
           "unit": "A", "tag": "check:dcct_mismatch", "missing": [], "ok": True}
RULE_NONE = {"kind": "rule", "name": "IH_vs_Icoil7", "stat": "p99_abs", "value": None, "tol": 5.0,
             "unit": "A", "tag": "check:current_mismatch", "missing": ["IH"], "ok": None}
CHANNEL_FAILED = {"kind": "channel", "channel": 2, "fields": {"Tcal2": 14.4}, "ok": False}
VERSION_FAILED = {"kind": "housing_version", "spec": "M8-260305", "data": "M8-230913", "ok": False}
LOAD = {"kind": "load", "reason": "FileFormatError: no data rows", "ok": None}


# ---------------------------------------------------------------------------
# labels and tooltips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value, label", [(None, ""), ("ok", "ok"), ("truncated", "truncated")])
def test_file_integrity_label(value, label):
    assert selectors.file_integrity_label(value) == label


@pytest.mark.parametrize("checks, label", [
    (None, ""),                                   # not checked
    ("[]", ""),                                   # stored as an empty JSON list
    (json.dumps([RULE_OK]), "ok"),
    (json.dumps([RULE_OK, RULE_NONE]), "ok"),     # not evaluated is not a failure
    (json.dumps([RULE_FAILED, CHANNEL_FAILED, RULE_OK]), "2 failed"),
    (json.dumps([LOAD]), "load error"),
    ([RULE_FAILED], "1 failed"),                  # an already parsed list
])
def test_etl_checks_label(checks, label):
    assert selectors.etl_checks_label(checks) == label


def test_file_integrity_tooltip_gives_reason_and_rows():
    tip = selectors.file_integrity_tooltip(
        json.dumps({"rows_read": 209, "rows_dropped": 12, "reason": "corrupt_tail"})
    )
    assert "corrupt_tail" in tip and "209" in tip and "12" in tip
    assert selectors.file_integrity_tooltip(None) == ""


def test_etl_checks_tooltip_lists_failed_and_not_evaluated_checks():
    tip = selectors.etl_checks_tooltip(json.dumps(
        [RULE_FAILED, RULE_UNTAGGED, RULE_OK, RULE_NONE, CHANNEL_FAILED, VERSION_FAILED]
    ))
    assert "A1_vs_A2" in tip and "check:dcct_mismatch" in tip   # tagged rule
    assert "Flow" in tip                                         # untagged rule
    assert "Tcal2" in tip                                        # channel
    assert "M8-260305" in tip                                    # housing version
    assert "IH_vs_Icoil7" in tip and "IH" in tip                 # not evaluated, with missing column
    assert "A3_vs_A4" not in tip                                 # passed: not listed
    assert selectors.etl_checks_tooltip("[]") == ""


def test_etl_checks_tooltip_load_error():
    assert "no data rows" in selectors.etl_checks_tooltip(json.dumps([LOAD]))


# ---------------------------------------------------------------------------
# colour precedence
# ---------------------------------------------------------------------------


def test_flag_unreadable_first():
    flag = selectors.experiment_flag("unreadable", json.dumps([LOAD]), [DCCT])
    assert flag == {"key": "unreadable", "color": selectors.UNREADABLE_COLOR,
                    "column": selectors.FILE_INTEGRITY_COLUMN}


def test_flag_load_error_before_truncated():
    flag = selectors.experiment_flag("truncated", json.dumps([LOAD]), [])
    assert flag == {"key": "load error", "color": selectors.UNREADABLE_COLOR,
                    "column": selectors.ETL_CHECKS_COLUMN}


def test_flag_truncated_before_tags():
    flag = selectors.experiment_flag("truncated", json.dumps([RULE_FAILED]), [DCCT])
    assert flag == {"key": "truncated", "color": selectors.TRUNCATED_COLOR,
                    "column": selectors.FILE_INTEGRITY_COLUMN}


def test_flag_highest_severity_tag():
    flag = selectors.experiment_flag("ok", json.dumps([RULE_FAILED]), [DCCT, SEVERE, CHANNEL])
    assert flag == {"key": "check:severe", "color": "#cfe2ff", "column": selectors.ETL_CHECKS_COLUMN}


def test_flag_same_severity_tags_by_name():
    flag = selectors.experiment_flag("ok", "[]", [DCCT, CHANNEL])
    assert flag["key"] == "check:channel_not_empty"


def test_no_flag_for_a_clean_or_unchecked_file():
    assert selectors.experiment_flag("ok", json.dumps([RULE_OK, RULE_NONE]), []) is None
    assert selectors.experiment_flag(None, None, []) is None


# ---------------------------------------------------------------------------
# experiment table
# ---------------------------------------------------------------------------

_COLUMNS = [{"name": "Experiment", "id": "Experiment", "presentation": "markdown"},
            {"name": "Status", "id": "Status"}]


def _table_df():
    return pd.DataFrame({
        "ID": [1, 2, 3, 4],
        "Experiment": ["[a](/x)", "[b](/x)", "[c](/x)", "[d](/x)"],
        "Status": ["s", "s", "s", "s"],
        "file_integrity": ["ok", "truncated", None, "ok"],
        "file_checks": [None, json.dumps({"rows_read": 9, "rows_dropped": 1, "reason": "corrupt_tail"}),
                        None, None],
        "etl_checks": [json.dumps([RULE_FAILED]), "[]", None, json.dumps([RULE_OK])],
    })


def _table(tags_by_id=None, **kwargs):
    div = selectors.experiment_table(_table_df(), _COLUMNS, tags_by_id or {1: [DCCT]}, **kwargs)
    legend, table = div.children
    assert isinstance(table, DataTable)
    return legend, table


def test_experiment_table_adds_check_columns_and_hides_the_flag():
    _legend, table = _table()
    ids = [c["id"] for c in table.columns]
    assert ids == ["Experiment", "Status", selectors.FILE_INTEGRITY_COLUMN,
                   selectors.ETL_CHECKS_COLUMN, "_flag"]
    assert table.hidden_columns == ["_flag"]
    assert table.cell_selectable is False
    rows = table.data
    assert [r[selectors.FILE_INTEGRITY_COLUMN] for r in rows] == ["ok", "truncated", "", "ok"]
    assert [r[selectors.ETL_CHECKS_COLUMN] for r in rows] == ["1 failed", "", "", "ok"]
    assert [r["_flag"] for r in rows] == ["check:dcct_mismatch", "truncated", "", ""]
    assert not {"file_integrity", "file_checks", "etl_checks"} & set(rows[0])


def test_experiment_table_colours_follow_the_flag_column():
    """Rules key on the hidden flag, not on a row index, so they survive sorting."""
    _legend, table = _table()
    rules = [r for r in table.style_data_conditional if "_flag" in r["if"].get("filter_query", "")]
    assert {(r["if"]["filter_query"], r["if"]["column_id"], r["backgroundColor"]) for r in rules} == {
        ('{_flag} = "check:dcct_mismatch"', "Experiment", "#d1e7dd"),
        ('{_flag} = "check:dcct_mismatch"', selectors.ETL_CHECKS_COLUMN, "#d1e7dd"),
        ('{_flag} = "truncated"', "Experiment", selectors.TRUNCATED_COLOR),
        ('{_flag} = "truncated"', selectors.FILE_INTEGRITY_COLUMN, selectors.TRUNCATED_COLOR),
    }


def test_experiment_table_keeps_extra_style_rules():
    extra = selectors.missing_date_style("Experiment")
    _legend, table = _table(extra_style=extra)
    assert table.style_data_conditional[: len(extra)] == extra


def test_experiment_table_tooltips_per_row():
    _legend, table = _table()
    tips = table.tooltip_data
    assert len(tips) == 4
    assert "check:dcct_mismatch" in tips[0]["Experiment"]["value"]
    assert "A1_vs_A2" in tips[0][selectors.ETL_CHECKS_COLUMN]["value"]
    assert "corrupt_tail" in tips[1][selectors.FILE_INTEGRITY_COLUMN]["value"]
    assert tips[2] == {} and tips[3] == {}


def test_experiment_table_legend_lists_integrity_colours_and_present_tags():
    legend, _table_ = _table(tags_by_id={1: [DCCT], 99: [SEVERE]})  # id 99 not in the table
    text = str(legend)
    assert selectors.TRUNCATED_COLOR in text and selectors.UNREADABLE_COLOR in text
    assert "check:dcct_mismatch" in text
    assert "check:severe" not in text


def test_experiment_table_on_a_db_without_checks():
    df = _table_df().assign(file_integrity=None, file_checks=None, etl_checks=None)
    _legend, table = (lambda d: d.children)(selectors.experiment_table(df, _COLUMNS, {}))
    assert [r["_flag"] for r in table.data] == ["", "", "", ""]
    assert table.tooltip_data == [{}, {}, {}, {}]


# ---------------------------------------------------------------------------
# File viewer: selector labels and note
# ---------------------------------------------------------------------------


def test_file_option_coloured_when_flagged():
    check = {"file_integrity": "ok", "file_checks": None,
             "etl_checks": json.dumps([RULE_FAILED]), "tags": [DCCT]}
    option = selectors.file_option("a.txt", check)
    assert option["value"] == "a.txt" and option["search"] == "a.txt"
    assert option["label"].children == "a.txt"
    assert option["label"].style["backgroundColor"] == "#d1e7dd"


def test_file_option_plain_when_clean_or_unchecked():
    clean = {"file_integrity": "ok", "file_checks": None, "etl_checks": "[]", "tags": []}
    assert selectors.file_option("a.txt", clean) == {"label": "a.txt", "value": "a.txt"}
    assert selectors.file_option("b.txt", None) == {"label": "b.txt", "value": "b.txt"}


def test_file_check_note_lists_integrity_and_checks():
    check = {"file_integrity": "truncated",
             "file_checks": json.dumps({"rows_read": 9, "rows_dropped": 1, "reason": "corrupt_tail"}),
             "etl_checks": json.dumps([RULE_FAILED]), "tags": [DCCT]}
    note = selectors.file_check_note(check)
    assert note.style["backgroundColor"] == selectors.TRUNCATED_COLOR
    text = str(note)
    assert "truncated" in text and "corrupt_tail" in text
    assert "A1_vs_A2" in text and "check:dcct_mismatch" in text


def test_file_check_note_empty_for_a_clean_file():
    clean = {"file_integrity": "ok", "file_checks": None, "etl_checks": json.dumps([RULE_OK]), "tags": []}
    assert selectors.file_check_note(clean) == ""
    assert selectors.file_check_note(None) == ""


# ---------------------------------------------------------------------------
# data access
# ---------------------------------------------------------------------------


def _checks_db(tmp_path, with_checks=True):
    path = tmp_path / "checks.duckdb"
    con = duckdb.connect(str(path))
    extra = ", file_integrity VARCHAR, file_checks JSON, etl_checks JSON" if with_checks else ""
    con.execute(f"CREATE TABLE experiments (id INTEGER, name VARCHAR, file VARCHAR, assembly_name VARCHAR{extra})")
    if with_checks:
        con.execute("INSERT INTO experiments VALUES (1, 'n', 'a.txt', 'M9_A', 'truncated', '{}', '[]'), "
                    "(2, 'n', 'b.txt', 'M9_A', 'ok', NULL, '[]')")
        con.execute("CREATE TABLE tags (name VARCHAR, color VARCHAR, severity INTEGER, description VARCHAR)")
        con.execute("INSERT INTO tags VALUES ('check:dcct_mismatch', '#d1e7dd', 1, 'd'), "
                    "('check:severe', '#cfe2ff', 3, 's')")
        con.execute("CREATE TABLE record_tags (record_table VARCHAR, record_key VARCHAR, tag VARCHAR, "
                    "rule VARCHAR, value DOUBLE, tolerance DOUBLE, tagged_at TIMESTAMP)")
        con.execute("INSERT INTO record_tags VALUES "
                    "('experiments', '2', 'check:dcct_mismatch', 'A1_vs_A2', 50.0, 42.0, now()), "
                    "('experiments', '2', 'check:severe', 'r', 9.0, 1.0, now()), "
                    "('overview_records', 'x', 'check:severe', 'r', 9.0, 1.0, now())")
    else:
        con.execute("INSERT INTO experiments VALUES (1, 'n', 'a.txt', 'M9_A')")
    con.close()
    return str(path)


def test_get_file_tags_by_experiment_id_most_severe_first(tmp_path):
    tags = db.get_file_tags(db_path=_checks_db(tmp_path))
    assert list(tags) == [2]
    assert [t["tag"] for t in tags[2]] == ["check:severe", "check:dcct_mismatch"]
    assert tags[2][1] == {"tag": "check:dcct_mismatch", "rule": "A1_vs_A2", "value": 50.0,
                          "tolerance": 42.0, "color": "#d1e7dd", "severity": 1, "description": "d"}


def test_get_file_tags_empty_on_an_older_db(tmp_path):
    assert db.get_file_tags(db_path=_checks_db(tmp_path, with_checks=False)) == {}


@pytest.mark.parametrize("with_checks", [True, False])
def test_experiment_check_columns_sql(tmp_path, with_checks):
    with duckdb.connect(_checks_db(tmp_path, with_checks), read_only=True) as con:
        sql = db.experiment_check_columns_sql(con)
        row = con.execute(f"SELECT {sql} FROM experiments AS e ORDER BY e.id").fetchone()
        agg = db.experiment_check_columns_sql(con, aggregate=True)
        con.execute(f"SELECT e.id, {agg} FROM experiments AS e GROUP BY e.id").fetchall()
    assert row == (("truncated", "{}", "[]") if with_checks else (None, None, None))


def test_get_file_checks_for_assembly(tmp_path):
    checks = db.get_file_checks_for_assembly("M9_A", db_path=_checks_db(tmp_path))
    assert checks["a.txt"]["file_integrity"] == "truncated"
    assert [t["tag"] for t in checks["b.txt"]["tags"]] == ["check:severe", "check:dcct_mismatch"]
    assert checks["a.txt"]["tags"] == []
