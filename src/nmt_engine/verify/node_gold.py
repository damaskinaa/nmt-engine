"""Node-check gold and test growth (PREREG_v3 amendment 1).

Gold items are the gold posts Kimi labels USER and naming a Solution, crossed with the 10 riskiest
nodes; a pair takes its post's split. Growth adds 150 L2 posts per round, all to test, labelled by
Kimi with the frozen prompts. A class's test calls are the producer's answers of that class on
test pairs Kimi answered; fewer than MIN_CALLS is NOT MEASURED, never a pass."""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from nmt_engine.collect.run import collector_on
from nmt_engine.hypothesis import generate
from nmt_engine.hypothesis.schema import HypothesisGraph
from nmt_engine.llm import LLM, PRODUCER
from nmt_engine.store import load_run
from nmt_engine.util import canonical_json, repo_root, sha256_text
from nmt_engine.verify import gold, node, prompts
from nmt_engine.verify.author import ROUNDS, Post
from nmt_engine.verify.gold import (
    CACHE_DIR,
    GOLD_DIR,
    GOLD_ROUNDS,
    MIN_CALLS,
    PRECISION_MIN,
    PRODUCER_REASONING,
    _clip,
    _prec,
    _read_jsonl,
    _short,
    _write_jsonl,
)

GRAPH = repo_root() / "briefs" / "invoicing.l1.json"
NODE_BATCH = 4
GROW_N = 150
GROW_ROUNDS_MAX = 6
T1_GATING = ("USER", "supports", "contradicts")
NODE_CLASSES = ("supports", "contradicts")


def candidates(path: Path = GRAPH) -> tuple[HypothesisGraph, list[str]]:
    frozen = json.loads(path.read_text("utf-8"))
    return generate.load(path), [r["id"] for r in frozen["riskiest"]]


def _stmts(path: Path = GRAPH) -> dict[str, str]:
    g, ids = candidates(path)
    return node.statements(g, ids)


def _hash(system: str, prompt: str, extra: dict, path: Path) -> str:
    return sha256_text(
        canonical_json({"node": [system, prompt], "statements": _stmts(path), **extra})
    )[:16]


def label_prompt_hash(path: Path = GRAPH) -> str:
    return _hash(
        prompts.GOLD_NODE_SYSTEM,
        prompts.GOLD_NODE_PROMPT,
        {"batch": NODE_BATCH, "rounds": GOLD_ROUNDS},
        path,
    )


def prompt_hash(
    model: str = PRODUCER, reasoning: str | None = PRODUCER_REASONING, path: Path = GRAPH
) -> str:
    return _hash(
        prompts.NODE_SYSTEM,
        prompts.NODE_PROMPT,
        {"batch": NODE_BATCH, "model": model, "reasoning_effort": reasoning},
        path,
    )


def _eligible(out: Path) -> list[dict]:
    """Gold posts Kimi calls USER and naming a Solution (§8 A4)."""
    return [
        g for g in _read_jsonl(out / "gold.jsonl") if g["role"] == "USER" and g["names_solution"]
    ]


def _posts(ids: set[str]) -> list[Post]:
    return [p for p in gold.load_posts() if p.id in ids]


def label(llm: LLM, out: Path = GOLD_DIR, path: Path = GRAPH) -> dict:
    """Kimi node labels for eligible posts not labelled yet; unanswered posts stay null."""
    f = out / "node_gold.jsonl"
    done = {r["id"]: r for r in _read_jsonl(f)} if f.is_file() else {}
    lh = label_prompt_hash(path)
    todo = [g for g in _eligible(out) if g["id"] not in done]
    if todo:
        posts = _posts({g["id"] for g in todo})
        ans = node.node_check(
            llm, posts, _stmts(path), "gold.node", NODE_BATCH, GOLD_ROUNDS, gold=True
        )
        quotes_f = CACHE_DIR / "node_gold_quotes.jsonl"
        quotes = _read_jsonl(quotes_f) if quotes_f.is_file() else []
        split = {g["id"]: g["split"] for g in todo}
        for p, a in zip(posts, ans, strict=True):
            done[p.id] = {
                "id": p.id,
                "split": split[p.id],
                "verdicts": {k: v["verdict"] for k, v in a.items()} if a else None,
                "labeller": llm.model,
                "label_prompt_hash": lh,
            }
            if a:  # quotes can carry names, so they stay in the gitignored cache (§8 A9)
                quotes.append({"id": p.id, "quotes": {k: _short(v["quote"]) for k, v in a.items()}})
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _write_jsonl(quotes_f, quotes)
    _write_jsonl(f, sorted(done.values(), key=lambda r: r["id"]))
    return {
        "posts": len(done),
        "labelled": sum(r["verdicts"] is not None for r in done.values()),
        "new": len(todo),
    }


def record(llm: LLM, out: Path = GOLD_DIR, path: Path = GRAPH) -> Path:
    """Producer node answers on every eligible post, committed under the node prompt hash."""
    ids = {r["id"] for r in _read_jsonl(out / "node_gold.jsonl")}
    posts = sorted(_posts(ids), key=lambda p: p.id)
    ans = node.node_check(llm, posts, _stmts(path), "gold.node.record", NODE_BATCH, ROUNDS)
    h = prompt_hash(llm.model, llm.reasoning_effort, path)
    rec = out / "recorded" / f"node-{h}.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "prompt_hash": h,
        "model": llm.model,
        "host": llm.host,
        "reasoning_effort": llm.reasoning_effort,
        "answers": {
            p.id: ({k: v["verdict"] for k, v in a.items()} if a else None)
            for p, a in zip(posts, ans, strict=True)
        },
    }
    rec.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", "utf-8")
    return rec


