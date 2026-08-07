"""Tests for compute_hoop_stats.py (orchestration in compute_hoop_stress_history()
is covered separately — see follow-up)."""

import json

import pandas as pd
import pyarrow.parquet as pq
import pytest

from compute_hoop_stats import (
    _bin_series,
    _check_processed,
    _column_meta,
    _compute_dt,
    _get_experiments,
    _insert_bin_stats,
    _insert_fatigue,
    _mark_processed,
    _merge_configs,
    _parse_bins,
    _rainflow_stats,
    bins_to_key,
    build_part_column_map,
    save_hoop_parquet,
)
from crud import (
    insert_experiments,
    insert_magnet,
    insert_magnet_part_row,
    insert_part,
    insert_site,
    insert_site_magnets,
)

# ---------------------------------------------------------------------------
# bins_to_key / _parse_bins
# ---------------------------------------------------------------------------


def test_bins_to_key():
    bins = [(0.0, 100.0), (100.0, 200.0), (200.0, 300.0)]
    assert bins_to_key(bins) == "0.0,100.0,200.0,300.0"


def test_parse_bins_edges_format():
    assert _parse_bins("0,100,200,300") == [
        (0.0, 100.0), (100.0, 200.0), (200.0, 300.0),
    ]


def test_parse_bins_legacy_pair_format():
    assert _parse_bins("0:100,100:200") == [(0.0, 100.0), (100.0, 200.0)]


def test_parse_bins_requires_at_least_two_edges():
    with pytest.raises(ValueError):
        _parse_bins("100")


# ---------------------------------------------------------------------------
# build_part_column_map
# ---------------------------------------------------------------------------


