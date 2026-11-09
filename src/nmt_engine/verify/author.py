"""L3 steps a (author gate) and c (element tags). An answer whose quote is not in the post
verbatim is dropped and the post is asked again; a post still unanswered stays None."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from nmt_engine.llm import LLM, LLMError
from nmt_engine.util import normalize_ws
from nmt_engine.verify import prompts

ROUNDS = 3
WORKERS = 6  # concurrent requests; TensorX allows 60 per minute per key


@dataclass(frozen=True)
class Post:
    id: str
    category: str
    text: str


@dataclass(frozen=True)
class AuthorVerdict:
    role: str
    role_quote: str
    names_solution: bool
    solution: str | None = None
    solution_quote: str | None = None

    @property
    def continues(self) -> bool:
        """§8 A4: only USER posts naming a Solution they use or used reach node checks."""
        return self.role == "USER" and self.names_solution


def verbatim(quote: object, text: str) -> bool:
    return (
        isinstance(quote, str) and bool(quote.strip()) and normalize_ws(quote) in normalize_ws(text)
    )


def parse_author(row: dict, text: str) -> AuthorVerdict | None:
    role, role_quote = row.get("role"), row.get("role_quote")
    if role not in prompts.ROLES or not verbatim(role_quote, text):
        return None
    names = row.get("names_solution")
    if not isinstance(names, bool):
        return None
    sol_quote = row.get("solution_quote") if names else None
    if names and not verbatim(sol_quote, text):
        return None
    return AuthorVerdict(
        role,
        normalize_ws(role_quote),
        names,
        str(row.get("solution")) if names and row.get("solution") else None,
        normalize_ws(sol_quote) if sol_quote is not None else None,
    )


def parse_elements(row: dict, text: str) -> dict[str, bool] | None:
    out = {}
    for el in prompts.ELEMENTS:
        v = row.get(el)
        if not isinstance(v, bool) or (v and not verbatim(row.get(f"{el}_quote"), text)):
            return None
        out[el] = v
    return out


def _ask(
    llm: LLM,
    posts: Sequence[Post],
    build: Callable[[str, str], str],
    system: str,
    purpose: str,
    parse: Callable[[dict, str], object],
    batch: int,
    rounds: int,
    workers: int = WORKERS,
) -> list:
    out: list = [None] * len(posts)

    def one(cat: str, chunk: list[int], round_: int) -> dict[int, object]:
        """Answers for one batch; workers return them and only the main thread writes `out`."""
        got: dict[int, object] = {}
        body = "\n\n".join(f"{n}.\n{posts[k].text}" for n, k in enumerate(chunk))
        prompt = build(cat, body)
        if round_:  # a changed prompt, so the cache cannot replay an unusable answer
            prompt += (
                f"\n\n(Retry {round_}: answer every id from 0 to {len(chunk) - 1}. Each quote "
                "must be copied exactly; use a shorter quote of a few words.)"
            )
        try:
            data = llm.complete_json(prompt, system, purpose)
        except (LLMError, ValueError):
            return got
        rows = data.get("posts") if isinstance(data, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                n = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if 0 <= n < len(chunk) and got.get(chunk[n]) is None:
                got[chunk[n]] = parse(row, posts[chunk[n]].text)
        return got

    for round_ in range(rounds):
        by_cat: dict[str, list[int]] = {}
        for k, p in enumerate(posts):
            if out[k] is None:
                by_cat.setdefault(p.category, []).append(k)
        jobs = [
            (cat, idx[i : i + batch], round_)
            for cat, idx in sorted(by_cat.items())
            for i in range(0, len(idx), batch)
        ]
        with ThreadPoolExecutor(max(1, min(workers, len(jobs)))) as pool:
            for got in pool.map(lambda j: one(*j), jobs):  # BudgetExceeded propagates
                for k, v in got.items():
                    out[k] = v
    return out


def author_gate(
    llm: LLM,
    posts: Sequence[Post],
    purpose: str = "verify.author",
    batch=8,
    rounds=ROUNDS,
    gold: bool = False,
) -> list[AuthorVerdict | None]:
    return _ask(
        llm,
        posts,
        lambda cat, body: (prompts.GOLD_AUTHOR_PROMPT if gold else prompts.AUTHOR_PROMPT).format(
            category=cat, posts=body
        ),
        prompts.GOLD_AUTHOR_SYSTEM if gold else prompts.AUTHOR_SYSTEM,
        purpose,
        parse_author,
        batch,
        rounds,
    )


def tag_elements(
    llm: LLM,
    posts: Sequence[Post],
    purpose: str = "verify.elements",
    batch=8,
    rounds=ROUNDS,
    gold: bool = False,
) -> list[dict[str, bool] | None]:
    return _ask(
        llm,
        posts,
        lambda cat, body: (prompts.GOLD_ELEMENT_PROMPT if gold else prompts.ELEMENT_PROMPT).format(
            category=cat, posts=body, fields=prompts.ELEMENT_FIELDS
        ),
        prompts.GOLD_ELEMENT_SYSTEM if gold else prompts.ELEMENT_SYSTEM,
        purpose,
        parse_elements,
        batch,
        rounds,
    )
