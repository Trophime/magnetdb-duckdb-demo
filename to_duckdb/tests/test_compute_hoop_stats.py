"""Tests for compute_hoop_stats.py."""

import json

import duckdb
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
    _parse_bins,
    _rainflow_stats,
    bins_to_key,
    build_part_column_map,
    compute_hoop_stress_history,
    resolve_z0_by_type,
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
from schema import ensure_schema

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


def _build_hoop_site(con):
    """Populate HOOP_SITE with two insert magnets (MAG_NEW, MAG_OLD) and one
    bitters magnet (MAG_B). Exercises rank ordering, commissioned_at DESC
    ordering across same-type magnets, and exclusion of non-coil parts
    (RING_NEW).
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


@pytest.fixture
def hoop_site(con):
    """HOOP_SITE with two insert magnets (MAG_NEW, MAG_OLD) and one bitters
    magnet (MAG_B). Exercises rank ordering, commissioned_at DESC ordering
    across same-type magnets, and exclusion of non-coil parts (RING_NEW).
    """
    _build_hoop_site(con)
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
# resolve_z0_by_type
# ---------------------------------------------------------------------------


def test_resolve_z0_by_type_defaults_to_zero(hoop_site):
    z0_h, z0_b = resolve_z0_by_type("HOOP_SITE", "", con=hoop_site)

    assert z0_h == [0.0, 0.0]  # H1_fast -> H_NEW, H2_fast -> H_OLD
    assert z0_b == [0.0]       # B1_fast -> B_ONE


def test_resolve_z0_by_type_reflects_site_magnets_z_offset(con):
    insert_part(con, {"name": "H_NEW", "type": "helix"}, verbose=False)
    insert_part(con, {"name": "H_OLD", "type": "helix"}, verbose=False)
    insert_part(con, {"name": "B_ONE", "type": "bitter"}, verbose=False)
    insert_magnet(con, {"name": "MAG_NEW"}, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_NEW", "H_NEW", 0, 1)
    insert_magnet(con, {"name": "MAG_OLD"}, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_OLD", "H_OLD", 0, 1)
    insert_magnet(con, {"name": "MAG_B"}, "bitters", verbose=False)
    insert_magnet_part_row(con, "MAG_B", "B_ONE", 0, 1)
    insert_site(con, {"name": "HOOP_SITE", "status": "in_operation"}, verbose=False)
    insert_site_magnets(
        con, "HOOP_SITE",
        [
            {"name": "MAG_NEW", "commissioned_at": "2025-06-01 00:00:00", "z_offset": 0.05},
            {"name": "MAG_OLD", "commissioned_at": "2025-01-01 00:00:00"},
            {"name": "MAG_B", "commissioned_at": "2025-03-01 00:00:00"},
        ],
        verbose=False,
    )

    z0_h, z0_b = resolve_z0_by_type("HOOP_SITE", "", con=con)

    # H1_fast -> H_NEW (MAG_NEW, commissioned_at DESC puts it first) -> 0.05
    # H2_fast -> H_OLD (MAG_OLD, no z_offset given) -> default 0.0
    assert z0_h == [0.05, 0.0]
    assert z0_b == [0.0]


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
    # Column is already renamed to the part name, as the real caller
    # (compute_hoop_stress_history) does before calling save_hoop_parquet.
    df = pd.DataFrame({"t": [0.0, 1.0, 2.0], "H_NEW": [10.0, 20.0, 30.0]})
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

    assert "H1_fast" not in table.schema.names
    field = table.schema.field("H_NEW")
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


# ---------------------------------------------------------------------------
# compute_hoop_stress_history() — orchestration
#
# compute_hoop_stress_history() opens its own DuckDB connection internally
# (duckdb.connect(db_path)); a second, independent `:memory:` connection does
# not see that state, so these tests use a file-backed DB under tmp_path
# instead of the `con`/`hoop_site` fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def hoop_db_path(tmp_path):
    """File-backed HOOP_SITE + 2 experiments (exp1, exp2)."""
    db_path = tmp_path / "hoop_orch.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    _build_hoop_site(con)
    insert_experiments(
        con, "HOOP_SITE",
        [
            {"name": "exp1", "file": "exp1.txt"},
            {"name": "exp2", "file": "exp2.txt"},
        ],
        verbose=False,
    )
    con.close()
    return str(db_path)


@pytest.fixture
def patched_hoop_pipeline(monkeypatch, tmp_path):
    """Fake the 4 stress_map functions compute_hoop_stress_history() imports
    locally, matching the corrected (site-level, not per-magnet)
    prepare_geometry_directory call shape — a regression to the old
    per-magnet/``geometry_data=`` call raises TypeError here exactly as it
    would against the real function.

    Returns the geometry directory the fake creates, so tests can assert it
    gets cleaned up by compute_hoop_stress_history()'s `finally` block, and
    a call counter to assert prepare_geometry_directory runs once per site,
    not once per magnet.
    """
    geom_dir = tmp_path / "geom_out"
    calls = {"prepare_geometry_directory": 0}

    def fake_load_site_config_from_duckdb(site_name, db_path, con=None):
        return "M9", [
            ("MAG_NEW", {"geom": "MAG_NEW.yaml"}, None),
            ("MAG_OLD", {"geom": "MAG_OLD.yaml"}, None),
            ("MAG_B", {"geom": "MAG_B.yaml"}, None),
        ]

    def fake_prepare_geometry_directory(site_name, config, db_path, geometries_dir=None, con=None):
        calls["prepare_geometry_directory"] += 1
        assert site_name == "HOOP_SITE"
        assert con is not None  # compute_hoop_stress_history must reuse its own connection
        assert isinstance(config, dict) and set(config) == {"name", "magnets"}
        assert len(config["magnets"]) == 3
        geom_dir.mkdir(exist_ok=True)
        return geom_dir

    def fake_load_magnettools(config, tempdir, debug=False):
        return "FAKE_MAGNETTOOLS_DATA"

    monkeypatch.setattr("stress_map.load_site_config_from_duckdb", fake_load_site_config_from_duckdb)
    monkeypatch.setattr("stress_map.prepare_geometry_directory", fake_prepare_geometry_directory)
    monkeypatch.setattr("stress_map.load_magnettools", fake_load_magnettools)
    return geom_dir, calls


def test_compute_hoop_stress_history_full_run(patched_hoop_pipeline, hoop_db_path, monkeypatch, tmp_path):
    geom_dir, calls = patched_hoop_pipeline

    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, site=None, z0_h=None, z0_b=None):
        return pd.DataFrame({"t": [0.0, 1.0, 2.0, 3.0], "H1_fast": [10.0, 60.0, 20.0, 80.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)

    pq_dir = tmp_path / "pq"
    results = compute_hoop_stress_history(
        "HOOP_SITE", hoop_db_path, parquet_dir=str(pq_dir), verbose=False,
    )

    assert results == {"new": 2, "skipped": 0, "errors": []}
    assert calls["prepare_geometry_directory"] == 1
    assert not geom_dir.exists()  # cleaned up by the `finally: shutil.rmtree(...)`
    assert (pq_dir / "exp1.parquet").exists()
    assert (pq_dir / "exp2.parquet").exists()

    # Parquet columns are renamed to part names (H1_fast -> H_NEW), not slot names.
    written = pq.read_table(pq_dir / "exp1.parquet")
    assert "H_NEW" in written.schema.names
    assert "H1_fast" not in written.schema.names

    con = duckdb.connect(hoop_db_path, read_only=True)
    try:
        processed = con.execute(
            "SELECT experiment_id, magnet_type FROM hoop_stress_processed ORDER BY experiment_id"
        ).fetchall()
        assert len(processed) == 2
        assert all(magnet_type == "all" for _exp_id, magnet_type in processed)

        # H1_fast -> H_NEW (commissioned_at DESC: MAG_NEW is newest, rank 0 helix).
        bin_rows = con.execute(
            "SELECT n_samples, sum_dt, sum_x_dt, min_x, max_x FROM hoop_stress_bin_stats "
            "WHERE part_name = 'H_NEW' ORDER BY experiment_id"
        ).fetchall()
        assert len(bin_rows) == 2
        # sigma=[10,60,20,80], dt=diff([0,1,2,3]).clip(lower=0)=[0,1,1,1] -> all in bin (0,100)
        assert bin_rows[0] == (4, 3.0, pytest.approx(160.0), 10.0, 80.0)

        fatigue_rows = con.execute(
            "SELECT part_name FROM hoop_stress_fatigue WHERE part_name = 'H_NEW'"
        ).fetchall()
        assert len(fatigue_rows) == 2

        # Only H1_fast was in the synthetic DataFrame -> no rows for the other parts.
        other_parts = con.execute(
            "SELECT DISTINCT part_name FROM hoop_stress_bin_stats"
        ).fetchall()
        assert other_parts == [("H_NEW",)]
    finally:
        con.close()


def test_compute_hoop_stress_history_geometry_prep_failure_aborts(hoop_db_path, monkeypatch):
    def fake_load_site_config_from_duckdb(site_name, db_path, con=None):
        return "M9", [("MAG_NEW", {"geom": "MAG_NEW.yaml"}, None)]

    def fake_prepare_geometry_directory(site_name, config, db_path, geometries_dir=None, con=None):
        raise RuntimeError("geometry boom")

    monkeypatch.setattr("stress_map.load_site_config_from_duckdb", fake_load_site_config_from_duckdb)
    monkeypatch.setattr("stress_map.prepare_geometry_directory", fake_prepare_geometry_directory)

    results = compute_hoop_stress_history("HOOP_SITE", hoop_db_path, verbose=False)

    assert results == {"new": 0, "skipped": 0, "errors": ["geometry boom"]}


def test_compute_hoop_stress_history_skips_already_processed_unless_reprocess(
    patched_hoop_pipeline, hoop_db_path, monkeypatch, tmp_path
):
    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, site=None, z0_h=None, z0_b=None):
        return pd.DataFrame({"t": [0.0, 1.0], "H1_fast": [10.0, 20.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)
    pq_dir = str(tmp_path / "pq")

    r1 = compute_hoop_stress_history("HOOP_SITE", hoop_db_path, parquet_dir=pq_dir, verbose=False)
    assert r1["new"] == 2 and r1["skipped"] == 0

    r2 = compute_hoop_stress_history("HOOP_SITE", hoop_db_path, parquet_dir=pq_dir, verbose=False)
    assert r2["new"] == 0 and r2["skipped"] == 2

    con = duckdb.connect(hoop_db_path, read_only=True)
    try:
        n_rows = con.execute("SELECT COUNT(*) FROM hoop_stress_processed").fetchone()[0]
        assert n_rows == 2  # not duplicated by the re-run
    finally:
        con.close()

    r3 = compute_hoop_stress_history(
        "HOOP_SITE", hoop_db_path, parquet_dir=pq_dir, reprocess=True, verbose=False,
    )
    assert r3["new"] == 2 and r3["skipped"] == 0


def test_compute_hoop_stress_history_dry_run_writes_nothing(
    patched_hoop_pipeline, hoop_db_path, monkeypatch, tmp_path
):
    def fake_validate(*args, **kwargs):
        raise AssertionError("validate_fast_from_pupitre must not run under dry_run")

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)
    pq_dir = tmp_path / "pq"

    results = compute_hoop_stress_history(
        "HOOP_SITE", hoop_db_path, parquet_dir=str(pq_dir), dry_run=True, verbose=False,
    )

    assert results == {"new": 2, "skipped": 0, "errors": []}
    assert not pq_dir.exists()

    con = duckdb.connect(hoop_db_path, read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM hoop_stress_processed").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM hoop_stress_bin_stats").fetchone()[0] == 0
    finally:
        con.close()


def test_compute_hoop_stress_history_different_bin_config_warns_and_reprocesses(
    patched_hoop_pipeline, hoop_db_path, monkeypatch, tmp_path, capsys
):
    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, site=None, z0_h=None, z0_b=None):
        return pd.DataFrame({"t": [0.0, 1.0], "H1_fast": [10.0, 20.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)
    pq_dir = str(tmp_path / "pq")

    r1 = compute_hoop_stress_history("HOOP_SITE", hoop_db_path, parquet_dir=pq_dir, verbose=False)
    assert r1["new"] == 2
    capsys.readouterr()  # discard first-run output

    r2 = compute_hoop_stress_history(
        "HOOP_SITE", hoop_db_path, parquet_dir=pq_dir,
        bins=[(0.0, 50.0), (50.0, 150.0)], verbose=False,
    )
    captured = capsys.readouterr()

    assert "previously processed with" in captured.out
    assert r2["new"] == 2  # not skipped -- computed under the new bin_key too
    assert r2["skipped"] == 0

    con = duckdb.connect(hoop_db_path, read_only=True)
    try:
        n_configs = con.execute(
            "SELECT COUNT(DISTINCT bin_config) FROM hoop_stress_processed"
        ).fetchone()[0]
        assert n_configs == 2
    finally:
        con.close()


def test_compute_hoop_stress_history_continues_after_one_experiment_errors(
    patched_hoop_pipeline, hoop_db_path, monkeypatch, tmp_path
):
    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, site=None, z0_h=None, z0_b=None):
        if "exp1" in exp_file:
            raise RuntimeError("boom")
        return pd.DataFrame({"t": [0.0, 1.0], "H1_fast": [10.0, 20.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)

    results = compute_hoop_stress_history(
        "HOOP_SITE", hoop_db_path, parquet_dir=str(tmp_path / "pq"), verbose=False,
    )

    assert results["new"] == 1
    assert len(results["errors"]) == 1
    assert results["errors"][0] == ("exp1", "boom")

    con = duckdb.connect(hoop_db_path, read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM hoop_stress_processed").fetchone()[0] == 1
    finally:
        con.close()


def test_compute_hoop_stress_history_skips_experiment_with_no_hoop_columns(
    patched_hoop_pipeline, hoop_db_path, monkeypatch, tmp_path
):
    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, site=None, z0_h=None, z0_b=None):
        return pd.DataFrame({"t": [0.0, 1.0], "IH": [100.0, 200.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)

    results = compute_hoop_stress_history(
        "HOOP_SITE", hoop_db_path, parquet_dir=str(tmp_path / "pq"), verbose=False,
    )

    assert results["new"] == 0
    assert len(results["errors"]) == 2
    assert all(msg == "no hoop columns" for _name, msg in results["errors"])
