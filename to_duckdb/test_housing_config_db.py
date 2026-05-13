"""Tests for the housing_config DuckDB table (schema.py + crud.py).

The bundled reference JSON files from python_magnetrun are used as ground
truth.  They are opened read-only and are never modified — all file writes
go to pytest's tmp_path.
"""

import json
from pathlib import Path

import duckdb
import pytest

from schema import ensure_schema
from crud import (
    _derive_housing_config_dict,
    insert_housing_config,
    export_housing_config_json,
)

# ---------------------------------------------------------------------------
# Reference JSON files (read-only)
# ---------------------------------------------------------------------------

_MAGNETRUN_PKG = (
    Path(__file__).parent.parent / "python_magnetrun" / "python_magnetrun"
)

_REF_FILES: dict[str, Path] = {
    "M8":  _MAGNETRUN_PKG / "M8-housing-config.json",
    "M9":  _MAGNETRUN_PKG / "M9-housing-config.json",
    "M10": _MAGNETRUN_PKG / "M10-housing-config.json",
}


def _load_ref(name: str) -> dict:
    return json.loads(_REF_FILES[name].read_text())


def _coil_assignment_from_ref(ref: dict) -> dict[str, str]:
    """Infer {coil_type: GR_name} from a reference JSON dict."""
    suffix_to_coil = {"H": "Insert", "B": "Bitter"}
    s1 = ref["reference_gr1_current"][-1]   # "H" or "B"
    s2 = ref["reference_gr2_current"][-1]
    return {suffix_to_coil[s1]: "GR1", suffix_to_coil[s2]: "GR2"}


def _extra_config_from_ref(ref: dict) -> dict | None:
    """Extract hybrid/extra fields present in a reference JSON dict."""
    keys = [
        "reference_gr1_hybrid", "reference_gr2_hybrid",
        "hybrid_formula_map", "hybrid_voltage_mask_map",
    ]
    extras = {k: ref[k] for k in keys if k in ref and ref[k]}
    return extras or None


# Fields that must be derived correctly from coil_assignment alone.
_DERIVED_FIELDS = [
    "reference_gr1_current", "reference_gr2_current",
    "reference_gr1_flow",    "reference_gr2_flow",
    "reference_gr1_rpm",     "reference_gr2_rpm",
    "reference_gr1_pin",     "reference_gr2_pin",
    "reference_gr1_voltage", "reference_gr2_voltage",
    "voltage_channels_gr1",  "voltage_channels_gr2",
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def con():
    """In-memory DuckDB connection with the full schema applied."""
    conn = duckdb.connect(":memory:")
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def populated_con(con):
    """Connection pre-loaded with M8, M9, M10 from the reference JSON files."""
    for name, path in _REF_FILES.items():
        ref = json.loads(path.read_text())
        insert_housing_config(con, {
            "name": name,
            "coil_assignment": _coil_assignment_from_ref(ref),
            "formats": ref["formats"],
            "extra_config": _extra_config_from_ref(ref),
        }, verbose=False)
    return con


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_housing_config_table_exists(self, con):
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'housing_config'"
        ).fetchall()
        assert rows, "housing_config table not found after ensure_schema()"

    def test_housing_config_has_required_columns(self, con):
        cols = {
            row[0]
            for row in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'housing_config'"
            ).fetchall()
        }
        assert {"name", "coil_assignment", "formats", "extra_config"} <= cols

    def test_ensure_schema_is_idempotent(self, con):
        """Calling ensure_schema twice must not raise."""
        ensure_schema(con)


# ---------------------------------------------------------------------------
# insert_housing_config
# ---------------------------------------------------------------------------


