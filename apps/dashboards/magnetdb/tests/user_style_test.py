import base64
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from plotly.utils import PlotlyJSONEncoder

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_plot as plot
import style_editor

_PUPITRE_FILE = "2025.12.02 - 14:30:46.txt"


def _base_config():
    return plot.StyleConfig(
        field_overrides={
            "G": {
                "a": plot.FieldStyleOverride(color="#ff0000"),
                "b": plot.FieldStyleOverride(color="#0000ff"),
            },
            "H": {"c": plot.FieldStyleOverride(width=4)},
        }
    )


def _upload_contents(payload) -> str:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return "data:application/json;base64," + base64.b64encode(raw).decode()


# --- merge_style_config ---------------------------------------------------


@pytest.mark.parametrize("user_data", [None, {}])
def test_merge_without_user_layer_returns_base(user_data):
    base = _base_config()
    assert plot.merge_style_config(base, user_data) == base


def test_merge_updates_source_style_property_by_property():
    merged = plot.merge_style_config(_base_config(), {"pupitre": {"opacity": 0.5}})
    assert merged.file_type_styles.pupitre.opacity == 0.5
    assert merged.file_type_styles.pupitre.color == "#2ca02c"
    assert merged.file_type_styles.overview == plot.FileTypeStyles().overview


def test_merge_replaces_user_group_as_a_whole_and_keeps_other_groups():
    merged = plot.merge_style_config(
        _base_config(), {"field_overrides": {"G": {"a": {"width": 3}}}}
    )
    assert merged.field_overrides["G"] == {"a": plot.FieldStyleOverride(width=3)}
    assert merged.field_overrides["H"] == {"c": plot.FieldStyleOverride(width=4)}


def test_merge_does_not_mutate_base():
    base = _base_config()
    plot.merge_style_config(base, {"pupitre": {"opacity": 0.5}, "field_overrides": {"G": {}}})
    assert base == _base_config()


# --- plot functions honour an explicit style_config -----------------------


def _pupitre_config(color="#123456", override=None):
    config = plot.StyleConfig()
    config.file_type_styles.pupitre.color = color
    if override:
        config.field_overrides = {"G": {"Ucoil1": override}}
    return config


def _df():
    return pd.DataFrame({"t": [0.0, 1.0, 2.0], "Ucoil1": [1.0, 2.0, 3.0]})


def test_create_plot_uses_explicit_style_config():
    fig = plot.create_plot(
        _df(), "t", ["Ucoil1"], "raw data", filename=_PUPITRE_FILE,
        group_name="G", style_config=_pupitre_config(),
    )
    assert fig.data[0].line.color == "#123456"


def test_create_plot_uses_field_override_from_style_config():
    config = _pupitre_config(override=plot.FieldStyleOverride(color="#abcdef", width=5))
    fig = plot.create_plot(
        _df(), "t", ["Ucoil1"], "raw data", filename=_PUPITRE_FILE,
        group_name="G", style_config=config,
    )
    assert fig.data[0].line.color == "#abcdef"
    assert fig.data[0].line.width == 5


def test_create_plot_defaults_to_server_style_config():
    fig = plot.create_plot(_df(), "t", ["Ucoil1"], "raw data", filename=_PUPITRE_FILE)
    assert fig.data[0].line.color == plot._STYLE_CONFIG.file_type_styles.pupitre.color


def test_create_annotated_plot_uses_explicit_style_config():
    files_data = [{"file": _PUPITRE_FILE, "df": _df(), "sensors": ["Ucoil1"], "mrun": None}]
    fig = plot.create_annotated_plot(
        files_data, "t", "raw data", group_name="G", style_config=_pupitre_config()
    )
    assert fig.data[0].line.color == "#123456"


# --- style editor helpers ------------------------------------------------


def test_saved_user_layer_replaces_group_and_records_opacity():
    user_layer = {"field_overrides": {"G": {"old": {"color": "#000000"}}, "H": {"c": {"width": 4}}}}
    saved = style_editor._saved_user_layer(
        user_layer,
        "G",
        {"a": plot.FieldStyleOverride(color="#ff0000", width=2)},
        {"pupitre": 0.4, "overview": None},
    )
    assert saved["field_overrides"]["G"] == {"a": {"color": "#ff0000", "width": 2}}
    assert saved["field_overrides"]["H"] == {"c": {"width": 4}}
    assert saved["pupitre"] == {"opacity": 0.4}
    assert "overview" not in saved
    # input store data is left untouched
    assert user_layer == {"field_overrides": {"G": {"old": {"color": "#000000"}}, "H": {"c": {"width": 4}}}}


def test_saved_user_layer_starts_from_empty_store():
    saved = style_editor._saved_user_layer(None, "G", {"a": plot.FieldStyleOverride(dash="dot")}, {})
    assert saved == {"field_overrides": {"G": {"a": {"dash": "dot"}}}}


def test_reset_group_removes_only_that_group():
    user_layer = {"pupitre": {"opacity": 0.4}, "field_overrides": {"G": {}, "H": {}}}
    reset = style_editor._reset_group(user_layer, "G")
    assert reset == {"pupitre": {"opacity": 0.4}, "field_overrides": {"H": {}}}
    assert "G" in user_layer["field_overrides"]


def test_export_then_import_round_trips():
    user_layer = {"pupitre": {"opacity": 0.4}, "field_overrides": {"G": {"a": {"color": "#ff0000"}}}}
    exported = style_editor._export_json(user_layer)
    assert style_editor._parse_import(_upload_contents(exported.encode())) == user_layer


def test_exported_file_is_a_valid_site_style_json(tmp_path):
    out = tmp_path / "style.json"
    out.write_text(style_editor._export_json({"pupitre": {"opacity": 0.4}}))
    assert plot.load_style_config(out).file_type_styles.pupitre.opacity == 0.4


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        [1, 2, 3],
        {"pupitre": {"no_such_property": 1}},
        {"pupitre": "red"},
        {"field_overrides": {"G": "red"}},
    ],
)
def test_parse_import_rejects_malformed_files(payload):
    with pytest.raises(ValueError):
        style_editor._parse_import(_upload_contents(payload))


def _find_component(node, component_id):
    if isinstance(node, dict):
        props = node.get("props", {})
        if props.get("id") == component_id:
            return node
        for value in props.values():
            found = _find_component(value, component_id)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_component(item, component_id)
            if found is not None:
                return found
    return None


def test_modal_has_export_import_and_confirmed_reset_all():
    layout = json.loads(json.dumps(style_editor.modal_component("xx"), cls=PlotlyJSONEncoder))
    assert _find_component(layout, "xx-style-export-btn") is not None
    assert _find_component(layout, "xx-style-export")["type"] == "Download"
    assert _find_component(layout, "xx-style-import")["type"] == "Upload"
    assert _find_component(layout, "xx-style-reset-all")["type"] == "ConfirmDialogProvider"


# --- app layout ----------------------------------------------------------


def test_app_layout_has_local_user_style_store():
    import magnetdb_app

    layout = magnetdb_app.server.test_client().get("/_dash-layout").get_json()
    store = _find_component(layout, "user-style")
    assert store["type"] == "Store"
    assert store["props"]["storage_type"] == "local"
