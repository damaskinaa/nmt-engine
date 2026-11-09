"""Node-check gold and test growth (PREREG_v3 amendment 1).

Gold items are the gold posts Kimi labels USER and naming a Solution, crossed with the 10 riskiest
nodes; a pair takes its post's split. Growth adds 150 L2 posts per round, all to test, labelled by
Kimi with the frozen prompts. A class's test calls are the producer's answers of that class on
test pairs Kimi answered; fewer than MIN_CALLS is NOT MEASURED, never a pass."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from nmt_engine.collect.run import collector_on
from nmt_engine.config import repo_root
from nmt_engine.hypothesis import generate
from nmt_engine.hypothesis.schema import HypothesisGraph
from nmt_engine.llm import LLM, PRODUCER
from nmt_engine.stats import agreement, cohen_kappa
from nmt_engine.store import load_run
from nmt_engine.util import canonical_json, sha256_text
from nmt_engine.verify import gold, node, prompts
from nmt_engine.verify.author import ROUNDS, Post, author_gate
from nmt_engine.verify.gold import (
    BATCH,
    CACHE_DIR,
    CROSS_MIN,
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


PICK_TOP = 8
PICK_NEG = 2
PICK_DEPTH = 60
ITEMS = "node_items.jsonl"
AUTHORS = "node_authors.jsonl"
NODE_POSTS = CACHE_DIR / "node_posts.jsonl"

# Amendment 2 canaries: synthetic, never scored for T1. (id, node, expected verdict, text)
CANARIES = [
    (
        "C1",
        "J4",
        "supports",
        "I've used FreshBooks for three years. What I care about most is getting clients to pay "
        "without souring things, so I always send a friendly nudge rather than a demand. Keeping "
        "the relationship good matters more to me than being paid a week earlier.",
    ),
    (
        "C2",
        "J12",
        "supports",
        "With Wave I kept missing due dates. What I really want is a warning a few days before an "
        "invoice goes overdue, so I can check in with the client before it is late.",
    ),
    (
        "C3",
        "S2",
        "contradicts",
        "I tried Bonsai for a month and then cancelled it. I don't use any invoicing app now: I "
        "write my invoices in Word, email them myself, and check my bank account to see who paid.",
    ),
    (
        "C4",
        "J5",
        "contradicts",
        "I invoice through Xero. I never keep records of what was agreed with a client: they all "
        "pay on receipt, there has never been a dispute, and I delete old quotes once paid.",
    ),
    (
        "C5",
        "J2",
        "unrelated",
        "I moved from QuickBooks to Xero because QuickBooks raised its price again. The bank "
        "feeds in Xero are nicer and the reconciliation screen is faster.",
    ),
    (
        "C6",
        "J11",
        "unrelated",
        "Harvest's mobile app crashes whenever I upload a receipt photo for expenses, and support "
        "took a week to answer my ticket.",
    ),
]


def _category() -> str:
    return gold.load_posts()[0].category


def canary(llm: LLM, out: Path = GOLD_DIR, path: Path = GRAPH) -> dict:
    """Run the frozen gold node prompt on the synthetic canaries. `ok` is False if any obvious
    supports / contradicts / unrelated comes back wrong (then the prompt is broken)."""
    cat = _category()
    posts = [Post(cid, cat, text) for cid, _, _, text in CANARIES]
    ans = node.node_check(
        llm, posts, _stmts(path), "gold.node.canary", NODE_BATCH, GOLD_ROUNDS, gold=True
    )
    rows = [
        {"id": cid, "node": n, "expected": exp, "got": (a or {}).get(n, {}).get("verdict")}
        for (cid, n, exp, _), a in zip(CANARIES, ans, strict=True)
    ]
    res = {
        "label_prompt_hash": label_prompt_hash(path),
        "labeller": llm.model,
        "canaries": rows,
        "ok": all(r["got"] == r["expected"] for r in rows),
    }
    (out / "node_canary.json").write_text(json.dumps(res, indent=1) + "\n", "utf-8")
    return res


def split_of(source_id: str) -> str:
    return "test" if int(sha256_text(source_id), 16) % 2 else "dev"


def ranks(run_dir: Path, node_ids: Sequence[str]) -> dict[str, list[str]]:
    """Per node, the customer-voice posts its queries retrieved, best (lowest) rank first."""
    run_dir = Path(run_dir)
    plan = json.loads((run_dir / "harvest_plan.json").read_text("utf-8"))
    nodes_of = {q["text"]: q["nodes"] for q in plan["queries"]}
    run = load_run(run_dir)
    pool = {
        s.id
        for s in run.sources.values()
        if not s.retracted and s.customer_voice and collector_on(s.platform, {})
    }
    best: dict[str, dict[str, int]] = {n: {} for n in node_ids}
    for h in _read_jsonl(run_dir / "harvest_hits.jsonl"):
        if h["source_id"] not in pool:
            continue
        for name, r in (h.get("ranks") or {}).items():
            adapter, rest = name.split(":", 1)
            if adapter == "stackexchange":
                rest = rest.split(":", 1)[1]
            for n in nodes_of.get(rest, ()):
                if n in best:
                    b = best[n]
                    b[h["source_id"]] = min(r, b.get(h["source_id"], r))
    return {n: sorted(b, key=lambda s, b=b: (b[s], s)) for n, b in best.items()}


def _qualifies(a: dict | None) -> bool:
    return bool(a and a.get("role") == "USER" and a.get("names_solution"))


def pick(
    llm: LLM, run_dir: Path, round_: int = 0, out: Path = GOLD_DIR, path: Path = GRAPH
) -> dict:
    """Amendment 2: per node, Kimi labels author role down the node's ranked candidates until
    PICK_TOP qualify (USER naming a Solution) or PICK_DEPTH are seen; then designates the top
    PICK_TOP plus PICK_NEG random qualifying negatives. Round 0 splits by post id; growth rounds
    go to test."""
    if not 0 <= round_ <= GROW_ROUNDS_MAX:
        raise ValueError(f"round must be 0..{GROW_ROUNDS_MAX}")
    items_f, auth_f = out / ITEMS, out / AUTHORS
    items = _read_jsonl(items_f) if items_f.is_file() else []
    if any(it["round"] == round_ for it in items):
        raise ValueError(f"round {round_} already picked")
    used = {it["source_id"] for it in items}
    auth = {r["source_id"]: r for r in _read_jsonl(auth_f)} if auth_f.is_file() else {}
    _, node_ids = candidates(path)
    run = load_run(Path(run_dir))
    allranked = ranks(run_dir, node_ids)
    order = {n: [s for s in v if s not in used][:PICK_DEPTH] for n, v in allranked.items()}
    cat = _category()

    def post(sid: str) -> Post:
        s = run.sources[sid]
        return Post(sid, cat, _clip((Path(run_dir) / s.text_path).read_text("utf-8")))

    lh = gold.label_prompt_hash()
    while True:
        want: list[str] = []
        for n in node_ids:
            if sum(_qualifies(auth.get(s)) for s in order[n]) >= PICK_TOP:
                continue
            want += [s for s in order[n] if s not in auth and s not in want][:PICK_TOP]
        if not want:
            break
        posts = [post(s) for s in want]
        ans = author_gate(llm, posts, "gold.node.author", BATCH, rounds=GOLD_ROUNDS, gold=True)
        for p, a in zip(posts, ans, strict=True):
            auth[p.id] = {
                "source_id": p.id,
                "role": a.role if a else None,
                "names_solution": a.names_solution if a else None,
                "labeller": llm.model,
                "label_prompt_hash": lh,
            }
        _write_jsonl(auth_f, sorted(auth.values(), key=lambda r: r["source_id"]))

    pairs: dict[str, dict[str, str]] = {}
    top = {n: [s for s in order[n] if _qualifies(auth.get(s))][:PICK_TOP] for n in node_ids}
    for n, ss in top.items():
        for s in ss:
            pairs.setdefault(s, {})[n] = "top"
    qual = sorted(s for s, a in auth.items() if _qualifies(a) and s not in used)
    negs: dict[str, list[str]] = {}
    for n in node_ids:
        seen = set(allranked[n])
        pool = [s for s in qual if s not in seen] or [s for s in qual if s not in top[n]]
        negs[n] = random.Random(f"{round_}:{n}").sample(pool, min(PICK_NEG, len(pool)))
        for s in negs[n]:
            pairs.setdefault(s, {}).setdefault(n, "neg")
    rows, posts_c = [], _read_jsonl(NODE_POSTS) if NODE_POSTS.is_file() else []
    for i, sid in enumerate(sorted(pairs)):
        s = run.sources[sid]
        nid = f"N{len(items) + i + 1:03d}"
        rows.append(
            {
                "id": nid,
                "source_id": sid,
                "url": s.url,
                "platform": s.platform,
                "family": s.evidence_family,
                "split": split_of(sid) if round_ == 0 else "test",
                "round": round_,
                "pairs": dict(sorted(pairs[sid].items())),
            }
        )
        posts_c.append({"id": nid, "category": cat, "text": post(sid).text})
    _write_jsonl(items_f, items + rows)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _write_jsonl(NODE_POSTS, posts_c)
    return {
        "round": round_,
        "items": len(rows),
        "pairs": sum(len(r["pairs"]) for r in rows),
        "authors_labelled": len(auth),
        "per_node": {
            n: {"top": len(top[n]), "neg": len(negs[n]), "ranked": len(allranked[n])}
            for n in node_ids
        },
    }


def _items(out: Path) -> dict[str, dict]:
    f = out / ITEMS
    return {r["id"]: r for r in _read_jsonl(f)} if f.is_file() else {}


def _posts(ids: set[str]) -> list[Post]:
    rows = _read_jsonl(NODE_POSTS) if NODE_POSTS.is_file() else []
    return [Post(**r) for r in rows if r["id"] in ids]


def label(llm: LLM, out: Path = GOLD_DIR, path: Path = GRAPH) -> dict:
    """Kimi node labels for node items not labelled yet; unanswered items stay null."""
    f = out / "node_gold.jsonl"
    done = {r["id"]: r for r in _read_jsonl(f)} if f.is_file() else {}
    lh = label_prompt_hash(path)
    items = _items(out)
    todo = sorted(i for i in items if i not in done)
    if todo:
        posts = _posts(set(todo))
        ans = node.node_check(
            llm, posts, _stmts(path), "gold.node", NODE_BATCH, GOLD_ROUNDS, gold=True
        )
        quotes_f = CACHE_DIR / "node_gold_quotes.jsonl"
        quotes = _read_jsonl(quotes_f) if quotes_f.is_file() else []
        for p, a in zip(posts, ans, strict=True):
            done[p.id] = {
                "id": p.id,
                "split": items[p.id]["split"],
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
        "items": len(done),
        "labelled": sum(r["verdicts"] is not None for r in done.values()),
        "new": len(todo),
    }


def _answers(llm: LLM, posts: list[Post], purpose: str, gold_: bool, path: Path) -> dict:
    rounds = GOLD_ROUNDS if gold_ else ROUNDS
    ans = node.node_check(llm, posts, _stmts(path), purpose, NODE_BATCH, rounds, gold=gold_)
    return {
        p.id: ({k: v["verdict"] for k, v in a.items()} if a else None)
        for p, a in zip(posts, ans, strict=True)
    }


def record(llm: LLM, out: Path = GOLD_DIR, path: Path = GRAPH) -> Path:
    """Producer node answers on every node item, committed under the node prompt hash. Items
    already recorded under this hash keep their answers, so growth only adds new items."""
    h = prompt_hash(llm.model, llm.reasoning_effort, path)
    rec = out / "recorded" / f"node-{h}.json"
    old = json.loads(rec.read_text("utf-8"))["answers"] if rec.is_file() else {}
    todo = {i for i in _items(out) if i not in old}
    new = _answers(llm, sorted(_posts(todo), key=lambda p: p.id), "gold.node.record", False, path)
    rec.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "prompt_hash": h,
        "model": llm.model,
        "host": llm.host,
        "reasoning_effort": llm.reasoning_effort,
        "answers": dict(sorted({**old, **new}.items())),
    }
    rec.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", "utf-8")
    return rec


def cross_label(llm: LLM, out: Path = GOLD_DIR, path: Path = GRAPH) -> Path:
    """A second model labels every node item blind, with the same frozen gold node prompt."""
    f = out / f"node_cross_{llm.model.split('/')[-1]}.json"
    old = json.loads(f.read_text("utf-8"))["answers"] if f.is_file() else {}
    todo = {i for i in _items(out) if i not in old}
    new = _answers(llm, sorted(_posts(todo), key=lambda p: p.id), "gold.node.cross", True, path)
    body = {
        "model": llm.model,
        "host": llm.host,
        "reasoning_effort": llm.reasoning_effort,
        "label_prompt_hash": label_prompt_hash(path),
        "answers": dict(sorted({**old, **new}.items())),
    }
    f.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", "utf-8")
    return f


def _designated(out: Path) -> list[tuple[str, str, str, str]]:
    """(item id, node, split, gold verdict) for every designated pair Kimi answered."""
    items = _items(out)
    f = out / "node_gold.jsonl"
    rows = _read_jsonl(f) if f.is_file() else []
    return [
        (r["id"], n, r["split"], r["verdicts"][n])
        for r in rows
        if r["verdicts"] is not None and r["id"] in items
        for n in items[r["id"]]["pairs"]
    ]


def cross_agreement(path: Path, out: Path = GOLD_DIR) -> dict:
    """Kimi vs second model over designated pairs both answered: overall, per Kimi class, kappa."""
    other = json.loads(path.read_text("utf-8"))
    ans = other["answers"]
    pairs = [
        (g, (ans.get(i) or {}).get(n)) for i, n, _, g in _designated(out) if ans.get(i) is not None
    ]
    a, b = [g for g, _ in pairs], [o for _, o in pairs]
    per = {
        c: {
            "n": sum(g == c for g in a),
            "agree": round(agreement([g for g in a if g == c], [o for g, o in pairs if g == c]), 4)
            if any(g == c for g in a)
            else None,
        }
        for c in prompts.VERDICTS
    }
    res = {
        "model": other["model"],
        "pairs": len(pairs),
        "unanswered_items": sum(v is None for v in ans.values()),
        "agreement": round(agreement(a, b), 4) if pairs else None,
        "kappa": cohen_kappa(a, b),
        "per_class": per,
        "passed": bool(pairs) and agreement(a, b) >= CROSS_MIN,
        "basis": "cross-model agreement, not human-verified",
    }
    (out / "node_cross_agreement.json").write_text(json.dumps(res, indent=1) + "\n", "utf-8")
    return res


def per_node(out: Path = GOLD_DIR) -> dict:
    """Gold verdict counts per node over designated pairs; 0 supports and 0 contradicts is
    reported as no public evidence in this harvest (amendment 2), never padded."""
    _, node_ids = candidates()
    res = {}
    for n in node_ids:
        c = Counter(g for _, m, _, g in _designated(out) if m == n)
        res[n] = {v: c.get(v, 0) for v in prompts.VERDICTS}
        if not c.get("supports") and not c.get("contradicts"):
            res[n]["finding"] = "no public evidence in this harvest"
    return res


def check_nodes(out: Path = GOLD_DIR, phash: str | None = None, path: Path = GRAPH) -> dict:
    """Producer supports / contradicts precision against Kimi, designated pairs only, per split."""
    phash = phash or prompt_hash(path=path)
    rec_f = out / "recorded" / f"node-{phash}.json"
    if not (out / "node_gold.jsonl").is_file() or not rec_f.is_file():
        return {"prompt_hash": phash, "classes": {}, "error": f"no node recording for {phash}"}
    rec = json.loads(rec_f.read_text("utf-8"))["answers"]
    des = _designated(out)
    res: dict = {"prompt_hash": phash, "classes": {}}
    for split in ("dev", "test"):
        pairs = [((rec.get(i) or {}).get(n), g) for i, n, s, g in des if s == split]
        for c in NODE_CLASSES:
            res["classes"].setdefault(c, {})[split] = _prec(
                [p for p, _ in pairs], [g for _, g in pairs], c
            )
    res["pairs"] = {s: sum(x[2] == s for x in des) for s in ("dev", "test")}
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
    res["per_node"] = per_node(out)
    xf = out / "node_cross_agreement.json"
    if xf.is_file():
        res["node_cross_agreement"] = json.loads(xf.read_text("utf-8"))
    for k in NODE_CLASSES:  # no recording yet still reports the class, as NOT MEASURED
        nodes["classes"].setdefault(k, {sp: _prec([], [], k) for sp in ("dev", "test")})
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


__all__ = [
    "canary",
    "check_nodes",
    "cross_agreement",
    "cross_label",
    "grow",
    "label",
    "per_node",
    "pick",
    "record",
    "t1",
]
