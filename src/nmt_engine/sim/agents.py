"""Segment agents: one per L1 segment, grounded by that segment's nearest USER quotes. No
per-person twins (A9); only post ids leave the cache."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from nmt_engine.hypothesis.schema import HypothesisGraph
from nmt_engine.store import load_run
from nmt_engine.verify import gold
from nmt_engine.verify.gold import GOLD_DIR, _read_jsonl

QUOTES = 5
QUOTE_CHARS = 300


@dataclass
class Agent:
    id: str
    segment: str
    jobs: list[str]
    criteria: list[str]
    serves: set[str]
    quote_ids: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)


def _mask(text: str) -> str:
    text = re.sub(r"\S+@\S+", "[email]", text)
    text = re.sub(r"https?://\S+", "[link]", text)
    return " ".join(text.split())[:QUOTE_CHARS]


def user_pool(run_dir: Path, out: Path = GOLD_DIR) -> list[dict]:
    """Posts Kimi labelled USER naming a Solution: L2 harvest posts (`node_authors.jsonl`, with
    dates) and B1 gold posts (`gold.jsonl`, no date, so never used in a replay)."""
    run = load_run(Path(run_dir))
    pool, seen = [], set()
    auth_f = out / "node_authors.jsonl"
    for a in _read_jsonl(auth_f) if auth_f.is_file() else []:
        s = run.sources.get(a["source_id"])
        if s is None or a["role"] != "USER" or not a["names_solution"] or s.id in seen:
            continue
        text = (Path(run_dir) / s.text_path).read_text("utf-8")
        pool.append({"id": s.id, "text": _mask(text), "published": s.published_at})
        seen.add(s.id)
    texts = {p.id: p.text for p in gold.load_posts()}
    for g in _read_jsonl(out / "gold.jsonl"):
        ok = g["role"] == "USER" and g["names_solution"] and g["id"] in texts
        if ok and g["source_id"] not in seen:
            pool.append({"id": g["source_id"], "text": _mask(texts[g["id"]]), "published": None})
            seen.add(g["source_id"])
    return sorted(pool, key=lambda p: p["id"])


def build(
    graph: HypothesisGraph, emb, pool: list[dict], before: datetime | None = None
) -> list[Agent]:
    nodes = {n.id: n for n in graph.nodes}
    segs = [n for n in graph.nodes if n.type == "segment"]
    if before is not None:
        pool = [p for p in pool if p["published"] is not None and p["published"] < before]
    pv = emb.embed([p["text"] for p in pool], "sim.agents.pool") if pool else None
    sv = emb.embed([s.text for s in segs], "sim.agents.segment")
    agents = []
    for s, v in zip(segs, sv, strict=True):
        a = Agent(
            id=s.id,
            segment=s.text,
            jobs=[nodes[j].text for j in s.core_jobs],
            criteria=[nodes[c].text for c in s.criteria_order],
            serves=set(s.core_jobs),
        )
        if pv is not None:
            sims = pv @ v
            order = sorted(range(len(pool)), key=lambda i: (-sims[i], pool[i]["id"]))[:QUOTES]
            a.quote_ids = [pool[i]["id"] for i in order]
            a.quotes = [pool[i]["text"] for i in order]
        agents.append(a)
    return agents


def incumbents(graph: HypothesisGraph, agent: Agent) -> list[str]:
    """L1 Solutions whose `serves` overlaps the agent's Core Jobs."""
    return [
        n.id for n in graph.nodes if n.type == "solution" and agent.serves & set(n.serves or [])
    ]
