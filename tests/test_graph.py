"""Graph scoring (route value, PageRank importance, breaks, layers) and the viewer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nmt_engine.graph import score
from nmt_engine.schema import Edge, EdgeCosts
from nmt_engine.stats import Z80, agreement, precision, wilson


def _edge(i, a, b, p=None, costs=None, layer="customer", kind="sequence"):
    return Edge(id=i, from_job=a, to_job=b, kind=kind, layer=layer, p_success=p, costs=costs)


def test_route_value_interval_arithmetic():
    e1 = _edge("e1", "a", "b", (0.5, 0.8), EdgeCosts(time=(0.1, 0.2)))
    e2 = _edge("e2", "b", "c", (0.5, 1.0), EdgeCosts(negative_emotion=(0.0, 0.1)))
    lo, hi = score.route_value([e1, e2], outcome=(10.0, 20.0))
    assert (lo, hi) == pytest.approx((0.25 * 10 - 0.3, 0.8 * 20 - 0.1))
    assert score.route_value([]) == (1.0, 1.0)


def test_added_value_uses_best_alternative():
    assert score.added_value((5, 6), [(1, 2), (3, 4)]) == (1, 3)
    assert score.added_value((5, 6), []) == (5, 6)


def test_importance_weighted_and_deterministic():
    edges = [_edge("e1", "a", "b"), _edge("e2", "c", "b"), _edge("e3", "b", "d")]
    freq = {"a": 1, "b": 10, "c": 1, "d": 1}
    r1 = score.importance("abcd", edges, freq, {})
    r2 = score.importance("dcba", list(reversed(edges)), freq, {})
    assert r1 == r2 and max(r1, key=r1.get) == "b"
    assert sum(r1.values()) == pytest.approx(1.0)


def test_critical_breaks_and_layers():
    edges = [
        _edge("e1", "a", "b", (0.1, 0.4)),
        _edge("e2", "b", "c", (0.3, 0.7)),
        _edge("e3", "s", "c", (0.6, 0.9), layer="product", kind="performs"),
    ]
    breaks = score.critical_breaks(edges)
    assert [(b.edge_id, b.certain) for b in breaks] == [("e1", True), ("e2", False)]
    views = score.layer_views(edges)
    assert views["product"] == {"edges": ["e3"], "nodes": ["c", "s"]}
    assert views["business"] == {"edges": [], "nodes": []}


def test_graph_json_cannot_break_out_of_script(tmp_path: Path) -> None:
    from nmt_engine.graph.viewer import _script_json, write_graph_html

    evil = "</SCRIPT><script>alert(1)</script><!--<script>"
    assert "<" not in _script_json({"label": evil})
    assert "\u2028" not in _script_json({"q": "a\u2028b\u2029c"})
    assert json.loads(_script_json({"q": "a\u2028b"}))["q"] == "a\u2028b"
    assert json.loads(_script_json({"label": evil}))["label"] == evil
    html = write_graph_html(
        {"nodes": [{"data": {"id": "j", "label": evil}}], "edges": []}, tmp_path / "g.html"
    ).read_text()
    assert "alert(1)</script>" not in html and "<!--<script>" not in html


def test_wilson_agreement_precision():
    lo, hi = wilson(0, 10, Z80)
    assert lo == 0.0 and 0 < hi < 0.3
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(11, 50)
    assert (lo, hi) == pytest.approx((0.127539, 0.352415), abs=1e-5)
    assert agreement([1, 0, 1], [1, 1, 1]) == 0.6667 and agreement([], []) == 0.0
    assert precision(["U", "B", "U", None], ["U", "U", "B", "U"], "U") == (1, 2)
