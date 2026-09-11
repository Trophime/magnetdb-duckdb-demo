import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dash_selectors as selectors


def test_file_stats_banner_includes_pupitre_sources_as_plain_text_without_assembly():
    banner = selectors.file_stats_banner(12.5, None, ["a.txt", "b.txt"])
    pupitre_span = banner.children[-1]
    assert pupitre_span.children == ["Pupitre sources: ", "a.txt", ", ", "b.txt"]


def test_file_stats_banner_links_pupitre_sources_when_assembly_given():
    banner = selectors.file_stats_banner(
        12.5, None, ["a.txt", "b.txt"], assembly_name="M9_A1"
    )
    pupitre_span = banner.children[-1]
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


def test_file_stats_banner_includes_energy_segment():
    banner = selectors.file_stats_banner(
        12.5, None, energy_stats={"energy_mwh": 0.0034, "n_included": 1}
    )
    assert "Energy: 0.0034 MWh" in banner.children


def test_file_stats_banner_marks_zoomed_range():
    banner = selectors.file_stats_banner(5.0, None, zoomed=True)
    assert "(zoomed range)" in banner.children


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"{name}: OK")
