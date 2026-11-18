import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dash_selectors as selectors
from dash import html


def test_file_stats_banner_includes_pupitre_sources_as_plain_text_without_assembly():
    banner = selectors.file_stats_banner(12.5, None, ["a.txt", "b.txt"])
    pupitre_span = banner.children[-1].children
    assert pupitre_span.children == ["Pupitre sources: ", "a.txt", ", ", "b.txt"]


def test_file_stats_banner_links_pupitre_sources_when_assembly_given():
    banner = selectors.file_stats_banner(
        12.5, None, ["a.txt", "b.txt"], assembly_name="M9_A1"
    )
    pupitre_span = banner.children[-1].children
    label, link_a, sep, link_b = pupitre_span.children
    assert label == "Pupitre sources: "
    assert sep == ", "
    assert link_a.children == "a.txt"
    assert link_a.href == "/file_viewer?assembly=M9_A1&file=a.txt"
    assert link_b.children == "b.txt"
    assert link_b.href == "/file_viewer?assembly=M9_A1&file=b.txt"


def test_file_stats_banner_omits_pupitre_line_when_empty():
    banner = selectors.file_stats_banner(12.5, None, [])
    assert "Pupitre sources" not in banner.children


def test_file_stats_banner_backward_compatible_without_pupitre_arg():
    banner = selectors.file_stats_banner(12.5, None)
    assert banner.children == "Duration: 12.5 s"


def test_file_stats_banner_empty_when_everything_missing():
    banner = selectors.file_stats_banner(None, None, None)
    assert banner.children is None


def _field(column, mx):
    return {"column": column, "unit": "tesla", "min": 0.0, "mean": 1.0, "max": mx, "std": 0.5}


def test_file_stats_banner_includes_energy_line():
    banner = selectors.file_stats_banner(
        12.5, None, energy_stats={"energy_mwh": 0.0034, "n_included": 1}
    )
    assert [line.children for line in banner.children] == [
        "Duration: 12.5 s",
        "Energy: 0.0034 MWh",
    ]


def test_file_stats_banner_marks_zoomed_range_on_duration_line():
    banner = selectors.file_stats_banner(5.0, None, zoomed=True)
    assert banner.children == "Duration: 5.0 s (zoomed range)"


def test_file_stats_banner_hybrid_sources_after_pupitre():
    banner = selectors.file_stats_banner(
        12.5,
        None,
        ["a.txt"],
        hybrid_files={
            "kHz": ["k1.bin", "k2.bin"],
            "RMS": ["r1.rms"],
            "trigger": [],
            "vprocess": [],
        },
    )
    stats_line, pupitre_line, hybrid_line = banner.children
    assert stats_line.children == "Duration: 12.5 s"
    assert pupitre_line.children.children[0] == "Pupitre sources: "
    hybrid = hybrid_line.children
    assert isinstance(hybrid, html.Details)
    summary, body = hybrid.children
    assert summary.children == "Hybrid sources: kHz 2, RMS 1"
    assert [line.children for line in body.children] == [
        "kHz: k1.bin, k2.bin",
        "RMS: r1.rms",
    ]


def test_file_stats_banner_hybrid_sources_none_when_all_empty():
    for hybrid_files in ({}, {"kHz": [], "RMS": []}):
        banner = selectors.file_stats_banner(12.5, None, ["a.txt"], hybrid_files=hybrid_files)
        hybrid = banner.children[-1].children
        assert isinstance(hybrid, html.Span)
        assert hybrid.children == ["Hybrid sources: ", "none"]


def test_file_stats_banner_no_hybrid_segment_by_default():
    banner = selectors.file_stats_banner(12.5, None, ["a.txt"])
    stats_line, pupitre_line = banner.children
    assert stats_line.children == "Duration: 12.5 s"
    assert pupitre_line.children.children[0] == "Pupitre sources: "


def test_file_stats_banner_one_item_per_line():
    banner = selectors.file_stats_banner(
        12.5,
        _field("Champ_magn", 33.5),
        ["a.txt"],
        energy_stats={"energy_mwh": 0.0034, "n_included": 1},
        hybrid_files={"kHz": ["k1.bin"]},
        extra_field_stats=[_field("SupraField", 8.5), _field("TotalField", 42.0)],
    )
    lines = banner.children
    assert [line.children for line in lines[:5]] == [
        "Duration: 12.5 s",
        "Champ_magn: min=0 tesla, mean=1 tesla, max=33.5 tesla, std=0.5 tesla",
        "SupraField: min=0 tesla, mean=1 tesla, max=8.5 tesla, std=0.5 tesla",
        "TotalField: min=0 tesla, mean=1 tesla, max=42 tesla, std=0.5 tesla",
        "Energy: 0.0034 MWh",
    ]
    assert lines[5].children.children == ["Pupitre sources: ", "a.txt"]
    assert isinstance(lines[6].children, html.Details)
    assert len(lines) == 7


def test_file_stats_banner_no_extra_field_lines_by_default():
    banner = selectors.file_stats_banner(12.5, _field("Field", 30.0))
    assert [line.children for line in banner.children] == [
        "Duration: 12.5 s",
        "Field: min=0 tesla, mean=1 tesla, max=30 tesla, std=0.5 tesla",
    ]


def test_file_stats_banner_sources_only_without_stats_line():
    banner = selectors.file_stats_banner(None, None, ["a.txt"])
    (pupitre_line,) = banner.children
    assert pupitre_line.children.children == ["Pupitre sources: ", "a.txt"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"{name}: OK")
