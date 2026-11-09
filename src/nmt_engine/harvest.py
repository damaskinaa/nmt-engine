"""L2 targeted harvest (ARCHITECTURE_v3 §3 L2, PREREG_v3 §5): queries come from the 10 riskiest
nodes, in customer words. Code writes the template queries for named Solutions ("alternative to
X", "switched from X", "X too expensive", "X vs Y"); the producer adds short searches per node
("how do I <job>"). The six L2 collectors run each query; every new source records the queries and
nodes that found it."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from itertools import combinations
from pathlib import Path

import httpx

from nmt_engine.collect import appstore, github, hackernews, stackexchange, wayback, web
from nmt_engine.collect.base import Collector, MissingKeyError, env, operator_hosts
from nmt_engine.hypothesis.schema import HypothesisGraph
from nmt_engine.llm import LLM, LLMError
from nmt_engine.util import canonical_json, sha256_text

STACK_SITES = ("freelancing", "money", "webapps")  # keyless quota: 300 requests a day
QUERY_WORDS = (2, 7)
QUERIES_PER_NODE = 3

QUERY_SYSTEM = (
    "You write short web-forum searches in the words customers use. You never invent product "
    "names or numbers. Output JSON only."
)

QUERY_PROMPT = """Market Job: {market_job}

For each statement below, write {k} short searches (2 to 7 words each) that would find forum \
posts, questions or reviews where people talk about it in their own words. Use plain customer \
words, for example "how do I ..." for a task, or the words someone uses when complaining. No \
quotation marks, no product names unless the statement names them, no numbers.

Statements:
{statements}