class TestInsertHousingConfig:
    def test_insert_m9_name(self, con):
        ref = _load_ref("M9")
        insert_housing_config(con, {
            "name": "M9",
            "coil_assignment": _coil_assignment_from_ref(ref),
            "formats": ref["formats"],
            "extra_config": None,
        }, verbose=False)
        row = con.execute(
            "SELECT name FROM housing_config WHERE name = 'M9'"
        ).fetchone()
        assert row is not None and row[0] == "M9"

    def test_insert_stores_coil_assignment(self, con):
        ref = _load_ref("M9")
        ca = _coil_assignment_from_ref(ref)
        insert_housing_config(con, {
            "name": "M9", "coil_assignment": ca,
            "formats": ref["formats"], "extra_config": None,
        }, verbose=False)
        row = con.execute(
            "SELECT coil_assignment FROM housing_config WHERE name = 'M9'"
        ).fetchone()
        assert dict(row[0]) == ca

    def test_insert_stores_formats(self, con):
        ref = _load_ref("M9")
        insert_housing_config(con, {
            "name": "M9", "coil_assignment": _coil_assignment_from_ref(ref),
            "formats": ref["formats"], "extra_config": None,
        }, verbose=False)
        row = con.execute(
            "SELECT formats FROM housing_config WHERE name = 'M9'"
        ).fetchone()
        assert list(row[0]) == ref["formats"]

    def test_insert_stores_extra_config_for_m8(self, con):
        ref = _load_ref("M8")
        ec = _extra_config_from_ref(ref)
        insert_housing_config(con, {
            "name": "M8", "coil_assignment": _coil_assignment_from_ref(ref),
            "formats": ref["formats"], "extra_config": ec,
        }, verbose=False)
        row = con.execute(
            "SELECT extra_config FROM housing_config WHERE name = 'M8'"
        ).fetchone()
        stored = json.loads(row[0])
        assert stored["reference_gr1_hybrid"] == ref["reference_gr1_hybrid"]
        assert stored["reference_gr2_hybrid"] == ref["reference_gr2_hybrid"]

    def test_insert_replace_is_idempotent(self, con):
        """Inserting the same name twice (OR REPLACE) must not raise."""
        base = {
            "name": "M9",
            "coil_assignment": {"Insert": "GR1", "Bitter": "GR2"},
            "formats": ["pupitre"],
            "extra_config": None,
        }
        insert_housing_config(con, base, verbose=False)
        updated = dict(base, formats=["pupitre", "pigbrother"])
        insert_housing_config(con, updated, verbose=False)
        row = con.execute(
            "SELECT formats FROM housing_config WHERE name = 'M9'"
        ).fetchone()
        assert list(row[0]) == ["pupitre", "pigbrother"]

    def test_all_three_housings_inserted(self, populated_con):
        count = populated_con.execute(
            "SELECT COUNT(*) FROM housing_config"
        ).fetchone()[0]
        assert count == 3

    @pytest.mark.parametrize("housing", ["M8", "M9", "M10"])
    def test_m9_coil_assignment_is_insert_gr1(self, con, housing):
        """M9 wires Insert to GR1; M8/M10 wire Insert to GR2."""
        ref = _load_ref(housing)
        ca = _coil_assignment_from_ref(ref)
        insert_housing_config(con, {
            "name": housing, "coil_assignment": ca,
            "formats": ref["formats"], "extra_config": None,
        }, verbose=False)
        row = con.execute(
            "SELECT coil_assignment FROM housing_config WHERE name = ?",
            [housing],
        ).fetchone()
        stored = dict(row[0])
        expected_gr1 = "GR1" if housing == "M9" else "GR2"
        assert stored["Insert"] == expected_gr1


# ---------------------------------------------------------------------------
# _derive_housing_config_dict — correctness vs reference JSONs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("housing", ["M8", "M9", "M10"])
class TestDeriveMatchesReference:
    def test_reference_fields(self, housing):
        ref = _load_ref(housing)
        derived = _derive_housing_config_dict(
            housing,
            _coil_assignment_from_ref(ref),
            ref["formats"],
            _extra_config_from_ref(ref),
        )
        for field in _DERIVED_FIELDS:
            assert derived[field] == ref[field], (
                f"{housing}.{field}: got {derived[field]!r}, "
                f"expected {ref[field]!r}"
            )

    def test_formats(self, housing):
        ref = _load_ref(housing)
        derived = _derive_housing_config_dict(
            housing,
            _coil_assignment_from_ref(ref),
            ref["formats"],
            _extra_config_from_ref(ref),
        )
        assert derived["formats"] == ref["formats"]

    def test_pupitre_formula_map(self, housing):
        ref = _load_ref(housing)
        derived = _derive_housing_config_dict(
            housing,
            _coil_assignment_from_ref(ref),
            ref["formats"],
            _extra_config_from_ref(ref),
        )
        assert derived["pupitre_formula_map"] == ref["pupitre_formula_map"]

    def test_pigbrother_formula_map(self, housing):
        ref = _load_ref(housing)
        derived = _derive_housing_config_dict(
            housing,
            _coil_assignment_from_ref(ref),
            ref["formats"],
            _extra_config_from_ref(ref),
        )
        assert derived["pigbrother_formula_map"] == ref["pigbrother_formula_map"]


