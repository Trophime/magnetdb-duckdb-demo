"""Tests for compute_hoop_stats.py."""

import json

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import pytest

from compute_hoop_stats import (
    _bin_rainflow_cycles,
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
    build_part_history_series,
    compute_hoop_stress_history,
    part_history_stats,
    resolve_z0_by_type,
    save_hoop_parquet,
)
from crud import (
    insert_experiments,
    insert_magnet,
    insert_magnet_part_row,
    insert_part,
    insert_assembly,
    insert_assembly_magnets,
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


def _build_hoop_assembly(con):
    """Populate HOOP_ASSEMBLY with two insert magnets (MAG_NEW, MAG_OLD) and one
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

    insert_assembly(con, {"name": "HOOP_ASSEMBLY", "status": "in_operation"}, verbose=False)
    insert_assembly_magnets(
        con, "HOOP_ASSEMBLY",
        [
            {"name": "MAG_NEW", "commissioned_at": "2025-06-01 00:00:00"},
            {"name": "MAG_OLD", "commissioned_at": "2025-01-01 00:00:00"},
            {"name": "MAG_B", "commissioned_at": "2025-03-01 00:00:00"},
        ],
        verbose=False,
    )


@pytest.fixture
def hoop_assembly(con):
    """HOOP_ASSEMBLY with two insert magnets (MAG_NEW, MAG_OLD) and one bitters
    magnet (MAG_B). Exercises rank ordering, commissioned_at DESC ordering
    across same-type magnets, and exclusion of non-coil parts (RING_NEW).
    """
    _build_hoop_assembly(con)
    return con


def test_build_part_column_map_orders_by_commissioned_at_desc_then_rank(hoop_assembly):
    mapping = build_part_column_map("HOOP_ASSEMBLY", "", con=hoop_assembly)
    assert mapping == {
        "H1_fast": "H_NEW",
        "H2_fast": "H_OLD",
        "B1_fast": "B_ONE",
    }


def test_build_part_column_map_excludes_non_coil_parts(hoop_assembly):
    mapping = build_part_column_map("HOOP_ASSEMBLY", "", con=hoop_assembly)
    assert "RING_NEW" not in mapping.values()


# ---------------------------------------------------------------------------
# resolve_z0_by_type
# ---------------------------------------------------------------------------


def test_resolve_z0_by_type_defaults_to_zero(hoop_assembly):
    z0_h, z0_b = resolve_z0_by_type("HOOP_ASSEMBLY", "", con=hoop_assembly)

    assert z0_h == [0.0, 0.0]  # H1_fast -> H_NEW, H2_fast -> H_OLD
    assert z0_b == [0.0]       # B1_fast -> B_ONE


def test_resolve_z0_by_type_reflects_assembly_magnets_z_offset(con):
    insert_part(con, {"name": "H_NEW", "type": "helix"}, verbose=False)
    insert_part(con, {"name": "H_OLD", "type": "helix"}, verbose=False)
    insert_part(con, {"name": "B_ONE", "type": "bitter"}, verbose=False)
    insert_magnet(con, {"name": "MAG_NEW"}, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_NEW", "H_NEW", 0, 1)
    insert_magnet(con, {"name": "MAG_OLD"}, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_OLD", "H_OLD", 0, 1)
    insert_magnet(con, {"name": "MAG_B"}, "bitters", verbose=False)
    insert_magnet_part_row(con, "MAG_B", "B_ONE", 0, 1)
    insert_assembly(con, {"name": "HOOP_ASSEMBLY", "status": "in_operation"}, verbose=False)
    insert_assembly_magnets(
        con, "HOOP_ASSEMBLY",
        [
            {"name": "MAG_NEW", "commissioned_at": "2025-06-01 00:00:00", "z_offset": 0.05},
            {"name": "MAG_OLD", "commissioned_at": "2025-01-01 00:00:00"},
            {"name": "MAG_B", "commissioned_at": "2025-03-01 00:00:00"},
        ],
        verbose=False,
    )

    z0_h, z0_b = resolve_z0_by_type("HOOP_ASSEMBLY", "", con=con)

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
        assembly_name="HOOP_ASSEMBLY",
        housing="M9",
        t0="2025-01-01T00:00:00",
        experiment_file="exp.txt",
        part_map={"H1_fast": "H_NEW"},
    )

    table = pq.read_table(path)
    meta = table.schema.metadata
    assert meta[b"assembly_name"] == b"HOOP_ASSEMBLY"
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


def test_rainflow_stats_matrix_counts_sum_to_n_cycles():
    sigma = pd.Series([0.0, 10.0, 0.0, 15.0, 0.0, 10.0, 0.0])
    bins = [(0.0, 5.0), (5.0, 10.0), (10.0, 15.0), (15.0, 20.0)]

    stats = _rainflow_stats(sigma, bins)

    matrix_total = sum(row["count"] for row in stats["matrix"])
    assert matrix_total == pytest.approx(stats["n_cycles"])


def test_rainflow_stats_matrix_empty_for_constant_series():
    # The one zero-range residual half-cycle from a flat series still lands
    # in the (0, bin_size) x (value, value+bin_size) cell -- matrix is not
    # empty, but every row's range is the bottom bin.
    stats = _rainflow_stats(pd.Series([5.0] * 10), bins=[(0.0, 100.0)])
    assert all(row["range_bin_low"] == 0.0 for row in stats["matrix"])


# ---------------------------------------------------------------------------
# _bin_rainflow_cycles
# ---------------------------------------------------------------------------


def test_bin_rainflow_cycles_buckets_by_range_and_mean():
    cycles_df = pd.DataFrame({
        "range": [5.0, 5.0, 25.0],
        "mean":  [2.0, 2.0, 12.0],
        "count": [1.0, 0.5, 1.0],
    })
    bins = [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)]

    rows = _bin_rainflow_cycles(cycles_df, bins)

    assert len(rows) == 2
    small = next(r for r in rows if r["range_bin_low"] == 0.0)
    assert small["mean_bin_low"] == 0.0
    assert small["count"] == pytest.approx(1.5)
    big = next(r for r in rows if r["range_bin_low"] == 20.0)
    assert big["mean_bin_low"] == 10.0
    assert big["count"] == pytest.approx(1.0)


def test_bin_rainflow_cycles_drops_out_of_range_cycles():
    cycles_df = pd.DataFrame({"range": [500.0], "mean": [5.0], "count": [1.0]})
    bins = [(0.0, 10.0)]

    assert _bin_rainflow_cycles(cycles_df, bins) == []


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
def hoop_assembly_with_experiments(hoop_assembly):
    insert_experiments(
        hoop_assembly, "HOOP_ASSEMBLY",
        [
            {"name": "exp1", "file": "exp1.txt"},
            {"name": "exp2", "file": "exp2.txt"},
        ],
        verbose=False,
    )
    return hoop_assembly


def test_get_experiments_returns_rows_ordered_by_id(hoop_assembly_with_experiments):
    df = _get_experiments(hoop_assembly_with_experiments, "HOOP_ASSEMBLY")
    assert df["name"].tolist() == ["exp1", "exp2"]
    assert set(df.columns) == {"id", "name", "file"}


def test_check_processed_and_mark_processed_round_trip(hoop_assembly_with_experiments):
    con = hoop_assembly_with_experiments
    exp_id = int(_get_experiments(con, "HOOP_ASSEMBLY").iloc[0]["id"])
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


def test_insert_bin_stats_and_fatigue_round_trip(hoop_assembly_with_experiments):
    con = hoop_assembly_with_experiments
    exp_id = int(_get_experiments(con, "HOOP_ASSEMBLY").iloc[0]["id"])

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


def test_insert_fatigue_writes_matrix_rows(hoop_assembly_with_experiments):
    con = hoop_assembly_with_experiments
    exp_id = int(_get_experiments(con, "HOOP_ASSEMBLY").iloc[0]["id"])

    matrix = [
        {"range_bin_low": 0.0, "range_bin_high": 100.0,
         "mean_bin_low": 0.0, "mean_bin_high": 100.0, "count": 2.0},
    ]
    _insert_fatigue(con, exp_id, "H_NEW", {"n_cycles": 2.0, "sum_range3": 1.0, "matrix": matrix})
    stored = con.execute(
        "SELECT range_bin_low, mean_bin_low, count FROM hoop_stress_fatigue_bins "
        "WHERE experiment_id = ? AND part_name = ?",
        [exp_id, "H_NEW"],
    ).fetchall()
    assert stored == [(0.0, 0.0, 2.0)]

    # INSERT OR REPLACE on the same key overwrites rather than duplicates.
    matrix[0]["count"] = 5.0
    _insert_fatigue(con, exp_id, "H_NEW", {"n_cycles": 5.0, "sum_range3": 1.0, "matrix": matrix})
    stored = con.execute(
        "SELECT count FROM hoop_stress_fatigue_bins WHERE experiment_id = ? AND part_name = ?",
        [exp_id, "H_NEW"],
    ).fetchall()
    assert stored == [(5.0,)]


# ---------------------------------------------------------------------------
# compute_hoop_stress_history() — orchestration
#
# compute_hoop_stress_history() opens its own DuckDB connection internally
# (duckdb.connect(db_path)); a second, independent `:memory:` connection does
# not see that state, so these tests use a file-backed DB under tmp_path
# instead of the `con`/`hoop_assembly` fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def hoop_db_path(tmp_path):
    """File-backed HOOP_ASSEMBLY + 2 experiments (exp1, exp2)."""
    db_path = tmp_path / "hoop_orch.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    _build_hoop_assembly(con)
    insert_experiments(
        con, "HOOP_ASSEMBLY",
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
    locally, matching the corrected (assembly-level, not per-magnet)
    prepare_geometry_directory call shape — a regression to the old
    per-magnet/``geometry_data=`` call raises TypeError here exactly as it
    would against the real function.

    Returns the geometry directory the fake creates, so tests can assert it
    gets cleaned up by compute_hoop_stress_history()'s `finally` block, and
    a call counter to assert prepare_geometry_directory runs once per assembly,
    not once per magnet.
    """
    geom_dir = tmp_path / "geom_out"
    calls = {"prepare_geometry_directory": 0}

    def fake_load_assembly_config_from_duckdb(assembly_name, db_path, con=None):
        return "M9", [
            ("MAG_NEW", {"geom": "MAG_NEW.yaml"}, None),
            ("MAG_OLD", {"geom": "MAG_OLD.yaml"}, None),
            ("MAG_B", {"geom": "MAG_B.yaml"}, None),
        ]

    def fake_prepare_geometry_directory(assembly_name, config, db_path, geometries_dir=None, con=None):
        calls["prepare_geometry_directory"] += 1
        assert assembly_name == "HOOP_ASSEMBLY"
        assert con is not None  # compute_hoop_stress_history must reuse its own connection
        assert isinstance(config, dict) and set(config) == {"name", "magnets"}
        assert len(config["magnets"]) == 3
        geom_dir.mkdir(exist_ok=True)
        return geom_dir

    def fake_load_magnettools(config, tempdir, debug=False):
        return "FAKE_MAGNETTOOLS_DATA"

    monkeypatch.setattr("stress_map.load_assembly_config_from_duckdb", fake_load_assembly_config_from_duckdb)
    monkeypatch.setattr("stress_map.prepare_geometry_directory", fake_prepare_geometry_directory)
    monkeypatch.setattr("stress_map.load_magnettools", fake_load_magnettools)
    return geom_dir, calls


def test_compute_hoop_stress_history_full_run(patched_hoop_pipeline, hoop_db_path, monkeypatch, tmp_path):
    geom_dir, calls = patched_hoop_pipeline

    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, assembly=None, z0_h=None, z0_b=None):
        return pd.DataFrame({"t": [0.0, 1.0, 2.0, 3.0], "H1_fast": [10.0, 60.0, 20.0, 80.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)

    pq_dir = tmp_path / "pq"
    results = compute_hoop_stress_history(
        "HOOP_ASSEMBLY", hoop_db_path, parquet_dir=str(pq_dir), verbose=False,
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
    def fake_load_assembly_config_from_duckdb(assembly_name, db_path, con=None):
        return "M9", [("MAG_NEW", {"geom": "MAG_NEW.yaml"}, None)]

    def fake_prepare_geometry_directory(assembly_name, config, db_path, geometries_dir=None, con=None):
        raise RuntimeError("geometry boom")

    monkeypatch.setattr("stress_map.load_assembly_config_from_duckdb", fake_load_assembly_config_from_duckdb)
    monkeypatch.setattr("stress_map.prepare_geometry_directory", fake_prepare_geometry_directory)

    results = compute_hoop_stress_history("HOOP_ASSEMBLY", hoop_db_path, verbose=False)

    assert results == {"new": 0, "skipped": 0, "errors": ["geometry boom"]}


def test_compute_hoop_stress_history_skips_already_processed_unless_reprocess(
    patched_hoop_pipeline, hoop_db_path, monkeypatch, tmp_path
):
    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, assembly=None, z0_h=None, z0_b=None):
        return pd.DataFrame({"t": [0.0, 1.0], "H1_fast": [10.0, 20.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)
    pq_dir = str(tmp_path / "pq")

    r1 = compute_hoop_stress_history("HOOP_ASSEMBLY", hoop_db_path, parquet_dir=pq_dir, verbose=False)
    assert r1["new"] == 2 and r1["skipped"] == 0

    r2 = compute_hoop_stress_history("HOOP_ASSEMBLY", hoop_db_path, parquet_dir=pq_dir, verbose=False)
    assert r2["new"] == 0 and r2["skipped"] == 2

    con = duckdb.connect(hoop_db_path, read_only=True)
    try:
        n_rows = con.execute("SELECT COUNT(*) FROM hoop_stress_processed").fetchone()[0]
        assert n_rows == 2  # not duplicated by the re-run
    finally:
        con.close()

    r3 = compute_hoop_stress_history(
        "HOOP_ASSEMBLY", hoop_db_path, parquet_dir=pq_dir, reprocess=True, verbose=False,
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
        "HOOP_ASSEMBLY", hoop_db_path, parquet_dir=str(pq_dir), dry_run=True, verbose=False,
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
    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, assembly=None, z0_h=None, z0_b=None):
        return pd.DataFrame({"t": [0.0, 1.0], "H1_fast": [10.0, 20.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)
    pq_dir = str(tmp_path / "pq")

    r1 = compute_hoop_stress_history("HOOP_ASSEMBLY", hoop_db_path, parquet_dir=pq_dir, verbose=False)
    assert r1["new"] == 2
    capsys.readouterr()  # discard first-run output

    r2 = compute_hoop_stress_history(
        "HOOP_ASSEMBLY", hoop_db_path, parquet_dir=pq_dir,
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
    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, assembly=None, z0_h=None, z0_b=None):
        if "exp1" in exp_file:
            raise RuntimeError("boom")
        return pd.DataFrame({"t": [0.0, 1.0], "H1_fast": [10.0, 20.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)

    results = compute_hoop_stress_history(
        "HOOP_ASSEMBLY", hoop_db_path, parquet_dir=str(tmp_path / "pq"), verbose=False,
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
    def fake_validate(data, exp_file, housing, magnet_type="all", use_mrun=False, assembly=None, z0_h=None, z0_b=None):
        return pd.DataFrame({"t": [0.0, 1.0], "IH": [100.0, 200.0]})

    monkeypatch.setattr("stress_map.validate_fast_from_pupitre", fake_validate)

    results = compute_hoop_stress_history(
        "HOOP_ASSEMBLY", hoop_db_path, parquet_dir=str(tmp_path / "pq"), verbose=False,
    )

    assert results["new"] == 0
    assert len(results["errors"]) == 2
    assert all(msg == "no hoop columns" for _name, msg in results["errors"])


# ---------------------------------------------------------------------------
# part_history_stats / build_part_history_series — cross-experiment/assembly
# aggregation and chronological concatenation (Phase 3)
# ---------------------------------------------------------------------------


def _build_part_history_assemblies(con):
    """Part 'H_NEW' recorded on two experiments across two different assemblies
    (ASSEMBLY_A, ASSEMBLY_B). Returns (exp_a_id, exp_b_id).
    """
    insert_part(con, {"name": "H_NEW", "type": "helix"}, verbose=False)
    insert_assembly(con, {"name": "ASSEMBLY_A", "status": "in_operation"}, verbose=False)
    insert_assembly(con, {"name": "ASSEMBLY_B", "status": "in_operation"}, verbose=False)
    insert_experiments(con, "ASSEMBLY_A", [{"name": "expA", "file": "expA.txt"}], verbose=False)
    insert_experiments(con, "ASSEMBLY_B", [{"name": "expB", "file": "expB.txt"}], verbose=False)
    exp_a = con.execute("SELECT id FROM experiments WHERE assembly_name = 'ASSEMBLY_A'").fetchone()[0]
    exp_b = con.execute("SELECT id FROM experiments WHERE assembly_name = 'ASSEMBLY_B'").fetchone()[0]
    return exp_a, exp_b


@pytest.fixture
def part_history_fixture(con):
    """'H_NEW' with hoop_stress_bin_stats/hoop_stress_fatigue rows on two
    experiments across two assemblies (ASSEMBLY_A, ASSEMBLY_B). Returns (con, exp_a, exp_b).
    """
    exp_a, exp_b = _build_part_history_assemblies(con)

    _insert_bin_stats(con, exp_a, "H_NEW", [{
        "stress_bin_low": 0.0, "stress_bin_high": 100.0, "n_samples": 2,
        "sum_dt": 3.0, "sum_x_dt": 60.0, "sum_x2_dt": 1400.0,
        "min_x": 10.0, "max_x": 50.0,
    }])
    _insert_bin_stats(con, exp_b, "H_NEW", [
        {
            "stress_bin_low": 0.0, "stress_bin_high": 100.0, "n_samples": 3,
            "sum_dt": 5.0, "sum_x_dt": 90.0, "sum_x2_dt": 2000.0,
            "min_x": 5.0, "max_x": 70.0,
        },
        {
            "stress_bin_low": 100.0, "stress_bin_high": 200.0, "n_samples": 1,
            "sum_dt": 1.0, "sum_x_dt": 150.0, "sum_x2_dt": 22500.0,
            "min_x": 150.0, "max_x": 150.0,
        },
    ])
    _insert_fatigue(con, exp_a, "H_NEW", {"n_cycles": 4.0, "sum_range3": 100.0})
    _insert_fatigue(con, exp_b, "H_NEW", {"n_cycles": 6.0, "sum_range3": 250.0})

    return con, exp_a, exp_b


def test_part_history_stats_aggregates_bin_stats_and_fatigue_across_assemblies(part_history_fixture):
    con, _exp_a, _exp_b = part_history_fixture

    stats = part_history_stats("H_NEW", "", con=con)

    assert stats["part_name"] == "H_NEW"
    assert {e["assembly_name"] for e in stats["experiments"]} == {"ASSEMBLY_A", "ASSEMBLY_B"}
    assert len(stats["experiments"]) == 2

    bins = {(r["stress_bin_low"], r["stress_bin_high"]): r for r in stats["bin_stats"]}

    # manual aggregation over the fixture: ASSEMBLY_A's (0,100) row + ASSEMBLY_B's (0,100) row
    low = bins[(0.0, 100.0)]
    assert low["n_samples"] == 5       # 2 + 3
    assert low["sum_dt"] == pytest.approx(8.0)     # 3.0 + 5.0
    assert low["sum_x_dt"] == pytest.approx(150.0)  # 60.0 + 90.0
    assert low["sum_x2_dt"] == pytest.approx(3400.0)  # 1400.0 + 2000.0
    assert low["min_x"] == 5.0   # min(10.0, 5.0)
    assert low["max_x"] == 70.0  # max(50.0, 70.0)

    # (100, 200) only has ASSEMBLY_B's row -- no aggregation needed
    high = bins[(100.0, 200.0)]
    assert high["n_samples"] == 1
    assert high["sum_dt"] == pytest.approx(1.0)

    assert stats["fatigue"]["n_cycles"] == pytest.approx(10.0)    # 4.0 + 6.0
    assert stats["fatigue"]["sum_range3"] == pytest.approx(350.0)  # 100.0 + 250.0


def test_part_history_stats_empty_for_part_with_no_recorded_data(con):
    insert_part(con, {"name": "H_UNUSED", "type": "helix"}, verbose=False)

    stats = part_history_stats("H_UNUSED", "", con=con)

    assert stats == {
        "part_name": "H_UNUSED",
        "experiments": [],
        "bin_stats": [],
        "fatigue": {"n_cycles": 0.0, "sum_range3": 0.0},
    }


def test_build_part_history_series_concatenates_chronologically_across_assemblies(
    part_history_fixture, tmp_path
):
    con, exp_a, exp_b = part_history_fixture

    # ASSEMBLY_B's t0 is earlier than ASSEMBLY_A's, so the chronologically-correct
    # result must reorder them, not just concatenate in experiment_id order.
    path_a = save_hoop_parquet(
        pd.DataFrame({"t": [0.0, 1.0], "H_NEW": [10.0, 20.0]}),
        tmp_path / "expA.parquet",
        assembly_name="ASSEMBLY_A", housing="M9", t0="2025-06-01T00:00:00",
        experiment_file="expA.txt", part_map={"H1_fast": "H_NEW"},
    )
    path_b = save_hoop_parquet(
        pd.DataFrame({"t": [0.0, 1.0, 2.0], "H_NEW": [1.0, 2.0, 3.0]}),
        tmp_path / "expB.parquet",
        assembly_name="ASSEMBLY_B", housing="M10", t0="2025-01-01T00:00:00",
        experiment_file="expB.txt", part_map={"H1_fast": "H_NEW"},
    )
    _mark_processed(con, exp_a, "all", "0.0,100.0", str(path_a))
    _mark_processed(con, exp_b, "all", "0.0,100.0", str(path_b))

    out_path = build_part_history_series("H_NEW", "", str(tmp_path), con=con, verbose=False)

    assert out_path == tmp_path / "parts" / "H_NEW.parquet"
    result = pq.read_table(out_path).to_pandas()

    # row-count concatenation across experiments: 2 (ASSEMBLY_A) + 3 (ASSEMBLY_B)
    assert len(result) == 5
    assert result["timestamp"].is_monotonic_increasing
    # ASSEMBLY_B (t0=2025-01-01) sorts before ASSEMBLY_A (t0=2025-06-01)
    assert result["assembly_name"].tolist() == ["ASSEMBLY_B"] * 3 + ["ASSEMBLY_A"] * 2
    assert result["experiment_id"].tolist() == [exp_b] * 3 + [exp_a] * 2
    assert result["hoop_stress_MPa"].tolist() == [1.0, 2.0, 3.0, 10.0, 20.0]


def test_build_part_history_series_warns_and_skips_pre_rename_parquet(
    part_history_fixture, tmp_path, capsys
):
    con, exp_a, exp_b = part_history_fixture

    # exp_a: current-format file (column already renamed to the part name).
    path_a = save_hoop_parquet(
        pd.DataFrame({"t": [0.0, 1.0], "H_NEW": [10.0, 20.0]}),
        tmp_path / "expA.parquet",
        assembly_name="ASSEMBLY_A", housing="M9", t0="2025-06-01T00:00:00",
        experiment_file="expA.txt", part_map={"H1_fast": "H_NEW"},
    )
    # exp_b: pre-rename file -- still has the raw slot-name column, not the
    # part name (the schema `build_part_column_map`/save_hoop_parquet used
    # before the Phase 2 rename).
    path_b = save_hoop_parquet(
        pd.DataFrame({"t": [0.0, 1.0], "H1_fast": [1.0, 2.0]}),
        tmp_path / "expB.parquet",
        assembly_name="ASSEMBLY_B", housing="M10", t0="2025-01-01T00:00:00",
        experiment_file="expB.txt", part_map={},
    )
    _mark_processed(con, exp_a, "all", "0.0,100.0", str(path_a))
    _mark_processed(con, exp_b, "all", "0.0,100.0", str(path_b))

    out_path = build_part_history_series("H_NEW", "", str(tmp_path), con=con, verbose=True)
    captured = capsys.readouterr()

    assert "[WARN]" in captured.out
    assert "no 'H_NEW' column" in captured.out

    result = pq.read_table(out_path).to_pandas()
    assert len(result) == 2  # only ASSEMBLY_A's file contributed
    assert result["assembly_name"].unique().tolist() == ["ASSEMBLY_A"]


def test_build_part_history_series_returns_none_when_no_data(con, tmp_path):
    insert_part(con, {"name": "H_UNUSED", "type": "helix"}, verbose=False)

    out_path = build_part_history_series("H_UNUSED", "", str(tmp_path), con=con, verbose=False)

    assert out_path is None


# ---------------------------------------------------------------------------
# Fatigue additivity (Phase 5) — is summing per-experiment n_cycles/sum_range3
# equivalent to rainflow-counting the full concatenated series?
# ---------------------------------------------------------------------------


def test_part_history_fatigue_matches_concatenated_rainflow_when_experiments_idle_at_zero(
    con, tmp_path
):
    """Real magnet experiments ramp down to zero stress between runs, and
    when each experiment's own turning-point sequence fully resolves into
    closed cycles (no leftover rainflow residual), summing per-experiment
    fatigue stats exactly matches rainflow-counting the full chronologically
    concatenated series -- confirmed against real multi-experiment DB data
    for this same reason (see docs/hoop-stress.md)."""
    insert_part(con, {"name": "H_FAT", "type": "helix"}, verbose=False)
    insert_assembly(con, {"name": "ASSEMBLY_F", "status": "in_operation"}, verbose=False)
    insert_experiments(con, "ASSEMBLY_F", [
        {"name": "exp1", "file": "exp1.txt"},
        {"name": "exp2", "file": "exp2.txt"},
    ], verbose=False)
    exp1, exp2 = con.execute(
        "SELECT id FROM experiments WHERE assembly_name = 'ASSEMBLY_F' ORDER BY id"
    ).fetchdf()["id"].tolist()

    # Both series start and end at 0 MPa, and are internally self-closed
    # (integer n_cycles when rainflow-counted alone -- no leftover residual).
    sigma_1 = [0.0, 40.0, 10.0, 60.0, 0.0]
    sigma_2 = [0.0, 50.0, 5.0, 45.0, 0.0]

    _insert_fatigue(con, exp1, "H_FAT", _rainflow_stats(pd.Series(sigma_1)))
    _insert_fatigue(con, exp2, "H_FAT", _rainflow_stats(pd.Series(sigma_2)))
    # build_part_history_series discovers contributing experiments via
    # hoop_stress_bin_stats, not hoop_stress_fatigue -- a row per experiment
    # is required even though this test doesn't examine bin-stats values.
    _insert_bin_stats(con, exp1, "H_FAT", [{
        "stress_bin_low": 0.0, "stress_bin_high": 100.0, "n_samples": 5,
        "sum_dt": 4.0, "sum_x_dt": 110.0, "sum_x2_dt": 5400.0,
        "min_x": 0.0, "max_x": 60.0,
    }])
    _insert_bin_stats(con, exp2, "H_FAT", [{
        "stress_bin_low": 0.0, "stress_bin_high": 100.0, "n_samples": 5,
        "sum_dt": 4.0, "sum_x_dt": 100.0, "sum_x2_dt": 4550.0,
        "min_x": 0.0, "max_x": 50.0,
    }])

    path_1 = save_hoop_parquet(
        pd.DataFrame({"t": list(range(len(sigma_1))), "H_FAT": sigma_1}),
        tmp_path / "exp1.parquet",
        assembly_name="ASSEMBLY_F", housing="M9", t0="2025-01-01T00:00:00",
        experiment_file="exp1.txt", part_map={"H1_fast": "H_FAT"},
    )
    path_2 = save_hoop_parquet(
        pd.DataFrame({"t": list(range(len(sigma_2))), "H_FAT": sigma_2}),
        tmp_path / "exp2.parquet",
        assembly_name="ASSEMBLY_F", housing="M9", t0="2025-01-02T00:00:00",
        experiment_file="exp2.txt", part_map={"H1_fast": "H_FAT"},
    )
    _mark_processed(con, exp1, "all", "0.0,100.0", str(path_1))
    _mark_processed(con, exp2, "all", "0.0,100.0", str(path_2))

    summed = part_history_stats("H_FAT", "", con=con)["fatigue"]

    out_path = build_part_history_series("H_FAT", "", str(tmp_path), con=con, verbose=False)
    concatenated_series = pq.read_table(out_path).to_pandas()["hoop_stress_MPa"]
    concatenated = _rainflow_stats(concatenated_series)

    assert concatenated["n_cycles"] == pytest.approx(summed["n_cycles"])
    assert concatenated["sum_range3"] == pytest.approx(summed["sum_range3"])


def test_rainflow_stats_boundary_discontinuity_breaks_additivity():
    """Additivity is not a general rainflow-counting guarantee: it relies on
    experiments starting/ending at the same reference stress. If one
    experiment's series ends far from where the next one begins, summing
    per-experiment fatigue stats diverges substantially from rainflow-
    counting the joined series -- unlike the zero-boundary case above."""
    sigma_a = [0.0, 40.0, 10.0, 60.0, 100.0]  # ends away from zero
    sigma_b = [0.0, 5.0, 45.0, 0.0]

    fatigue_a = _rainflow_stats(pd.Series(sigma_a))
    fatigue_b = _rainflow_stats(pd.Series(sigma_b))
    summed = {
        "n_cycles": fatigue_a["n_cycles"] + fatigue_b["n_cycles"],
        "sum_range3": fatigue_a["sum_range3"] + fatigue_b["sum_range3"],
    }

    concatenated = _rainflow_stats(pd.Series(sigma_a + sigma_b))

    assert concatenated["n_cycles"] != pytest.approx(summed["n_cycles"])
    assert concatenated["sum_range3"] != pytest.approx(summed["sum_range3"])
