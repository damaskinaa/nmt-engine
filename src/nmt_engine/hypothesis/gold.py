"""Consistency-check gold set (§4 rule 3, A1). Truth comes from construction, not from a model:
each real link of the committed L1 graph is a "consistent" item, and code corrupts links into
"inconsistent" items by re-pointing them at a node under a different Core Job. Kimi's answers are
committed under the prompt hash; CI scores them with no API key."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from nmt_engine.config import repo_root
from nmt_engine.hypothesis import consistency
from nmt_engine.hypothesis.prompts import prompt_hash
from nmt_engine.hypothesis.schema import HypothesisGraph, Node
from nmt_engine.llm import LLM
from nmt_engine.verify.gold import MIN_CALLS, PRECISION_MIN, _prec

L1_GOLD_DIR = repo_root() / "tests" / "gold" / "l1"
CORRUPT_PER_LINK = 2
TEST_SHARE = 0.5


def _core_of(g: HypothesisGraph) -> dict[str, str | None]:
    """The Core Job above each job (None for the Big Job); criteria take their job's core."""
    by = {n.id: n for n in g.nodes}

    def up(jid: str) -> str | None:
        n = by[jid]
        while n.level not in ("core", "big"):
            n = by[n.parent]
        return n.id if n.level == "core" else None

    core = {n.id: up(n.id) for n in g.of("job")}
    core.update({c.id: core[c.job] for c in g.of("criterion")})
    return core


def _swap(n: Node, g: HypothesisGraph, core: dict, rng: random.Random) -> Node | None:
    """A copy of n with one link moved under a different Core Job, or None if impossible."""
    jobs = [j for j in g.of("job") if j.level != "big"]
    crits = g.of("criterion")

    def other(pool: list[Node], cid: str | None) -> Node | None:
        cands = [x for x in pool if core.get(x.id) not in (cid, None)]
        return rng.choice(cands) if cands else None

    if n.type == "job" and n.parent and n.level != "core":
        t = other(
            [j for j in jobs if j.level == {"small": "core", "micro": "small"}[n.level]], core[n.id]
        )
        return n.model_copy(update={"parent": t.id}) if t else None
    if n.type == "criterion":
        t = other(jobs, core[n.job])
        return n.model_copy(update={"job": t.id}) if t else None
    if n.type == "solution":
        served = {core.get(j) for j in n.serves}
        cands = [j for j in jobs if core[j.id] not in served]
        return n.model_copy(update={"serves": [rng.choice(cands).id]}) if cands else None
    if n.type == "problem":
        served = {core.get(j) for j in g.node(n.solution).serves}
        cands = [c for c in crits if core[c.id] not in served]
        if not cands:
            return None
        return n.model_copy(update={"criteria": [rng.choice(cands).id]})
    if n.type == "segment":
        mine = set(n.core_jobs)
        cands = [c for c in crits if core[c.id] not in mine]
        if len(cands) < 2:
            return None
        return n.model_copy(update={"criteria_order": rng.sample([c.id for c in cands], 2)})
    return None


def _one(g: HypothesisGraph, n: Node) -> list[dict]:
    """Statements for node n alone, computed on a graph view where n replaces the original."""
    view = HypothesisGraph.model_construct(
        brief=g.brief, nodes=[n if x.id == n.id else x for x in g.nodes]
    )
    return [s for s in consistency.statements(view) if s["link"].split(">")[0] == n.id]


