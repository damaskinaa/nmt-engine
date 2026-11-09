"""L1: the producer drafts the hypothesis Job Graph; the schema and Kimi's link check decide.
Kill criterion: schema valid and Kimi finds every link consistent. Otherwise regenerate (max 2),
then flag."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from nmt_engine.brief import Brief
from nmt_engine.hypothesis import consistency
from nmt_engine.hypothesis.prompts import DRAFT_PROMPT, DRAFT_SYSTEM, FEEDBACK
from nmt_engine.hypothesis.schema import HypothesisGraph, Node
from nmt_engine.llm import LLM, LLMError

REGENERATIONS = 2


def _draft(llm: LLM, brief: Brief, feedback: str, prev: object) -> object:
    prompt = DRAFT_PROMPT.format(
        goal=brief.goal,
        market_job=brief.market_job,
        geography=brief.geography,
        product_reach=brief.product_reach,
        feedback=FEEDBACK.format(errors=feedback, draft=json.dumps(prev, ensure_ascii=False))
        if feedback
        else "",
    )
    return llm.complete_json(prompt, DRAFT_SYSTEM, "l1.draft")


def _errors(e: ValidationError, raw: object) -> str:
    """Pydantic errors with the node id and field they concern."""
    out = []
    for x in e.errors()[:20]:
        loc, where = x["loc"], ""
        if len(loc) >= 2 and loc[0] == "nodes" and isinstance(loc[1], int):
            try:
                where = f"{raw['nodes'][loc[1]].get('id', '?')}"
            except (KeyError, IndexError, TypeError, AttributeError):
                where = f"node {loc[1]}"
            if len(loc) > 2:
                where += "." + ".".join(str(p) for p in loc[2:])
        out.append(f"- {where + ': ' if where else ''}{x['msg']}")
    return "\n".join(out)


def build(producer: LLM, auditor: LLM, brief: Brief) -> dict:
    """Returns {graph, status: passed|flagged, attempts: [...]} ; raises if no draft is valid."""
    attempts, feedback, last_valid, prev = [], "", None, None
    for i in range(REGENERATIONS + 1):
        raw = None
        try:
            raw = _draft(producer, brief, feedback, prev)
            prev = raw
            g = HypothesisGraph.model_validate({"brief": brief.id, **(raw or {})})
        except (ValidationError, TypeError) as e:
            feedback = _errors(e, raw) if isinstance(e, ValidationError) else "not a JSON object"
            attempts.append({"attempt": i + 1, "schema": "invalid", "errors": feedback})
            continue
        except LLMError as e:
            feedback = f"- {e}"
            attempts.append({"attempt": i + 1, "schema": "unparsed", "errors": feedback})
            continue
        res = consistency.check(auditor, g, brief.market_job)
        attempts.append({"attempt": i + 1, "schema": "valid", **res})
        last_valid = g
        if res["consistent"]:
            return {"graph": g, "status": "passed", "attempts": attempts}
        feedback = "\n".join(
            f"- inconsistent link {b['link']}: {b['statement']} ({b['reason']})"
            for b in res["inconsistent"]
        )
    if last_valid is None:
        why = "\n".join(f"attempt {a['attempt']}: {a['errors']}" for a in attempts)
        raise LLMError(f"no schema-valid draft after {REGENERATIONS + 1} attempts\n{why}")
    return {"graph": last_valid, "status": "flagged", "attempts": attempts}


def to_json(g: HypothesisGraph, brief: Brief, status: str) -> dict:
    """The committed graph: model words plus code-computed priority and importance."""
    imp = g.importance()
    nodes = []
    for n in g.nodes:
        d = n.model_dump(exclude_defaults=True)
        d["status"] = n.status
        d["rat_priority"] = n.rat.priority
        d["importance"] = imp[n.id]
        nodes.append(d)
    return {
        "brief": brief.id,
        "brief_hash": brief.hash,
        "l1_status": status,
        "nodes": nodes,
        "riskiest": g.riskiest(10),
    }


def load(path: Path) -> HypothesisGraph:
    data = json.loads(path.read_text("utf-8"))
    keep = set(Node.model_fields)
    nodes = [{k: v for k, v in n.items() if k in keep} for n in data["nodes"]]
    return HypothesisGraph.model_validate({"brief": data["brief"], "nodes": nodes})
