"""L3 steps a (author gate) and c (element tags). An answer whose quote is not in the post
verbatim is dropped and the post is asked again; a post still unanswered stays None."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nmt_engine.llm import LLM, LLMError
from nmt_engine.util import normalize_ws
from nmt_engine.verify import prompts

ROUNDS = 3


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
    role = row.get("role")
    if role not in prompts.ROLES or not verbatim(row.get("role_quote"), text):
        return None
    names = row.get("names_solution")
    if not isinstance(names, bool):
        return None
    if names and not verbatim(row.get("solution_quote"), text):
        return None
    return AuthorVerdict(
        role,
        normalize_ws(row["role_quote"]),
        names,
        str(row.get("solution")) if names and row.get("solution") else None,
        normalize_ws(row["solution_quote"]) if names else None,
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
) -> list:
    out: list = [None] * len(posts)
    for round_ in range(rounds):
        by_cat: dict[str, list[int]] = {}
        for k, p in enumerate(posts):
            if out[k] is None:
                by_cat.setdefault(p.category, []).append(k)
        for cat, idx in sorted(by_cat.items()):
            for i in range(0, len(idx), batch):
                chunk = idx[i : i + batch]
                body = "\n\n".join(f"{n}.\n{posts[k].text}" for n, k in enumerate(chunk))
                prompt = build(cat, body)
                if round_:  # a changed prompt, so the cache cannot replay an unusable answer
                    prompt += f"\n\n(Retry {round_}: answer every id from 0 to {len(chunk) - 1}.)"
                try:
                    data = llm.complete_json(prompt, system, purpose)
                except (LLMError, ValueError):
                    continue
                rows = data.get("posts") if isinstance(data, dict) else None
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    try:
                        n = int(row.get("id"))
                    except (TypeError, ValueError):
                        continue
                    if 0 <= n < len(chunk) and out[chunk[n]] is None:
                        out[chunk[n]] = parse(row, posts[chunk[n]].text)
    return out


def author_gate(
    llm: LLM, posts: Sequence[Post], purpose: str = "verify.author", batch=8, rounds=ROUNDS
) -> list[AuthorVerdict | None]:
    return _ask(
        llm,
        posts,
        lambda cat, body: prompts.AUTHOR_PROMPT.format(category=cat, posts=body),
        prompts.AUTHOR_SYSTEM,
        purpose,
        parse_author,
        batch,
        rounds,
    )


def tag_elements(
    llm: LLM, posts: Sequence[Post], purpose: str = "verify.elements", batch=8, rounds=ROUNDS
) -> list[dict[str, bool] | None]:
    return _ask(
        llm,
        posts,
        lambda cat, body: prompts.ELEMENT_PROMPT.format(
            category=cat, posts=body, fields=prompts.ELEMENT_FIELDS
        ),
        prompts.ELEMENT_SYSTEM,
        purpose,
        parse_elements,
        batch,
        rounds,
    )
