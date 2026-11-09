"""Route value, added value, weighted PageRank importance, critical-chain breaks, layer views.

Ranges are closed intervals (lo, hi) and propagate with interval arithmetic, so every output is
a range. Status of every output: DERIVED.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import networkx as nx

from nmt_engine.schema import Edge, EdgeCosts

Range = tuple[float, float]
STATUS = "DERIVED"
COST_FIELDS = ("money", "time", "effort", "cognitive", "negative_emotion", "tax_jobs")
DEFAULT_COST_WEIGHTS: dict[str, float] = dict.fromkeys(COST_FIELDS, 1.0)
BREAK_THRESHOLD = 0.5


def r_mul(a: Range, b: Range) -> Range:
    prods = (a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1])
    return (min(prods), max(prods))


def r_add(a: Range, b: Range) -> Range:
    return (a[0] + b[0], a[1] + b[1])


def r_sub(a: Range, b: Range) -> Range:
    return (a[0] - b[1], a[1] - b[0])


def r_scale(a: Range, k: float) -> Range:
    return (min(a[0] * k, a[1] * k), max(a[0] * k, a[1] * k))


def r_max(ranges: Iterable[Range]) -> Range:
    rs = list(ranges)
    return (max(r[0] for r in rs), max(r[1] for r in rs))


def weighted_cost(costs: EdgeCosts | None, weights: Mapping[str, float]) -> Range:
    total: Range = (0.0, 0.0)
    if costs is None:
        return total
    for f in COST_FIELDS:
        total = r_add(total, r_scale(getattr(costs, f), weights.get(f, 0.0)))
    return total


def route_value(
    edges: list[Edge],
    outcome: Range = (1.0, 1.0),
    weights: Mapping[str, float] = DEFAULT_COST_WEIGHTS,
) -> Range:
    """route_value = prod(p_success) x outcome - sum(weighted six costs). Edges without a
    p_success contribute (1, 1): unknown is not evidence of failure."""
    p: Range = (1.0, 1.0)
    cost: Range = (0.0, 0.0)
    for e in edges:
        p = r_mul(p, e.p_success or (1.0, 1.0))
        cost = r_add(cost, weighted_cost(e.costs, weights))
    return r_sub(r_mul(p, outcome), cost)


def added_value(our_route: Range, consideration_routes: Iterable[Range]) -> Range:
    """Our route value minus the best route in the consideration set (interval max)."""
    routes = list(consideration_routes)
    return our_route if not routes else r_sub(our_route, r_max(routes))


def importance(
    nodes: Iterable[str],
    edges: Iterable[Edge],
    freq: Mapping[str, float],
    value: Mapping[str, float],
    alpha: float = 0.85,
) -> dict[str, float]:
    """Weighted PageRank: edge weight = freq x value of the target node; teleport is weighted
    by node freq x value, so frequent, valuable jobs rank high even without edges."""
    g = nx.DiGraph()
    nodes = sorted(set(nodes))
    g.add_nodes_from(nodes)
    for e in sorted(edges, key=lambda e: e.id):
        if e.from_job in g and e.to_job in g:
            w = freq.get(e.to_job, 1.0) * value.get(e.to_job, 1.0)
            prev = g.get_edge_data(e.from_job, e.to_job, {}).get("weight", 0.0)
            g.add_edge(e.from_job, e.to_job, weight=prev + w)
    if not nodes:
        return {}
    pers = {n: max(freq.get(n, 1.0) * value.get(n, 1.0), 1e-12) for n in nodes}
    pr = nx.pagerank(g, alpha=alpha, personalization=pers, weight="weight", tol=1e-12, max_iter=500)
    return {n: round(pr[n], 10) for n in nodes}


@dataclass(frozen=True)
class ChainBreak:
    edge_id: str
    p_success: Range
    certain: bool  # True: hi < threshold; False: threshold inside the range


def critical_breaks(edges: Iterable[Edge], threshold: float = BREAK_THRESHOLD) -> list[ChainBreak]:
    out = []
    for e in sorted(edges, key=lambda e: e.id):
        if e.p_success is None:
            continue
        lo, hi = e.p_success
        if hi < threshold:
            out.append(ChainBreak(e.id, e.p_success, True))
        elif lo < threshold:
            out.append(ChainBreak(e.id, e.p_success, False))
    return out


def layer_views(edges: Iterable[Edge]) -> dict[str, dict[str, list[str]]]:
    views: dict[str, dict[str, set[str]]] = {
        layer: {"nodes": set(), "edges": set()}
        for layer in ("customer", "intermediary", "business", "product")
    }
    for e in edges:
        v = views[e.layer]
        v["edges"].add(e.id)
        v["nodes"] |= {e.from_job, e.to_job}
    return {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in views.items()}