class TestDeriveM8HybridFields:
    def test_hybrid_formula_map(self):
        ref = _load_ref("M8")
        derived = _derive_housing_config_dict(
            "M8",
            _coil_assignment_from_ref(ref),
            ref["formats"],
            _extra_config_from_ref(ref),
        )
        assert derived["hybrid_formula_map"] == ref["hybrid_formula_map"]

    def test_hybrid_voltage_mask_map(self):
        ref = _load_ref("M8")
        derived = _derive_housing_config_dict(
            "M8",
            _coil_assignment_from_ref(ref),
            ref["formats"],
            _extra_config_from_ref(ref),
        )
        assert derived["hybrid_voltage_mask_map"] == ref["hybrid_voltage_mask_map"]

    def test_reference_gr1_hybrid(self):
        ref = _load_ref("M8")
        derived = _derive_housing_config_dict(
            "M8",
            _coil_assignment_from_ref(ref),
            ref["formats"],
            _extra_config_from_ref(ref),
        )
        assert derived["reference_gr1_hybrid"] == ref["reference_gr1_hybrid"]

    def test_reference_gr2_hybrid(self):
        ref = _load_ref("M8")
        derived = _derive_housing_config_dict(
            "M8",
            _coil_assignment_from_ref(ref),
            ref["formats"],
            _extra_config_from_ref(ref),
        )
        assert derived["reference_gr2_hybrid"] == ref["reference_gr2_hybrid"]


# ---------------------------------------------------------------------------
# export_housing_config_json
# ---------------------------------------------------------------------------


class TestExportHousingConfigJson:
    def test_creates_file(self, populated_con, tmp_path):
        path = export_housing_config_json(populated_con, "M9", tmp_path)
        assert path.exists()

    def test_filename_convention(self, populated_con, tmp_path):
        path = export_housing_config_json(populated_con, "M9", tmp_path)
        assert path.name == "M9-housing-config.json"

    def test_output_is_valid_json(self, populated_con, tmp_path):
        path = export_housing_config_json(populated_con, "M9", tmp_path)
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    @pytest.mark.parametrize("housing", ["M8", "M9", "M10"])
    def test_derived_fields_match_reference(self, populated_con, tmp_path, housing):
        path = export_housing_config_json(populated_con, housing, tmp_path)
        exported = json.loads(path.read_text())
        ref = _load_ref(housing)
        for field in _DERIVED_FIELDS:
            assert exported[field] == ref[field], (
                f"{housing}.{field}: got {exported[field]!r}, "
                f"expected {ref[field]!r}"
            )

    @pytest.mark.parametrize("housing", ["M8", "M9", "M10"])
    def test_formula_maps_match_reference(self, populated_con, tmp_path, housing):
        path = export_housing_config_json(populated_con, housing, tmp_path)
        exported = json.loads(path.read_text())
        ref = _load_ref(housing)
        assert exported["pupitre_formula_map"] == ref["pupitre_formula_map"]
        assert exported["pigbrother_formula_map"] == ref["pigbrother_formula_map"]

    def test_m8_hybrid_fields_match_reference(self, populated_con, tmp_path):
        path = export_housing_config_json(populated_con, "M8", tmp_path)
        exported = json.loads(path.read_text())
        ref = _load_ref("M8")
        assert exported["hybrid_formula_map"] == ref["hybrid_formula_map"]
        assert exported["hybrid_voltage_mask_map"] == ref["hybrid_voltage_mask_map"]
        assert exported["reference_gr1_hybrid"] == ref["reference_gr1_hybrid"]
        assert exported["reference_gr2_hybrid"] == ref["reference_gr2_hybrid"]

    def test_missing_housing_raises(self, con, tmp_path):
        with pytest.raises(ValueError, match="No housing_config row"):
            export_housing_config_json(con, "INVALID", tmp_path)

    def test_reference_files_are_never_modified(self, populated_con, tmp_path):
        """Exporting to tmp_path must leave the original reference files untouched."""
        originals = {name: path.read_text() for name, path in _REF_FILES.items()}
        for name in _REF_FILES:
            export_housing_config_json(populated_con, name, tmp_path)
        for name, path in _REF_FILES.items():
            assert path.read_text() == originals[name], (
                f"Reference file {path.name} was modified!"
            )
