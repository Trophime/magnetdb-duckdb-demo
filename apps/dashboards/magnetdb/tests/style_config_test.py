import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_plot as plot


def test_style_config_round_trips_with_field_overrides(tmp_path):
    config = plot.StyleConfig(
        file_type_styles=plot.FileTypeStyles(),
        field_overrides={
            "Courants_Alimentations": {
                "Idcct1": plot.FieldStyleOverride(color="#ff0000", marker_every=20),
            }
        },
    )
    out = tmp_path / "style.json"
    plot.save_style_config(config, out)
    loaded = plot.load_style_config(out)

    assert loaded.file_type_styles == config.file_type_styles
    assert loaded.field_overrides["Courants_Alimentations"]["Idcct1"] == plot.FieldStyleOverride(
        color="#ff0000", marker_every=20
    )


def test_load_style_config_accepts_legacy_file_with_no_field_overrides(tmp_path):
    out = tmp_path / "style.json"
    plot.save_file_type_styles(plot.FileTypeStyles(), out)

    loaded = plot.load_style_config(out)

    assert loaded.file_type_styles == plot.FileTypeStyles()
    assert loaded.field_overrides == {}


def test_load_style_config_loads_bundled_style_json():
    bundled = Path(plot.__file__).parent / "style.json"
    loaded = plot.load_style_config(bundled)
    assert loaded.field_overrides == {}
    assert loaded.file_type_styles.pupitre.color == "#2ca02c"


def test_field_style_override_to_dict_skips_unset_properties():
    override = plot.FieldStyleOverride(color="#000000")
    assert override.to_dict() == {"color": "#000000"}


def test_apply_style_no_style_no_override_matches_today_default():
    kwargs = plot._apply_style(None, None, n_points=5)
    assert kwargs == {"mode": "lines", "line": {"width": 2}, "opacity": 1.0}


def test_apply_style_source_style_only():
    style = plot.TraceStyle(color="#2ca02c", dash="solid", width=2, opacity=1.0)
    kwargs = plot._apply_style(style, None, n_points=5)
    assert kwargs == {
        "mode": "lines",
        "line": {"width": 2, "color": "#2ca02c", "dash": "solid"},
        "opacity": 1.0,
    }


def test_apply_style_color_only_override_keeps_rest_from_source_style():
    style = plot.TraceStyle(color="#2ca02c", dash="solid", width=2, opacity=0.8)
    override = plot.FieldStyleOverride(color="#ff0000")
    kwargs = plot._apply_style(style, override, n_points=5)
    assert kwargs["line"] == {"width": 2, "color": "#ff0000", "dash": "solid"}
    assert kwargs["opacity"] == 0.8
    assert kwargs["mode"] == "lines"


def test_apply_style_width_only_override_keeps_rest_from_source_style():
    style = plot.TraceStyle(color="#2ca02c", dash="solid", width=2, opacity=0.8)
    override = plot.FieldStyleOverride(width=5)
    kwargs = plot._apply_style(style, override, n_points=5)
    assert kwargs["line"] == {"width": 5, "color": "#2ca02c", "dash": "solid"}
    assert kwargs["opacity"] == 0.8


def test_apply_style_marker_every_masks_every_nth_point():
    override = plot.FieldStyleOverride(marker_symbol="circle", marker_every=3)
    kwargs = plot._apply_style(None, override, n_points=10)
    assert kwargs["mode"] == "lines+markers"
    sizes = kwargs["marker"]["size"]
    nonzero_indices = [i for i, s in enumerate(sizes) if s]
    assert nonzero_indices == [0, 3, 6, 9]


def test_apply_style_marker_symbol_without_every_shows_every_point():
    override = plot.FieldStyleOverride(marker_symbol="circle")
    kwargs = plot._apply_style(None, override, n_points=10)
    assert kwargs["mode"] == "lines+markers"
    assert kwargs["marker"] == {"symbol": "circle"}


def test_resolve_field_override_unset_returns_none():
    assert plot._resolve_field_override("SomeGroup", "SomeSensor") is None


def test_resolve_file_type_key_pupitre_and_pigbrother():
    assert plot.resolve_file_type_key("2025.12.02 - 14:30:46.txt") == "pupitre"
    assert plot.resolve_file_type_key("M9_Overview_251202-1430.tdms") == "overview"


if __name__ == "__main__":
    import tempfile

    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            if "tmp_path" in fn.__code__.co_varnames[: fn.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"{name}: OK")
