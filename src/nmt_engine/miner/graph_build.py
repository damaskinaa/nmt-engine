"""Steps 4-5: segment hypotheses and the economic job graph (edges, node weights)."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from nmt_engine.miner.jobs import BuiltJob, jaccard, tokens
from nmt_engine.schema import Claim, Edge, EdgeCosts, Segment, Source, SourceRef
from nmt_engine.util import sha256_text

Z80 = 1.2815515655446004  # standard-normal quantile for an 80% two-sided interval


def wilson(k: int, n: int, z: float = Z80) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(max(0.0, mid - half), 6), round(min(1.0, mid + half), 6))


def criteria_order(bj: BuiltJob) -> list[str]:
    return [
        c.criterion for c in sorted(bj.job.success_criteria, key=lambda c: c.priority_rank or 999)
    ]


def criteria_similarity(a: list[str], b: list[str], top: int = 3) -> float | None:
    """Agreement of two priority orders: shared criteria weighted by rank closeness."""
    a, b = a[:top], b[:top]
    if not a or not b:
        return None
    score = sum(1 / (1 + abs(a.index(c) - b.index(c))) for c in set(a) & set(b))
    return score / max(len(a), len(b))


def job_similarity(x: BuiltJob, y: BuiltJob) -> float:
    s = jaccard(tokens(x.job.statement), tokens(y.job.statement))
    c = criteria_similarity(criteria_order(x), criteria_order(y))
    return s if c is None else 0.5 * s + 0.5 * c


def segments(built: list[BuiltJob], sources: dict[str, Source], cut: float = 0.7) -> list[Segment]:
    """Cluster jobs by similar statement + similar success-criteria priority order (average
    linkage, distance = 1 - similarity, cut at `cut`). Platform/demographics are not used."""
    if not built:
        return []
    n = len(built)
    if n == 1:
        labels = [1]
    else:
        d = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                d[i, j] = d[j, i] = min(1.0, max(0.0, 1 - job_similarity(built[i], built[j])))
        labels = fcluster(linkage(squareform(d), "average"), t=cut, criterion="distance")
    groups: dict[int, list[BuiltJob]] = defaultdict(list)
    for lab, bj in zip(labels, built, strict=True):
        groups[int(lab)].append(bj)
    out = []
    for members in groups.values():
        members.sort(key=lambda b: (-b.voices, b.job.id))
        sids = {i.source_id for b in members for i in b.group.instances}
        srcs = [sources[s] for s in sids]
        voices = len({s.author_hash for s in srcs if s.author_hash})
        kinds = {s.kind for s in srcs}
        crit_voices: dict[str, set[str]] = defaultdict(set)
        for b in members:
            for inst in b.group.instances:
                for label, _ in inst.criteria:
                    crit_voices[label].add(sources[inst.source_id].author_hash or inst.source_id)
        order = sorted(crit_voices, key=lambda c: (-len(crit_voices[c]), c))
        lead = members[0].job
        claim_ids = [c.id for b in members for c in b.claims.values() if not c.single_signal]
        out.append(
            Segment(
                id="seg_" + sha256_text("|".join(sorted(b.job.id for b in members)))[:12],
                name=f"{lead.statement}"
                + (f" (judged by {', '.join(order[:2])})" if order else ""),
                core_job_ids=[b.job.id for b in members],
                criteria_priority_order=order,
                causal_criteria=[c for c in order if len(crit_voices[c]) >= 2],
                qualification_questions=[f"How important is '{c}' to you?" for c in order[:3]],
                claim_ids=claim_ids,
                thin=voices < 2 or len(kinds) < 2 or not claim_ids,
            )
        )
    return sorted(out, key=lambda s: (s.thin, -len(s.core_job_ids), s.id))


def edge_costs(bj: BuiltJob) -> tuple[tuple[float, float], EdgeCosts]:
    """p_success = 1 - Wilson(share of instances reporting a problem or workaround).
    negative_emotion / tax_jobs costs = Wilson share of instances with those spans (0-1 scale).
    Money/time/effort/cognitive are not observable from traces here: left at (0, 0)."""
    insts = bj.group.instances
    n = len(insts)
    fail = sum(1 for i in insts if i.spans.get("problem") or i.spans.get("workaround"))
    lo, hi = wilson(fail, n)
    neg = wilson(sum(1 for i in insts if i.spans.get("negative_emotions")), n)
    tax = wilson(sum(1 for i in insts if i.spans.get("workaround")), n)
    return (round(1 - hi, 6), round(1 - lo, 6)), EdgeCosts(negative_emotion=neg, tax_jobs=tax)


def _reaches(start: str, target: str, by_id: dict[str, BuiltJob]) -> bool:
    """True if following higher_job_id links from `start` arrives at `target` (would cycle)."""
    seen: set[str] = set()
    cur: str | None = start
    while cur and cur not in seen:
        if cur == target:
            return True
        seen.add(cur)
        cur = by_id[cur].job.higher_job_id if cur in by_id else None
    return False


def _edge_id(kind: str, a: str, b: str) -> str:
    return f"e_{kind}_" + sha256_text(f"{a}>{b}")[:12]


@dataclass
class GraphParts:
    edges: list[Edge]
    claims: list[Claim]
    solutions: dict[str, str]  # solution node id -> name


def build_edges(
    built: list[BuiltJob],
    sources: dict[str, Source],
    geo: str,
    text_of: Callable[[Source], str | None] = lambda s: None,
) -> GraphParts:
    by_id = {b.job.id: b for b in built}
    p_cost = {b.job.id: edge_costs(b) for b in built}
    edges: dict[str, Edge] = {}
    support: dict[str, list[str]] = defaultdict(list)

    def add(kind: str, a: str, b: str, layer: str, claim_ids: list[str]) -> None:
        eid = _edge_id(kind, a, b)
        p, costs = p_cost.get(b, (None, None))
        if eid not in edges:
            edges[eid] = Edge(
                id=eid, from_job=a, to_job=b, kind=kind, layer=layer, p_success=p, costs=costs
            )
        support[eid] += claim_ids

    def claim(b: BuiltJob) -> list[str]:
        c = b.claims.get("job") or next(iter(b.claims.values()))
        return [c.id]

    # sequence edges from narrated "first I ... then I ..." orders within one trace
    by_source: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for b in built:
        for inst in b.group.instances:
            if inst.order:
                by_source[inst.source_id].append((inst.order, b.job.id))
    for seq in by_source.values():
        seq = sorted(set(seq))
        for (_, a), (_, z) in zip(seq, seq[1:], strict=False):
            if a != z:
                add("sequence", a, z, "customer", claim(by_id[a]) + claim(by_id[z]))
    # hierarchy edges: a job's higher-goal span names another job
    for b in built:
        goals = [s for i in b.group.instances for s in i.spans.get("higher_goal", [])]
        best, score = None, 0.4
        for other in built:
            if other.job.id == b.job.id or _reaches(other.job.id, b.job.id, by_id):
                continue
            s = max((jaccard(tokens(g), tokens(other.job.statement)) for g in goals), default=0)
            if s >= score:
                best, score = other, s
        if best is not None:
            b.job.higher_job_id = best.job.id
            hc = [b.claims["higher_goal"].id] if "higher_goal" in b.claims else claim(b)
            add("hierarchy", b.job.id, best.job.id, "customer", hc)
    # sequence edges from search query chains (autocomplete / people-also-ask / related)
    query_claims: list[Claim] = []
    for src in sorted(sources.values(), key=lambda s: s.id):
        if src.kind != "search":
            continue
        queries = search_queries(text_of(src) or "")
        mapped = [(q, match_job(q, built)) for q in queries]
        mapped = [(q, j) for q, j in mapped if j]
        for (qa, a), (qz, z) in zip(mapped, mapped[1:], strict=False):
            if a == z:
                continue
            cid = "c_q_" + sha256_text(f"{src.id}|{qa}|{qz}")[:12]
            query_claims.append(
                Claim(
                    id=cid,
                    text=f"query chain '{qa}' -> '{qz}' suggests job order (sequence hypothesis)",
                    status="DERIVED",
                    source_types=["search"],
                    source_refs=[SourceRef(source_id=src.id, verbatim=qa, locator="query")],
                    geography=geo,
                )
            )
            add("sequence", a, z, "customer", [cid])
    # product layer: solutions named in the consideration set perform the job
    solutions: dict[str, str] = {}
    for b in built:
        if "alternatives" not in b.claims:
            continue
        for name in b.job.consideration_set:
            sid = "sol_" + sha256_text(name.lower())[:10]
            solutions.setdefault(sid, name)
            add("performs", sid, b.job.id, "product", [b.claims["alternatives"].id])
    for eid, e in edges.items():
        e.claim_ids = list(dict.fromkeys(support[eid]))
    return GraphParts(sorted(edges.values(), key=lambda e: e.id), query_claims, solutions)


def search_queries(text: str) -> list[str]:
    """Queries in a stored DataForSEO payload, in payload order."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    out: list[str] = []

    def walk(v):
        if isinstance(v, dict):
            for k in sorted(v):
                if k in ("suggestion", "keyword") and isinstance(v[k], str):
                    out.append(v[k])
                elif k in ("paa", "related") and isinstance(v[k], list):
                    out.extend(x for x in v[k] if isinstance(x, str))
                else:
                    walk(v[k])
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(data)
    return list(dict.fromkeys(out))


def match_job(query: str, built: list[BuiltJob], threshold: float = 0.5) -> str | None:
    qt = tokens(query)
    best, score = None, threshold
    for b in built:
        cands = [tokens(b.job.statement)] + [
            tokens(i.search_query) for i in b.group.instances if i.search_query
        ]
        s = max(jaccard(qt, c) for c in cands)
        if s >= score:
            best, score = b.job.id, s
    return best


def solution_counts(built: list[BuiltJob]) -> Counter:
    return Counter(n for b in built for n in b.job.consideration_set)
