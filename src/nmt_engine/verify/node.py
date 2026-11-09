"""L3 step b, node check: each USER post naming a Solution x each candidate node -> supports /
contradicts / unrelated, with a verbatim quote (PREREG_v3 amendment 1). Statements come from code,
one per node, so a model never words the claim it is checking."""

from __future__ import annotations

from collections.abc import Sequence

from nmt_engine.hypothesis.schema import HypothesisGraph
from nmt_engine.llm import LLM
from nmt_engine.util import normalize_ws
from nmt_engine.verify import prompts
from nmt_engine.verify.author import ROUNDS, Post, _ask, verbatim


def _act(job: str) -> str:
    return job[len("I want to ") :] if job.startswith("I want to ") else job


def statement(g: HypothesisGraph, node_id: str) -> str:
    t = {n.id: n for n in g.nodes}
    n = t[node_id]
    if n.type == "job":
        return f'The author needs to do this: "{n.text}".'
    if n.type == "solution":
        jobs = " and ".join(f'"{_act(t[j].text)}"' for j in n.serves)
        return f'The author uses "{n.text}" (or a product of that kind) to {jobs}.'
    if n.type == "criterion":
        return f'For "{t[n.job].text}", the author judges success by this: "{n.text}".'
    if n.type == "problem":
        return f'The author has this problem with "{t[n.solution].text}": "{n.text}".'
    raise ValueError(f"{node_id}: {n.type} nodes are not desk-checkable")


def statements(g: HypothesisGraph, node_ids: Sequence[str]) -> dict[str, str]:
    return {i: statement(g, i) for i in node_ids}


def render(stmts: dict[str, str]) -> str:
    return "\n".join(f"{i}: {s}" for i, s in stmts.items())


def parse_nodes(node_ids: Sequence[str]):
    """Parser for one post's answers: every node answered, quotes verbatim, else None."""

    def parse(row: dict, text: str) -> dict[str, dict] | None:
        answers = row.get("answers")
        if not isinstance(answers, list):
            return None
        got: dict[str, dict] = {}
        for a in answers:
            if not isinstance(a, dict) or a.get("node") not in node_ids:
                continue
            v, q = a.get("verdict"), a.get("quote")
            if v not in prompts.VERDICTS:
                return None
            if v != "unrelated" and not verbatim(q, text):
                return None
            got[a["node"]] = {
                "verdict": v,
                "quote": normalize_ws(q) if v != "unrelated" else None,
            }
        return got if set(got) == set(node_ids) else None

    return parse


def node_check(
    llm: LLM,
    posts: Sequence[Post],
    stmts: dict[str, str],
    purpose: str = "verify.node",
    batch: int = 4,
    rounds: int = ROUNDS,
    gold: bool = False,
) -> list[dict[str, dict] | None]:
    body = render(stmts)
    return _ask(
        llm,
        posts,
        lambda cat, posts_: (prompts.GOLD_NODE_PROMPT if gold else prompts.NODE_PROMPT).format(
            category=cat, statements=body, posts=posts_
        ),
        prompts.GOLD_NODE_SYSTEM if gold else prompts.NODE_SYSTEM,
        purpose,
        parse_nodes(list(stmts)),
        batch,
        rounds,
    )
