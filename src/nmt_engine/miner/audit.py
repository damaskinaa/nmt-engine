"""Auditor work for the pre-registered kill line v2 (PREREG_killline_v2.md §5, §6).

The auditor labels clustering-threshold pairs and checks accepted spans. Blind packets for the
operator carry no auditor answers; answers are compared once the operator returns labels."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from nmt_engine.llm import LLM, LLMError
from nmt_engine.miner import prompts
from nmt_engine.miner.extract import JobInstance
from nmt_engine.miner.graph_build import wilson

Z95 = 1.959964
EXCLUDE_LOWER = 0.20
AGREE_MIN = 0.80


def _batched(items: Sequence, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


ROUNDS = 3  # passes over still-unanswered items


def _answers(
    llm: LLM, prompt: str, system: str, purpose: str, key: str, field: str, n: int, round_: int = 0
):
    """{item number: bool} from one auditor request; missing or malformed items are left out.
    A retry round changes the prompt, so the cache cannot replay an earlier unusable answer."""
    if round_:
        prompt += f"\n\n(Retry {round_}: give an answer for every id from 0 to {n - 1}.)"
    try:
        data = llm.complete_json(prompt, system, purpose)
    except (LLMError, ValueError):
        return {}
    rows = data.get(key) if isinstance(data, dict) else None
    out = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get(field), bool):
            try:
                i = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if 0 <= i < n:
                out[i] = row[field]
    return out


def label_pairs(
    llm: LLM, pairs: Sequence[tuple[str, str, str]], batch: int = 10, rounds: int = ROUNDS
) -> list[bool | None]:
    """Auditor same-job labels for (category, text_a, text_b) pairs; None where it gave none.
    A batch holds pairs of one category so the prompt names it. Pairs left unanswered are
    asked again in fresh batches, up to `rounds` passes in all."""
    out: list[bool | None] = [None] * len(pairs)
    for round_ in range(rounds):
        by_cat: dict[str, list[int]] = {}
        for k, (cat, _, _) in enumerate(pairs):
            if out[k] is None:
                by_cat.setdefault(cat, []).append(k)
        for cat, idx in by_cat.items():
            for chunk in _batched(idx, batch):
                body = "\n\n".join(
                    f"{n}.\nA: {pairs[k][1]}\nB: {pairs[k][2]}" for n, k in enumerate(chunk)
                )
                ans = _answers(
                    llm,
                    prompts.PAIR_PROMPT.format(category=cat, pairs=body),
                    prompts.PAIR_SYSTEM,
                    "audit.pairs",
                    "pairs",
                    "same",
                    len(chunk),
                    round_,
                )
                for n, k in enumerate(chunk):
                    out[k] = ans.get(n)
    return out


@dataclass(frozen=True)
class Span:
    category: str
    source_id: str
    job: str
    element: str
    span: str


def accepted_spans(inst: JobInstance, category: str) -> list[Span]:
    out = [
        Span(category, inst.source_id, inst.statement, el, s)
        for el in prompts.ELEMENTS
        for s in inst.spans.get(el, [])
    ]
    out += [
        Span(category, inst.source_id, inst.statement, "success_criteria", s)
        for _, s in inst.criteria
    ]
    out += [
        Span(category, inst.source_id, inst.statement, "alternatives", s)
        for _, s in inst.alternatives
    ]
    return out


def sample_spans(
    instances: dict[str, list[JobInstance]], per: int = 50, seed: int = 0
) -> list[Span]:
    """`per` distinct accepted spans per element, pooled over categories, seeded."""
    pool: dict[str, list[Span]] = {el: [] for el in prompts.ELEMENTS}
    for cat in sorted(instances):
        for inst in instances[cat]:
            for s in accepted_spans(inst, cat):
                pool[s.element].append(s)
    rng = random.Random(seed)
    out = []
    for el in prompts.ELEMENTS:
        uniq = sorted(set(pool[el]), key=lambda s: (s.category, s.source_id, s.job, s.span))
        out += rng.sample(uniq, min(per, len(uniq)))
    return out


def audit_spans(
    llm: LLM, spans: Sequence[Span], batch: int = 10, rounds: int = ROUNDS
) -> list[bool | None]:
    """Auditor verdict per span: True = correctly labelled, None = no answer.
    Unanswered spans are asked again in fresh batches, up to `rounds` passes in all."""
    meanings = "\n".join(f"- {k}: {v}" for k, v in prompts.ELEMENT_MEANING.items())
    out: list[bool | None] = [None] * len(spans)
    for round_ in range(rounds):
        for chunk in _batched([k for k in range(len(spans)) if out[k] is None], batch):
            items = [spans[k] for k in chunk]
            body = "\n\n".join(
                f'{n}. job: {s.job}\n   element: {s.element}\n   quote: "{s.span}"'
                for n, s in enumerate(items)
            )
            ans = _answers(
                llm,
                prompts.AUDIT_PROMPT.format(meanings=meanings, items=body),
                prompts.AUDIT_SYSTEM,
                "audit.spans",
                "items",
                "correct",
                len(chunk),
                round_,
            )
            for n, k in enumerate(chunk):
                out[k] = ans.get(n)
    return out


def mislabel_rates(spans: Sequence[Span], verdicts: Sequence[bool | None]) -> dict[str, dict]:
    """Per element: audited n, mislabelled k, rate, 95% Wilson interval, excluded flag.
    Spans without an auditor answer are left out of n."""
    out = {}
    for el in prompts.ELEMENTS:
        vs = [v for s, v in zip(spans, verdicts, strict=True) if s.element == el and v is not None]
        k, n = sum(not v for v in vs), len(vs)
        lo, hi = wilson(k, n, Z95)
        out[el] = {
            "n": n,
            "mislabelled": k,
            "rate": round(k / n, 4) if n else None,
            "wilson95": [lo, hi],
            "excluded": n > 0 and lo > EXCLUDE_LOWER,
        }
    return out


def blind_sample(n_items: int, k: int, seed: int, exclude: Sequence[int] = ()) -> list[int]:
    """Indices for an operator packet: `k` of `n_items`, seeded, among those with an answer."""
    pool = [i for i in range(n_items) if i not in set(exclude)]
    return sorted(random.Random(seed).sample(pool, min(k, len(pool))))


def agreement(human: Sequence[bool], auditor: Sequence[bool]) -> float:
    if not human:
        return 0.0
    return round(sum(h == a for h, a in zip(human, auditor, strict=True)) / len(human), 4)