Return {{"queries": [{{"node": "<statement id>", "searches": ["...", ...]}}, ...]}}."""


@dataclass(frozen=True)
class Query:
    text: str
    nodes: tuple[str, ...]
    origin: str  # "template" or "producer"


def solution_names(text: str) -> list[str]:
    """Product names a Solution node gives as examples: "... such as QuickBooks or Xero"."""
    m = re.search(r"\bsuch as (.+)$", text)
    if not m:
        return []
    return [n.strip(" .") for n in re.split(r",| or | and ", m.group(1)) if n.strip(" .")]


def template_queries(g: HypothesisGraph, riskiest: list[str]) -> list[Query]:
    by_id = {n.id: n for n in g.nodes}
    names = {n.id: solution_names(n.text) for n in g.nodes if n.type == "solution"}
    every = sorted({x for v in names.values() for x in v})
    out = []
    for nid in riskiest:
        for x in names.get(nid, []):
            for t in (f"alternative to {x}", f"switched from {x}", f"{x} too expensive"):
                out.append(Query(t, (nid,), "template"))
            for a, b in combinations(every, 2):
                if x in (a, b) and by_id[nid].type == "solution":
                    out.append(Query(f"{a} vs {b}", (nid,), "template"))
    return out


def _clean(q: object) -> str | None:
    if not isinstance(q, str):
        return None
    q = " ".join(q.replace('"', " ").split())
    lo, hi = QUERY_WORDS
    if not lo <= len(q.split()) <= hi or re.search(r"\d", q):
        return None
    return q.lower()


def producer_queries(
    llm: LLM, g: HypothesisGraph, riskiest: list[str], stmts: dict[str, str]
) -> list[Query]:
    prompt = QUERY_PROMPT.format(
        market_job=g.nodes[0].text if g.nodes else "",
        k=QUERIES_PER_NODE,
        statements="\n".join(f"{i}: {stmts[i]}" for i in riskiest),
    )
    raw = llm.complete_json(prompt, QUERY_SYSTEM, "l2.queries")
    rows = raw.get("queries") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise LLMError("no queries list")
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get("node") not in riskiest:
            continue
        for s in (r.get("searches") or [])[:QUERIES_PER_NODE]:
            if q := _clean(s):
                out.append(Query(q, (r["node"],), "producer"))
    return out


def merge(queries: list[Query]) -> list[Query]:
    """One query per text; its nodes are the union, in first-seen order."""
    seen: dict[str, Query] = {}
    for q in queries:
        k = q.text.lower()
        if k in seen:
            old = seen[k]
            nodes = old.nodes + tuple(n for n in q.nodes if n not in old.nodes)
            seen[k] = Query(old.text, nodes, old.origin)
        else:
            seen[k] = q
    return list(seen.values())


@dataclass
class HarvestPlan:
    brief_hash: str
    riskiest: list[str]
    queries: list[Query]
    apps: list[str]
    competitors: list[str] = field(default_factory=list)
    app_countries: list[str] = field(default_factory=lambda: ["us", "gb", "ie"])
    since: str = "2023-01-01"
    geo: str = "IE"
    per_query: int = 30

    @property
    def hash(self) -> str:
        return sha256_text(canonical_json(self.as_dict()))[:16]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["queries"] = [
            {"text": q.text, "nodes": list(q.nodes), "origin": q.origin} for q in self.queries
        ]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> HarvestPlan:
        qs = [Query(q["text"], tuple(q["nodes"]), q["origin"]) for q in d["queries"]]
        return cls(
            **{**{k: v for k, v in d.items() if k not in ("queries", "hash")}, "queries": qs}
        )


def plan(
    llm: LLM | None,
    g: HypothesisGraph,
    brief_hash: str,
    riskiest: list[str],
    stmts: dict[str, str],
    competitors: list[str] = (),
    since: str = "2023-01-01",
    apps: list[str] = (),
) -> HarvestPlan:
    qs = template_queries(g, riskiest)
    if llm is not None:
        qs += producer_queries(llm, g, riskiest, stmts)
    named = {x for n in g.nodes if n.type == "solution" for x in solution_names(n.text)}
    apps = sorted(named | set(apps))
    return HarvestPlan(
        brief_hash, list(riskiest), merge(qs), apps, competitors=list(competitors), since=since
    )


def _steps(p: HarvestPlan) -> list[tuple[str, tuple[str, ...], Callable[[Collector], list]]]:
    since, n = date.fromisoformat(p.since), p.per_query
    steps = []
    for q in p.queries:
        t = q.text
        steps.append(
            (f"hackernews:{t}", q.nodes, lambda c, t=t: hackernews.collect(c, t, since, n))
        )
        for site in STACK_SITES:
            steps.append(
                (
                    f"stackexchange:{site}:{t}",
                    q.nodes,
                    lambda c, t=t, s=site: stackexchange.collect(
                        c, t, since, s, n // 3, similar=True
                    ),
                )
            )
        steps.append((f"github:{t}", q.nodes, lambda c, t=t: github.issues(c, t, since, n // 3)))
    for a in p.apps:
        for cc in p.app_countries:
            steps.append(
                (
                    f"appstore:{cc}:{a}",
                    (),
                    lambda c, a=a, cc=cc: appstore.named_app(c, a, cc, 10, since),
                )
            )
    for d in p.competitors:
        steps.append((f"web:{d}", (), lambda c, d=d: web.competitor_pages(c, d)))
        steps.append(
            (f"wayback:{d}", (), lambda c, d=d: wayback.collect(c, f"{d}/pricing", since, 12))
        )
    return steps


BREAKER = 3  # consecutive errors (e.g. an exhausted daily quota) before an adapter is skipped


def run(p: HarvestPlan, run_dir: Path, collector: Collector | None = None) -> dict:
    """Run every step; failures are recorded, not fatal. Writes `harvest_summary.json` and
    `harvest_hits.jsonl` (source id -> the queries and nodes that found it)."""
    run_dir = Path(run_dir)
    if collector is None and not env("NMT_AUTHOR_SALT"):
        raise MissingKeyError("set $NMT_AUTHOR_SALT so author hashes are salted and reproducible")
    c = collector or Collector(
        run_dir,
        geo=p.geo,
        salt=env("NMT_AUTHOR_SALT"),
        extra_hosts=operator_hosts(p.competitors),
    )
    (run_dir / "harvest_plan.json").write_text(
        json.dumps({**p.as_dict(), "hash": p.hash}, indent=1), "utf-8"
    )
    hits: dict[str, dict] = {}
    steps: dict[str, dict] = {}
    fails: dict[str, int] = {}
    for name, nodes, step in _steps(p):
        adapter = name.split(":", 1)[0]
        if fails.get(adapter, 0) >= BREAKER:
            steps[name] = {"status": "skipped", "reason": f"{adapter}: {BREAKER} errors in a row"}
            continue
        try:
            found = step(c)
            steps[name] = {"status": "ok", "sources": len(found)}
        except MissingKeyError as exc:
            steps[name], found = {"status": "skipped", "reason": str(exc)}, []
        except appstore.NoApp as exc:
            steps[name], found = {"status": "none", "reason": str(exc)}, []
        except (httpx.HTTPError, ValueError, KeyError, PermissionError) as exc:
            steps[name], found = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}, []
        fails[adapter] = fails.get(adapter, 0) + 1 if steps[name]["status"] == "error" else 0
        for s in found:
            h = hits.setdefault(s.id, {"source_id": s.id, "queries": [], "nodes": []})
            h["queries"].append(name)
            h["nodes"] += [x for x in nodes if x not in h["nodes"]]
    with (run_dir / "harvest_hits.jsonl").open("w", encoding="utf-8") as f:
        for h in sorted(hits.values(), key=lambda h: h["source_id"]):
            f.write(json.dumps(h, sort_keys=True) + "\n")
    live = [s for s in c.store.current("source").values() if not s.retracted]
    fam: dict[str, int] = {}
    for s in live:
        fam[s.evidence_family] = fam.get(s.evidence_family, 0) + 1
    summary = {
        "plan_hash": p.hash,
        "steps": steps,
        "status_counts": {
            k: sum(v["status"] == k for v in steps.values())
            for k in ("ok", "skipped", "none", "error")
        },
        "sources": len(live),
        "sources_by_family": dict(sorted(fam.items())),
        "customer_voice": sum(1 for s in live if s.customer_voice),
    }
    (run_dir / "harvest_summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
    return summary
