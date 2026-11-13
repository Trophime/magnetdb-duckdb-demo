import sys
from pathlib import Path

import dash
from dash.dash_table import DataTable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# dash.register_page() (called at the page module's import) requires a
# pages-enabled app to exist first.
dash.Dash(__name__, use_pages=True, pages_folder="")

from pages import about  # noqa: E402


def _find(component, component_id):
    """Depth-first search of a layout for the component with *component_id*."""
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    for child in children if isinstance(children, list) else [children]:
        if child is not None and not isinstance(child, str):
            found = _find(child, component_id)
            if found is not None:
                return found
    return None


def test_operation_log_shows_ten_latest_entries_per_page():
    table = _find(about.layout(), "about-log-table")
    assert isinstance(table, DataTable)
    assert table.page_size == 10
