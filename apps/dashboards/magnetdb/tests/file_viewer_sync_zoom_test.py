import json
import sys
from contextvars import copy_context
from pathlib import Path

import dash
import pytest
from dash._callback_context import context_value
from dash._utils import AttributeDict
from dash.exceptions import PreventUpdate

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# dash.register_page() (called at the page module's import) requires a
# pages-enabled app to exist first.
dash.Dash(__name__, use_pages=True, pages_folder="")

from pages import file_viewer as fv  # noqa: E402

GRAPH_A = {"type": "dynamic-graph", "index": "A"}
GRAPH_B = {"type": "dynamic-graph", "index": "B"}


def _sync_from_a(relayout_a):
    """Run sync_zoom_home as if graph A fired *relayout_a*."""
    prop_id = json.dumps(GRAPH_A, separators=(",", ":"), sort_keys=True) + ".relayoutData"

    def run():
        context_value.set(
            AttributeDict(triggered_inputs=[{"prop_id": prop_id, "value": relayout_a}])
        )
        return fv.sync_zoom_home([relayout_a, None], [GRAPH_A, GRAPH_B])

    return copy_context().run(run)


def _assignments(patch):
    """Map each assigned location (as a tuple) to its value in a Patch."""
    return {
        tuple(op["location"]): op["params"]["value"]
        for op in patch.to_plotly_json()["operations"]
        if op["operation"] == "Assign"
    }


def test_autoscale_propagates_to_other_graphs():
    patches = _sync_from_a({"xaxis.autorange": True})
    assert patches[0] is dash.no_update
    assert _assignments(patches[1]) == {("layout", "xaxis", "autorange"): True}


def test_unrelated_event_is_ignored():
    with pytest.raises(PreventUpdate):
        _sync_from_a({"autosize": True})


def test_range_zoom_propagates_to_other_graphs():
    patches = _sync_from_a({"xaxis.range[0]": 1, "xaxis.range[1]": 5})
    assert patches[0] is dash.no_update
    assert _assignments(patches[1]) == {
        ("layout", "xaxis", "range"): [1, 5],
        ("layout", "xaxis", "autorange"): False,
    }