def build(g: HypothesisGraph, seed: int = 0, out: Path = L1_GOLD_DIR) -> dict:
    rng = random.Random(seed)
    core = _core_of(g)
    items = []
    for n in g.nodes:
        for s in _one(g, n):
            items.append({**s, "truth": "yes", "origin": n.id})
        for k in range(CORRUPT_PER_LINK):
            bad = _swap(n, g, core, rng)
            if bad is None:
                continue
            for s in _one(g, bad):
                items.append({**s, "link": f"{s['link']}#x{k}", "truth": "no", "origin": n.id})
    seen, uniq = set(), []
    for it in items:
        if it["statement"] not in seen:
            seen.add(it["statement"])
            uniq.append(it)
    rng.shuffle(uniq)
    # split by origin node, so a link and its corruptions never straddle dev and test
    origins = sorted({it["origin"] for it in uniq})
    rng.shuffle(origins)
    test = set(origins[: round(len(origins) * TEST_SHARE)])
    for i, it in enumerate(uniq):
        it["id"] = f"l{i:03d}"
        it["split"] = "test" if it["origin"] in test else "dev"
    out.mkdir(parents=True, exist_ok=True)
    (out / "items.jsonl").write_text(
        "".join(json.dumps(it, ensure_ascii=False, sort_keys=True) + "\n" for it in uniq), "utf-8"
    )
    return {
        "items": len(uniq),
        "consistent": sum(it["truth"] == "yes" for it in uniq),
        "inconsistent": sum(it["truth"] == "no" for it in uniq),
        "test": sum(it["split"] == "test" for it in uniq),
    }


def items_hash(out: Path) -> str:
    """Ties a recording to the exact items it answered; item ids are reused after a rebuild."""
    return hashlib.sha256((out / "items.jsonl").read_bytes()).hexdigest()[:16]


def _items(out: Path) -> list[dict]:
    return [json.loads(x) for x in (out / "items.jsonl").read_text("utf-8").splitlines() if x]


def record(llm: LLM, market_job: str, out: Path = L1_GOLD_DIR) -> Path:
    items = _items(out)
    answers = consistency.ask(llm, market_job, items, purpose="l1.gold")
    path = out / "recorded" / f"{prompt_hash()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "prompt_hash": path.stem,
        "model": llm.model,
        "host": llm.host,
        "market_job": market_job,
        "items_hash": items_hash(out),
        "answers": {it["id"]: a for it, a in zip(items, answers, strict=True)},
    }
    path.write_text(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n", "utf-8")
    return path


def check(out: Path = L1_GOLD_DIR, phash: str | None = None) -> dict:
    """Precision of Kimi's "yes" (consistent) and "no" (inconsistent) calls against constructed
    truth, dev and test. < MIN_CALLS test calls is NOT MEASURED, and the L1 gate passes only
    when both classes are measured and pass."""
    phash = phash or prompt_hash()
    path = out / "recorded" / f"{phash}.json"
    if not path.is_file():
        return {
            "prompt_hash": phash,
            "classes": {},
            "passed_for": [],
            "passed": False,
            "error": f"no recording for {phash}",
        }
    body = json.loads(path.read_text("utf-8"))
    if body.get("items_hash") != items_hash(out):
        return {
            "prompt_hash": phash,
            "classes": {},
            "passed_for": [],
            "passed": False,
            "error": f"recording {phash} answered other items; re-record",
        }
    rec = body["answers"]
    items = _items(out)
    res: dict = {"prompt_hash": phash, "classes": {}}
    for split in ("dev", "test"):
        rows = [it for it in items if it["split"] == split]
        pred = [rec.get(it["id"], {}).get("consistent") for it in rows]
        truth = [it["truth"] for it in rows]
        for cls, val in (("consistent", "yes"), ("inconsistent", "no")):
            res["classes"].setdefault(cls, {})[split] = _prec(pred, truth, val)
    for c in res["classes"].values():
        t = c["test"]
        if t["called"] < MIN_CALLS:
            t["status"] = "NOT MEASURED"
        else:
            t["status"] = "PASS" if t["precision"] >= PRECISION_MIN else "FAIL"
    status = {k: c["test"]["status"] for k, c in res["classes"].items()}
    res["passed_for"] = sorted(k for k, v in status.items() if v == "PASS")
    res["passed"] = bool(status) and all(v == "PASS" for v in status.values())
    return res