@pytest.fixture
def hoop_site(con):
    """HOOP_SITE with two insert magnets (MAG_NEW, MAG_OLD) and one bitters
    magnet (MAG_B). Exercises rank ordering, commissioned_at DESC ordering
    across same-type magnets, and exclusion of non-coil parts (RING_NEW).
    """
    insert_part(con, {"name": "H_NEW", "type": "helix"}, verbose=False)
    insert_part(con, {"name": "RING_NEW", "type": "ring"}, verbose=False)
    insert_part(con, {"name": "H_OLD", "type": "helix"}, verbose=False)
    insert_part(con, {"name": "B_ONE", "type": "bitter"}, verbose=False)

    insert_magnet(con, {"name": "MAG_NEW"}, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_NEW", "H_NEW", 0, 1)
    insert_magnet_part_row(con, "MAG_NEW", "RING_NEW", 1, None)

    insert_magnet(con, {"name": "MAG_OLD"}, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_OLD", "H_OLD", 0, 1)

    insert_magnet(con, {"name": "MAG_B"}, "bitters", verbose=False)
    insert_magnet_part_row(con, "MAG_B", "B_ONE", 0, 1)

    insert_site(con, {"name": "HOOP_SITE", "status": "in_operation"}, verbose=False)
    insert_site_magnets(
        con, "HOOP_SITE",
        [
            {"name": "MAG_NEW", "commissioned_at": "2025-06-01 00:00:00"},
            {"name": "MAG_OLD", "commissioned_at": "2025-01-01 00:00:00"},
            {"name": "MAG_B", "commissioned_at": "2025-03-01 00:00:00"},
        ],
        verbose=False,
    )
    return con


def test_build_part_column_map_orders_by_commissioned_at_desc_then_rank(hoop_site):
    mapping = build_part_column_map("HOOP_SITE", "", con=hoop_site)
    assert mapping == {
        "H1_fast": "H_NEW",
        "H2_fast": "H_OLD",
        "B1_fast": "B_ONE",
    }


def test_build_part_column_map_excludes_non_coil_parts(hoop_site):
    mapping = build_part_column_map("HOOP_SITE", "", con=hoop_site)
    assert "RING_NEW" not in mapping.values()


# ---------------------------------------------------------------------------
# _column_meta
# ---------------------------------------------------------------------------


def test_column_meta_helix():
    meta = _column_meta("H1_fast")
    assert meta[b"unit"] == b"MPa"
    assert meta[b"symbol"].decode() == "σ_H1"


def test_column_meta_bitter():
    meta = _column_meta("B2_fast")
    assert meta[b"symbol"].decode() == "σ_B2"


def test_column_meta_supra():
    meta = _column_meta("Supra3_fast")
    assert meta[b"symbol"].decode() == "σ_S3"


def test_column_meta_unmatched_returns_empty():
    assert _column_meta("IH") == {}
    assert _column_meta("t") == {}


# ---------------------------------------------------------------------------
# save_hoop_parquet
# ---------------------------------------------------------------------------


def test_save_hoop_parquet_round_trip(tmp_path):
    df = pd.DataFrame({"t": [0.0, 1.0, 2.0], "H1_fast": [10.0, 20.0, 30.0]})
    path = tmp_path / "exp.parquet"

    save_hoop_parquet(
        df, path,
        site_name="HOOP_SITE",
        housing="M9",
        t0="2025-01-01T00:00:00",
        experiment_file="exp.txt",
        part_map={"H1_fast": "H_NEW"},
    )

    table = pq.read_table(path)
    meta = table.schema.metadata
    assert meta[b"site_name"] == b"HOOP_SITE"
    assert meta[b"housing"] == b"M9"
    assert meta[b"t0"] == b"2025-01-01T00:00:00"
    assert json.loads(meta[b"part_map"]) == {"H1_fast": "H_NEW"}

    field = table.schema.field("H1_fast")
    assert field.metadata[b"unit"] == b"MPa"
    assert field.metadata[b"symbol"].decode() == "σ_H1"
    assert table.column("t").to_pylist() == [0.0, 1.0, 2.0]


# ---------------------------------------------------------------------------
# _bin_series
# ---------------------------------------------------------------------------


def test_bin_series_buckets_by_stress_and_accumulates_dt():
    sigma = pd.Series([10.0, 50.0, 150.0, 250.0])
    dt = pd.Series([1.0, 2.0, 3.0, 4.0])
    bins = [(0.0, 100.0), (100.0, 200.0), (200.0, 300.0)]

    rows = {(r["stress_bin_low"], r["stress_bin_high"]): r for r in _bin_series(sigma, dt, bins)}

    low = rows[(0.0, 100.0)]
    assert low["n_samples"] == 2
    assert low["sum_dt"] == 3.0
    assert low["sum_x_dt"] == pytest.approx(10.0 * 1.0 + 50.0 * 2.0)
    assert low["min_x"] == 10.0
    assert low["max_x"] == 50.0
    assert rows[(100.0, 200.0)]["n_samples"] == 1
    assert rows[(200.0, 300.0)]["n_samples"] == 1


def test_bin_series_omits_empty_bins():
    sigma = pd.Series([10.0])
    dt = pd.Series([1.0])
    bins = [(0.0, 100.0), (100.0, 200.0)]

    rows = _bin_series(sigma, dt, bins)

    assert len(rows) == 1
    assert rows[0]["stress_bin_low"] == 0.0


# ---------------------------------------------------------------------------
# _rainflow_stats
# ---------------------------------------------------------------------------


def test_rainflow_stats_constant_series_has_zero_range():
    # A flat series still yields one zero-range residual half-cycle from the
    # rainflow algorithm — n_cycles is nonzero, but sum_range3 stays 0 since
    # range**3 == 0.
    stats = _rainflow_stats(pd.Series([5.0] * 10))
    assert stats["sum_range3"] == 0.0


def test_rainflow_stats_matches_manual_aggregation():
    rainflow = pytest.importorskip("rainflow")
    sigma = pd.Series([0.0, 10.0, 0.0, 15.0, 0.0, 10.0, 0.0])

    stats = _rainflow_stats(sigma)

    cycles = list(rainflow.count_cycles(sigma.to_numpy().astype(float)))
    expected_n = sum(count for _rng, count in cycles)
    expected_sum_range3 = sum(count * float(rng) ** 3 for rng, count in cycles)
    assert stats["n_cycles"] == pytest.approx(expected_n)
    assert stats["sum_range3"] == pytest.approx(expected_sum_range3)


# ---------------------------------------------------------------------------
# _compute_dt
# ---------------------------------------------------------------------------


def test_compute_dt_with_t_column_clips_negative_diffs():
    df = pd.DataFrame({"t": [0.0, 1.0, 3.0, 2.0]})
    assert _compute_dt(df).tolist() == [0.0, 1.0, 2.0, 0.0]


def test_compute_dt_without_t_column_defaults_to_one():
    df = pd.DataFrame({"x": [1, 2, 3]})
    assert _compute_dt(df).tolist() == [1.0, 1.0, 1.0]


# ---------------------------------------------------------------------------
# _merge_configs
# ---------------------------------------------------------------------------


def test_merge_configs_concatenates_list_values():
    configs = [
        ("MAG_A", {"Helices": ["H1"]}, None),
        ("MAG_B", {"Helices": ["H2"], "BMagnets": ["B1"]}, None),
    ]
    merged = _merge_configs(configs)
    assert merged["Helices"] == ["H1", "H2"]
    assert merged["BMagnets"] == ["B1"]


def test_merge_configs_last_scalar_wins():
    configs = [("A", {"tag": "first"}, None), ("B", {"tag": "second"}, None)]
    assert _merge_configs(configs)["tag"] == "second"


# ---------------------------------------------------------------------------
# DB round-trip helpers: _get_experiments, _check_processed/_mark_processed,
# _insert_bin_stats/_insert_fatigue
# ---------------------------------------------------------------------------


@pytest.fixture
def hoop_site_with_experiments(hoop_site):
    insert_experiments(
        hoop_site, "HOOP_SITE",
        [
            {"name": "exp1", "file": "exp1.txt"},
            {"name": "exp2", "file": "exp2.txt"},
        ],
        verbose=False,
    )
    return hoop_site


def test_get_experiments_returns_rows_ordered_by_id(hoop_site_with_experiments):
    df = _get_experiments(hoop_site_with_experiments, "HOOP_SITE")
    assert df["name"].tolist() == ["exp1", "exp2"]
    assert set(df.columns) == {"id", "name", "file"}


def test_check_processed_and_mark_processed_round_trip(hoop_site_with_experiments):
    con = hoop_site_with_experiments
    exp_id = int(_get_experiments(con, "HOOP_SITE").iloc[0]["id"])
    bin_key = "0.0,100.0,200.0"

    done, others = _check_processed(con, exp_id, bin_key)
    assert done is False
    assert others == set()

    _mark_processed(con, exp_id, "all", bin_key, "/tmp/exp.parquet")

    done, others = _check_processed(con, exp_id, bin_key)
    assert done is True
    assert others == set()

    other_key = "0.0,150.0,300.0"
    done, others = _check_processed(con, exp_id, other_key)
    assert done is False
    assert others == {bin_key}


def test_insert_bin_stats_and_fatigue_round_trip(hoop_site_with_experiments):
    con = hoop_site_with_experiments
    exp_id = int(_get_experiments(con, "HOOP_SITE").iloc[0]["id"])

    rows = [{
        "stress_bin_low": 0.0, "stress_bin_high": 100.0, "n_samples": 2,
        "sum_dt": 3.0, "sum_x_dt": 60.0, "sum_x2_dt": 1400.0,
        "min_x": 10.0, "max_x": 50.0,
    }]
    _insert_bin_stats(con, exp_id, "H_NEW", rows)
    stored = con.execute(
        "SELECT part_name, n_samples, sum_dt FROM hoop_stress_bin_stats WHERE experiment_id = ?",
        [exp_id],
    ).fetchall()
    assert stored == [("H_NEW", 2, 3.0)]

    # INSERT OR REPLACE on the same (experiment_id, part_name, stress_bin_low)
    # key overwrites rather than duplicates.
    rows[0]["n_samples"] = 5
    _insert_bin_stats(con, exp_id, "H_NEW", rows)
    stored = con.execute(
        "SELECT n_samples FROM hoop_stress_bin_stats WHERE experiment_id = ?", [exp_id]
    ).fetchall()
    assert stored == [(5,)]

    _insert_fatigue(con, exp_id, "H_NEW", {"n_cycles": 4.0, "sum_range3": 123.0})
    fatigue = con.execute(
        "SELECT n_cycles, sum_range3 FROM hoop_stress_fatigue "
        "WHERE experiment_id = ? AND part_name = ?",
        [exp_id, "H_NEW"],
    ).fetchone()
    assert fatigue == (4.0, 123.0)