def check_nodes(out: Path = GOLD_DIR, phash: str | None = None, path: Path = GRAPH) -> dict:
    """Producer supports / contradicts precision against Kimi node labels, per split."""
    phash = phash or prompt_hash(path=path)
    rec_f = out / "recorded" / f"node-{phash}.json"
    gold_f = out / "node_gold.jsonl"
    if not gold_f.is_file() or not rec_f.is_file():
        return {"prompt_hash": phash, "classes": {}, "error": f"no node recording for {phash}"}
    rec = json.loads(rec_f.read_text("utf-8"))["answers"]
    res: dict = {"prompt_hash": phash, "classes": {}}
    rows = [r for r in _read_jsonl(gold_f) if r["verdicts"] is not None]
    for split in ("dev", "test"):
        pairs = [
            ((rec.get(r["id"]) or {}).get(n), v)
            for r in rows
            if r["split"] == split
            for n, v in r["verdicts"].items()
        ]
        for c in NODE_CLASSES:
            res["classes"].setdefault(c, {})[split] = _prec(
                [p for p, _ in pairs], [g for _, g in pairs], c
            )
    res["pairs"] = {
        s: sum(len(r["verdicts"]) for r in rows if r["split"] == s) for s in ("dev", "test")
    }
    return res


def t1(out: Path = GOLD_DIR) -> dict:
    """T1 (§5): author-gate and element classes from `gold.check`, node classes from
    `check_nodes`. T2 may run only if USER, supports and contradicts each PASS."""
    res = gold.check(out)
    nodes = check_nodes(out)
    if "error" in nodes:
        res.setdefault("errors", []).append(nodes["error"])
    res["node_prompt_hash"] = nodes["prompt_hash"]
    res["node_pairs"] = nodes.get("pairs")
    for k, c in nodes["classes"].items():
        t = c["test"]
        if t["called"] < MIN_CALLS:
            t["status"] = "NOT MEASURED"
        else:
            t["status"] = "PASS" if t["precision"] >= PRECISION_MIN else "FAIL"
        res["classes"][k] = c
    status = {k: c["test"]["status"] for k, c in res["classes"].items()}
    res["t1_passed_for"] = sorted(k for k, v in status.items() if v == "PASS")
    res["not_measured"] = sorted(k for k, v in status.items() if v == "NOT MEASURED")
    res["t2_may_run"] = all(status.get(k) == "PASS" for k in T1_GATING)
    res["passed"] = "FAIL" not in status.values() and not res.get("errors") and "error" not in res
    res["basis"] = "precision against model labels (Kimi), not human-verified"
    return res


def grow(run_dir: Path, round_: int, out: Path = GOLD_DIR, n: int = GROW_N) -> dict:
    """Add up to `n` L2 customer-voice posts to the test split, stratified by evidence family,
    seeded with the round number. Skips posts already in gold (same source id or URL)."""
    if not 1 <= round_ <= GROW_ROUNDS_MAX:
        raise ValueError(f"round must be 1..{GROW_ROUNDS_MAX}")
    items = _read_jsonl(out / "items.jsonl")
    if any(it.get("round") == round_ for it in items):
        raise ValueError(f"round {round_} already grown")
    seen_ids = {it["source_id"] for it in items}
    seen_urls = {it["url"] for it in items}
    run = load_run(run_dir)
    pool = sorted(
        (
            s
            for s in run.sources.values()
            if not s.retracted
            and s.customer_voice
            and collector_on(s.platform, {})
            and s.id not in seen_ids
            and s.url not in seen_urls
        ),
        key=lambda s: s.id,
    )
    if not pool:
        return {"round": round_, "added": 0, "pool": 0}
    rng = random.Random(round_)
    n = min(n, len(pool))
    fam = Counter(s.evidence_family for s in pool)
    quota = {f: min(c, round(n * c / len(pool))) for f, c in fam.items()}
    quota[max(quota, key=quota.get)] += n - sum(quota.values())
    chosen = []
    for f in sorted(quota):
        chosen += rng.sample([s for s in pool if s.evidence_family == f], quota[f])
    rng.shuffle(chosen)
    category = gold.load_posts()[0].category
    start = len(items)
    rows, posts = [], []
    for i, s in enumerate(chosen):
        gid = f"G{start + i + 1:03d}"
        rows.append(
            {
                "id": gid,
                "source_id": s.id,
                "url": s.url,
                "platform": s.platform,
                "family": s.evidence_family,
                "split": "test",
                "round": round_,
            }
        )
        text = _clip((Path(run_dir) / s.text_path).read_text("utf-8"))
        posts.append({"id": gid, "category": category, "text": text})
    _write_jsonl(out / "items.jsonl", items + rows)
    _write_jsonl(CACHE_DIR / "posts.jsonl", _read_jsonl(CACHE_DIR / "posts.jsonl") + posts)
    return {
        "round": round_,
        "added": len(rows),
        "pool": len(pool),
        "by_family": dict(sorted(Counter(r["family"] for r in rows).items())),
    }


__all__ = ["check_nodes", "grow", "label", "record", "t1"]
