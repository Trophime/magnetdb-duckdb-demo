import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_analysis as db


def test_order_groups_listed_groups_win_in_config_order(monkeypatch):
    monkeypatch.setattr(db, "_GROUP_ORDER", ["Field", "Alimentations"])
    assert db.order_groups(["Alimentations", "Field"]) == ["Field", "Alimentations"]


def test_order_groups_unlisted_groups_keep_relative_order_and_land_after(monkeypatch):
    monkeypatch.setattr(db, "_GROUP_ORDER", ["Field"])
    assert db.order_groups(["Zeta", "Field", "Alpha"]) == ["Field", "Zeta", "Alpha"]


def test_order_groups_empty_config_is_a_noop(monkeypatch):
    monkeypatch.setattr(db, "_GROUP_ORDER", [])
    assert db.order_groups(["Zeta", "Alpha", "Field"]) == ["Zeta", "Alpha", "Field"]
