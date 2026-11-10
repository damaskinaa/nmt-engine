"""SSR anchor gold (PREREG_v3 amendment 4): 150 model-written answers (Kimi), 50 per intended
class, split by answer id. CI recomputes SSR classes from committed similarities, keyed by the
anchor-set hash, without an API key. Model-written, not human-verified."""

from __future__ import annotations

import json
from pathlib import Path

from nmt_engine.hypothesis.schema import HypothesisGraph
from nmt_engine.llm import LLM, LLMError, parse_json
from nmt_engine.sim import ssr as ssr_mod
from nmt_engine.sim.world import CONDITIONS, solutions
from nmt_engine.util import sha256_text
from nmt_engine.verify.gold import GOLD_DIR, MIN_CALLS, _read_jsonl, _write_jsonl

PER_CLASS = 50
PER_CALL = 5
BAR = 0.85
FILE = "ssr_gold.jsonl"
REC_DIR = "ssr_recorded"

MEANS = {
    "stay": "they keep what they use now and are not looking at anything else",
    "consider": "they start looking at or trying alternatives but have not moved and keep their "
    "current option for now",
    "switch": "they leave what they use now and move to {x}, named in the answer",
}

GEN_SYSTEM = "You write test data for a market simulation. You reply with JSON only."
GEN_PROMPT = """Customer segment: {segment}
They use now: {incumbent}
What has just happened: {condition}

Write {n} different answers this customer might give when asked what they do now. Every answer
must clearly mean that {means}. First person, 2 to 4 sentences, plain words, no numbers, and
vary the wording, the reasons and the tone between answers.

Reply as {{"answers": ["...", ...]}} with exactly {n} answers."""


def split_of(item_id: str) -> str:
    return "test" if int(sha256_text(item_id), 16) % 2 else "dev"


def _combos(graph: HypothesisGraph):
    segs = [n for n in graph.nodes if n.type == "segment"]
    sols = solutions(graph)
    conds = list(CONDITIONS)
    i = 0
    while True:
        s = segs[i % len(segs)]
        inc_ids = [
            n.id for n in graph.nodes if n.type == "solution" and set(n.serves) & set(s.core_jobs)
        ]
        inc = inc_ids[(i // len(segs)) % len(inc_ids)]
        others = [k for k in sols if k != inc]
        yield s, inc, others[i % len(others)], conds[i % len(conds)], [sols[k] for k in others]
        i += 1


def generate(llm: LLM, graph: HypothesisGraph, out: Path = GOLD_DIR) -> dict:
    sols = solutions(graph)
    rows = []
    for cls in ssr_mod.CLASSES:
        combos = _combos(graph)
        k = 0
        while k < PER_CLASS:
            s, inc, rival, cond, offers = next(combos)
            means = MEANS[cls].format(x=sols[rival])
            ctext = CONDITIONS[cond].format(inc=sols[inc], job="send invoices", rival=sols[rival])
            prompt = GEN_PROMPT.format(
                segment=s.text, incumbent=sols[inc], condition=ctext, n=PER_CALL, means=means
            )

            def check(text: str) -> list[str]:
                ans = parse_json(text).get("answers")
                if not isinstance(ans, list) or len(ans) != PER_CALL:
                    raise LLMError("wrong number of answers")
                return ans

            ans = check(
                llm.complete(prompt, GEN_SYSTEM, "sim.ssrgold", json_mode=True, check=check)
            )
            for a in ans[: PER_CLASS - k]:
                iid = f"SG-{cls}-{k:03d}"
                rows.append(
                    {
                        "id": iid,
                        "class": cls,
                        "destination": rival if cls == "switch" else None,
                        "segment": s.id,
                        "incumbent": inc,
                        "condition": cond,
                        "offers": offers,
                        "answer": " ".join(str(a).split()),
                        "split": split_of(iid),
                        "writer": llm.model,
                        "basis": "model-written (Kimi), not human-verified",
                    }
                )
                k += 1
    _write_jsonl(out / FILE, rows)
    return {"items": len(rows), "by_split": _count(rows, "split")}


def _count(rows, key):
    out: dict[str, int] = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


def record(emb, graph: HypothesisGraph, out: Path = GOLD_DIR) -> Path:
    rows = _read_jsonl(out / FILE)
    sols = solutions(graph)
    sims = ssr_mod.SSR(emb).sims(
        [r["answer"] for r in rows],
        [r["offers"] for r in rows],
        [sols[r["incumbent"]] for r in rows],
        "sim.ssrgold",
    )
    path = out / REC_DIR / f"{ssr_mod.anchor_hash()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "anchor_hash": ssr_mod.anchor_hash(),
        "sims": {r["id"]: s for r, s in zip(rows, sims, strict=True)},
    }
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", "utf-8")
    return path


def check(out: Path = GOLD_DIR) -> dict:
    """Per-class precision of the SSR top class against the intended class. Fewer than 20 test
    calls is NOT MEASURED. `passed` (the CI gate) fails on a missing recording or any measured
    class below 85%; `t3_may_run` needs all three classes measured and passing."""
    path = out / REC_DIR / f"{ssr_mod.anchor_hash()}.json"
    if not path.is_file():
        return {
            "anchor_hash": ssr_mod.anchor_hash(),
            "error": "no recording",
            "passed": False,
            "t3_may_run": False,
        }
    sims = json.loads(path.read_text("utf-8"))["sims"]
    rows = _read_jsonl(out / FILE)
    res: dict = {
        "anchor_hash": ssr_mod.anchor_hash(),
        "basis": "model-written answers (Kimi), not human-verified",
        "classes": {},
    }
    for cls in ssr_mod.CLASSES:
        res["classes"][cls] = {}
        for sp in ("dev", "test"):
            called = [
                r
                for r in rows
                if r["split"] == sp and ssr_mod.top_class(ssr_mod.probs(sims[r["id"]])) == cls
            ]
            tp = sum(r["class"] == cls for r in called)
            res["classes"][cls][sp] = {
                "tp": tp,
                "called": len(called),
                "precision": round(tp / len(called), 4) if called else None,
            }
        t = res["classes"][cls]["test"]
        t["status"] = (
            "NOT MEASURED"
            if t["called"] < MIN_CALLS
            else ("PASS" if t["precision"] >= BAR else "FAIL")
        )
    st = [res["classes"][c]["test"]["status"] for c in ssr_mod.CLASSES]
    res["passed"] = "FAIL" not in st
    res["t3_may_run"] = all(s == "PASS" for s in st)
    return res
