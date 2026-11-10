"""Segment agents: one per L1 segment, grounded by that segment's nearest USER quotes. No
per-person twins (A9); only post ids leave the cache. Calibration (PREREG amendment 6 rule 3):
up to 2 of the B3 supporting posts first, then the pool by cosine x weight, where a problem tag
(measured) weighs 1.0, only unmeasured tags 0.6 and no tag 0.5."""

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
SUPPORT_SLOTS = 2
MEASURED = ("problem",)
UNMEASURED = ("trigger", "success_criterion", "alternative", "aha")
WEIGHT = {"measured": 1.0, "unmeasured": 0.6, "none": 0.5}


@dataclass
class Agent:
    id: str
    segment: str
    jobs: list[str]
    criteria: list[str]
    serves: set[str]
    quote_ids: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    calibration: list[dict] = field(default_factory=list)


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
        pool.append({"id": s.id, "text": _mask(text), "published": s.published_at, "tags": None})
        seen.add(s.id)
    texts = {p.id: p.text for p in gold.load_posts()}
    for g in _read_jsonl(out / "gold.jsonl"):
        ok = g["role"] == "USER" and g["names_solution"] and g["id"] in texts
        if ok and g["source_id"] not in seen:
            tags = {k: bool(v) for k, v in g["elements"].items()}
            pool.append(
                {
                    "id": g["source_id"],
                    "text": _mask(texts[g["id"]]),
                    "published": None,
                    "tags": tags,
                    "tagged_by": "kimi-gold",
                }
            )
            seen.add(g["source_id"])
    return sorted(pool, key=lambda p: p["id"])


def supporting(out: Path = GOLD_DIR) -> dict[str, str]:
    """source id -> node for the B3 designated pairs Kimi labelled supports (amendment 3)."""
    from nmt_engine.verify import node_gold

    items = node_gold._items(out)
    return {
        items[i]["source_id"]: n for i, n, _sp, v in node_gold._designated(out) if v == "supports"
    }


def tag_pool(llm, pool: list[dict], category: str) -> None:
    """Producer element tags (DeepSeek, as recorded for T1) for pool posts without Kimi tags."""
    from nmt_engine.verify.author import Post, tag_elements

    todo = [p for p in pool if p.get("tags") is None]
    if not todo:
        return
    got = tag_elements(llm, [Post(p["id"], category, p["text"]) for p in todo], "sim.agents.tags")
    for p, t in zip(todo, got, strict=True):
        p["tags"], p["tagged_by"] = t, "producer"


def weight_class(tags: dict | None) -> str:
    tags = tags or {}
    if any(tags.get(k) for k in MEASURED):
        return "measured"
    return "unmeasured" if any(tags.get(k) for k in UNMEASURED) else "none"


def build(
    graph: HypothesisGraph,
    emb,
    pool: list[dict],
    before: datetime | None = None,
    support: dict[str, str] | None = None,
) -> list[Agent]:
    nodes = {n.id: n for n in graph.nodes}
    segs = [n for n in graph.nodes if n.type == "segment"]
    support = support or {}
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
            near = sorted(range(len(pool)), key=lambda i: (-sims[i], pool[i]["id"]))
            mine = set(s.core_jobs) | set(incumbents(graph, a))
            first = [i for i in near if support.get(pool[i]["id"]) in mine][:SUPPORT_SLOTS]
            rest = sorted(
                (i for i in range(len(pool)) if i not in first),
                key=lambda i: (-sims[i] * WEIGHT[weight_class(pool[i].get("tags"))], pool[i]["id"]),
            )
            order = (first + rest)[:QUOTES]
            a.quote_ids = [pool[i]["id"] for i in order]
            a.quotes = [pool[i]["text"] for i in order]
            a.calibration = [_calib(pool[i], support, float(sims[i])) for i in order]
        agents.append(a)
    return agents


def _calib(p: dict, support: dict[str, str], cos: float) -> dict:
    tags = p.get("tags") or {}
    wc = weight_class(tags)
    return {
        "id": p["id"],
        "measured_on": ["USER"] + [k for k in MEASURED if tags.get(k)],
        "unmeasured": [k for k in UNMEASURED if tags.get(k)],
        "supports": support.get(p["id"]),
        "weight": None if p["id"] in support else WEIGHT[wc],
        "tagged_by": p.get("tagged_by"),
        "cosine": round(cos, 4),
    }


def calibration_record(graph: HypothesisGraph, agents: list[Agent]) -> dict:
    """What the simulation was grounded on (amendment 6 rule 3), for the ledger and report."""
    return {
        "measured": {
            "USER": "PASS, precision against Kimi model labels (B3 T1)",
            "problem": "PASS, precision against Kimi model labels (B3 T1)",
            "supporting_posts": "4 B3 designated supporting pairs, below the L4 bar",
        },
        "unmeasured_low_weight": list(UNMEASURED),
        "weights": WEIGHT,
        "unmeasured_structure": "segments, Core Jobs and criteria order from the L1 hypothesis "
        "graph (0 of 10 riskiest nodes supported)",
        "agents": {a.id: a.calibration for a in agents},
    }


def incumbents(graph: HypothesisGraph, agent: Agent) -> list[str]:
    """L1 Solutions whose `serves` overlaps the agent's Core Jobs."""
    return [
        n.id for n in graph.nodes if n.type == "solution" and agent.serves & set(n.serves or [])
    ]
