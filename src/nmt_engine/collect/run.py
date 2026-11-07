"""`nmt collect` orchestration: run every enabled trace adapter for one category."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from nmt_engine.collect import (
    appstore,
    dataforseo,
    github,
    hackernews,
    procurement,
    reddit,
    stackexchange,
    wayback,
    web,
    youtube,
)
from nmt_engine.collect.base import Collector, MissingKeyError, env

STACK_SITES = ("stackoverflow", "softwarerecs", "webapps", "superuser")


@dataclass
class CollectPlan:
    category: str
    since: date
    geo: str = "IE"
    competitors: list[str] = field(default_factory=list)
    per_adapter: int = 200


def _steps(p: CollectPlan) -> list[tuple[str, Callable[[Collector], list]]]:
    q, n = p.category, p.per_adapter
    steps: list[tuple[str, Callable[[Collector], list]]] = [
        ("hackernews:comments", lambda c: hackernews.collect(c, q, p.since, n, "comment")),
        ("hackernews:stories", lambda c: hackernews.collect(c, q, p.since, n // 2, "story")),
        ("appstore", lambda c: appstore.collect(c, q, p.geo.lower(), 5, 2, p.since)),
        ("github", lambda c: github.collect(c, q, p.since, n // 2)),
        ("reddit", lambda c: reddit.collect(c, q, p.since, n)),
        ("youtube", lambda c: youtube.collect(c, q, p.since)),
        ("procurement:ted", lambda c: procurement.ted(c, q, p.since, 50)),
        ("procurement:contracts_finder", lambda c: procurement.contracts_finder(c, q, p.since)),
        ("dataforseo:autocomplete", lambda c: _dfs(c, q, p.geo)),
    ]
    for site in STACK_SITES:
        steps.append(
            (
                f"stackexchange:{site}",
                lambda c, s=site: stackexchange.collect(c, q, p.since, s, n // 4),
            )
        )
    for dom in p.competitors:
        steps.append((f"web:{dom}", lambda c, d=dom: web.competitor_pages(c, d)))
        steps.append(
            (f"wayback:{dom}", lambda c, d=dom: wayback.collect(c, f"{d}/pricing", p.since, 6))
        )
    return steps


def _dfs(c: Collector, q: str, geo: str) -> list:
    if not env("DATAFORSEO_LOGIN"):
        raise MissingKeyError("dataforseo needs $DATAFORSEO_LOGIN")
    dataforseo.autocomplete(c, q, geo)
    dataforseo.serp_questions(c, q, geo)
    return []


def run_collect(plan: CollectPlan, run_dir: Path, collector: Collector | None = None) -> dict:
    """Run all adapters; adapters missing keys are skipped, failures are reported, not fatal.
    Writes and returns `collect_summary.json`."""
    if collector is None and not env("NMT_AUTHOR_SALT"):
        raise MissingKeyError("set $NMT_AUTHOR_SALT so author hashes are salted and reproducible")
    c = collector or Collector(run_dir, geo=plan.geo, salt=env("NMT_AUTHOR_SALT"))
    summary: dict = {"category": plan.category, "since": plan.since.isoformat(), "adapters": {}}
    for name, step in _steps(plan):
        try:
            summary["adapters"][name] = {"status": "ok", "sources": len(step(c))}
        except MissingKeyError as exc:
            summary["adapters"][name] = {"status": "skipped", "reason": str(exc)}
        except (httpx.HTTPError, ValueError, KeyError, PermissionError) as exc:
            summary["adapters"][name] = {
                "status": "error",
                "reason": f"{type(exc).__name__}: {exc}",
            }
    kinds = Counter(s.kind for s in c.store.current("source").values())
    summary["sources_by_kind"] = dict(sorted(kinds.items()))
    summary["trace_sources"] = sum(
        v for k, v in kinds.items() if k in {"review", "forum", "qa", "issue", "web"}
    )
    (Path(run_dir) / "collect_summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
    return summary
