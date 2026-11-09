"""Switching world: each segment agent holds a current Solution and answers, in free text, what
it does under one market condition. SSR turns the answer into P(stay / consider / switch to X).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from nmt_engine.hypothesis.schema import HypothesisGraph
from nmt_engine.llm import LLM
from nmt_engine.sim import agents as ag
from nmt_engine.sim.ssr import SSR, collapse
from nmt_engine.util import canonical_json, sha256_text

LABEL = "SIMULATED"
CONDITIONS: dict[str, str] = {
    "none": "Nothing on the market has changed.",
    "price10": "{inc} raises its price by 10% from next month.",
    "price50": "{inc} raises its price by 50% from next month.",
    "entrant": (
        "A new invoicing app launches that sends payment reminders by itself and shows every "
        "unpaid invoice in one place, at about the same price as {inc}."
    ),
    "kill_job": "{inc} stops helping you {job}.",
    "take_job": (
        "A service launches that chases your unpaid invoices for you, so the job is taken off "
        "your hands, for a monthly fee."
    ),
    "copy": "{rival} copies the feature you rely on most in {inc}.",
}

SYSTEM = (
    "You play one customer segment in a market simulation. Answer in the first person, in 2 to 4 "
    "sentences of plain text. Never give numbers, scores, percentages or probabilities."
)

PROMPT = """You are: {segment}
The jobs you need done:
{jobs}
How you judge that a job went well, most important first:
{criteria}
What people like you have said in public (for grounding only):
{quotes}

You use now: {incumbent}
Other options on the market:
{offers}
What has just happened: {condition}

Weigh a move: the outcome against your criteria in your order, minus the six costs of moving
(money, time, effort, cognitive load, negative emotion, and the extra admin jobs it creates),
against what you expect to get. Think about what pushes you away from what you use now, what
pulls you towards another option, your habit, your anxiety about changing and any barriers.

Say what you do now: stay with what you use, look around without moving yet, or switch. If you
switch, name the option you move to.{repeat}"""


def prompt_hash() -> str:
    return sha256_text(canonical_json({"s": SYSTEM, "p": PROMPT, "c": CONDITIONS}))[:16]


@dataclass(frozen=True)
class Cell:
    agent: str
    incumbent: str
    condition: str
    repeat: int = 0


def condition_text(key: str, inc: str, agent: ag.Agent, rival: str, text: str | None = None) -> str:
    if text is not None:
        return text
    job = agent.jobs[0].removeprefix("I want to ").rstrip(".")
    return CONDITIONS[key].format(inc=inc, job=job, rival=rival)


def render(
    agent: ag.Agent, incumbent: str, offers: list[str], condition: str, repeat: int = 0
) -> str:
    def lines(xs):
        return "\n".join(f"- {x}" for x in xs) or "- (none)"

    return PROMPT.format(
        segment=agent.segment,
        jobs=lines(agent.jobs),
        criteria="\n".join(f"{i}. {c}" for i, c in enumerate(agent.criteria, 1)),
        quotes=lines(f'"{q}"' for q in agent.quotes),
        incumbent=incumbent,
        offers=lines(offers),
        condition=condition,
        repeat=f"\n\n(Run {repeat + 1}.)" if repeat else "",
    )


def answer(llm: LLM, prompt: str, purpose: str) -> str:
    def check(text: str) -> str:
        if not text.strip():
            from nmt_engine.llm import LLMError

            raise LLMError("empty simulated answer")
        return text

    return llm.complete(prompt, system=SYSTEM, purpose=purpose, check=check).strip()


def solutions(graph: HypothesisGraph) -> dict[str, str]:
    return {n.id: n.text for n in graph.nodes if n.type == "solution"}


def main_cells(graph: HypothesisGraph, agents: list[ag.Agent], repeats: int = 1) -> list[Cell]:
    return [
        Cell(a.id, inc, cond, r)
        for a in agents
        for inc in ag.incumbents(graph, a)
        for cond in CONDITIONS
        for r in range(repeats)
    ]


def run(
    llm: LLM,
    ssr: SSR,
    graph: HypothesisGraph,
    agents: list[ag.Agent],
    cells: list[Cell],
    out: Path,
    workers: int = 8,
) -> list[dict]:
    """Answer every cell, score it with SSR and write `out` (jsonl, one row per cell)."""
    sols = solutions(graph)
    by_id = {a.id: a for a in agents}
    jobs = []
    for c in cells:
        a = by_id[c.agent]
        inc = sols[c.incumbent]
        offers = [t for k, t in sols.items() if k != c.incumbent]
        cond = condition_text(c.condition, inc, a, offers[0])
        jobs.append((c, inc, offers, render(a, inc, offers, cond, c.repeat)))
    purpose = f"sim.world.{llm.model.split('/')[-1]}"
    with ThreadPoolExecutor(workers) as pool:
        texts = list(pool.map(lambda j: answer(llm, j[3], purpose), jobs))
    ps = ssr.score(texts, [j[2] for j in jobs], [j[1] for j in jobs], "sim.ssr")
    rows = []
    for (c, *_), text, p in zip(jobs, texts, ps, strict=True):
        rows.append(
            {
                "label": LABEL,
                "simulated": True,
                "family": "simulated",
                "model": llm.model,
                "prompt_hash": prompt_hash(),
                **c.__dict__,
                "answer": text,
                "p": p,
                **{f"p_{k}": v for k, v in collapse(p).items()},
            }
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), "utf-8")
    return rows
