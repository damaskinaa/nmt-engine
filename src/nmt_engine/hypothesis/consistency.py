"""L1 kill criterion, second half: Kimi answers one closed question per link ("is this link
internally consistent?"). Links come from code, so every graph edge is checked exactly once."""

from __future__ import annotations

from nmt_engine.hypothesis.prompts import CHECK_PROMPT, CHECK_SYSTEM
from nmt_engine.hypothesis.schema import HypothesisGraph
from nmt_engine.llm import LLM, LLMError

BATCH = 20
ATTEMPTS = 3


def _q(text: str) -> str:
    return f'"{text}"'


def statements(g: HypothesisGraph) -> list[dict]:
    """One statement per link: part_of, serves, judges, each problem, each segment."""
    t = {n.id: n.text for n in g.nodes}
    out = []
    for n in g.nodes:
        if n.parent:
            s = f"Doing {_q(n.text)} is part of getting {_q(t[n.parent])} done."
            out.append({"link": f"{n.id}>{n.parent}", "statement": s})
        for j in n.serves:
            s = f"People use {_q(n.text)} to get {_q(t[j])} done."
            out.append({"link": f"{n.id}>{j}", "statement": s})
        if n.type == "criterion":
            s = f"{_q(n.text)} is a way to judge whether {_q(t[n.job])} went well."
            out.append({"link": f"{n.id}>{n.job}", "statement": s})
        if n.type == "problem":
            crit = " and ".join(_q(t[c]) for c in n.criteria)
            s = (
                f"{_q(n.text)} is a way {_q(t[n.solution])} falls short on {crit} "
                f"when used to {t[n.job][len('I want to ') :]}."
            )
            out.append({"link": f"{n.id}>{n.solution}", "statement": s})
        if n.type == "segment":
            jobs = " and ".join(_q(t[j]) for j in n.core_jobs)
            order = ", then ".join(_q(t[c]) for c in n.criteria_order)
            s = f"The group {_q(n.text)} does {jobs} and weighs {order}, in that order."
            out.append({"link": n.id, "statement": s})
    return out


def _parse(raw: object, n: int) -> list[dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get("answers"), list):
        raise LLMError("no answers list")
    got = {}
    for a in raw["answers"]:
        if isinstance(a, dict) and a.get("consistent") in ("yes", "no"):
            got[int(a.get("n", 0))] = a
    if sorted(got) != list(range(1, n + 1)):
        raise LLMError(f"expected answers 1..{n}, got {sorted(got)}")
    return [got[i] for i in range(1, n + 1)]


def ask(llm: LLM, market_job: str, items: list[dict], purpose: str = "l1.check") -> list[dict]:
    """Answers {consistent, reason} for each item, in order (batches of BATCH)."""
    out: list[dict] = []
    for i in range(0, len(items), BATCH):
        chunk = items[i : i + BATCH]
        body = "\n".join(f"{k + 1}. {it['statement']}" for k, it in enumerate(chunk))
        prompt = CHECK_PROMPT.format(market_job=market_job, statements=body)
        for attempt in range(ATTEMPTS):
            try:
                p = prompt if not attempt else prompt + f"\n(Retry {attempt}: one answer per n.)"
                ans = _parse(llm.complete_json(p, CHECK_SYSTEM, purpose), len(chunk))
                break
            except LLMError:
                if attempt == ATTEMPTS - 1:
                    raise
        out += [{"consistent": a["consistent"], "reason": str(a.get("reason", ""))} for a in ans]
    return out


def check(llm: LLM, g: HypothesisGraph, market_job: str) -> dict:
    items = statements(g)
    answers = ask(llm, market_job, items)
    bad = [
        {**it, "reason": a["reason"]}
        for it, a in zip(items, answers, strict=True)
        if a["consistent"] == "no"
    ]
    return {"links": len(items), "inconsistent": bad, "consistent": not bad}
