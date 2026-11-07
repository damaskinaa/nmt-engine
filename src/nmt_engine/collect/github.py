"""GitHub issues (REST search) and discussions (GraphQL; needs GITHUB_TOKEN).

access_basis: public_api_terms_ok
terms: https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms
"""

from __future__ import annotations

from datetime import date

from nmt_engine.collect.base import Collector, env, ts

NAME = "github"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service"
SEARCH = "https://api.github.com/search/issues"
GRAPHQL = "https://api.github.com/graphql"


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if tok := env("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {tok}"
    return h


def issues(c: Collector, query: str, since: date, limit: int = 100, repo: str | None = None):
    q = f"{query} is:issue created:>={since.isoformat()}" + (f" repo:{repo}" if repo else "")
    out, page = [], 1
    while len(out) < limit:
        data = c.fetch_json(
            SEARCH,
            NAME,
            params={"q": q, "per_page": min(100, limit), "page": page},
            headers=_headers(),
        )
        items = data.get("items", [])
        for it in items:
            src = c.add_source(
                adapter=NAME,
                kind="issue",
                platform="github",
                url=it["html_url"],
                text=f"{it.get('title', '')}\n\n{it.get('body') or ''}",
                author=(it.get("user") or {}).get("login"),
                published_at=ts(it.get("created_at")),
                access_basis=ACCESS_BASIS,
                terms_url=TERMS_URL,
                geography="GLOBAL",
            )
            if src:
                out.append(src)
        if len(items) < min(100, limit) or page >= 10:
            break
        page += 1
    return out[:limit]


DISCUSSIONS_Q = """query($q: String!, $n: Int!) { search(query: $q, type: DISCUSSION, first: $n) {
  nodes { ... on Discussion { url title body createdAt author { login } } } } }"""


def discussions(c: Collector, query: str, since: date, limit: int = 50):
    env("GITHUB_TOKEN", required_by="github discussions (GraphQL)")
    q = f"{query} created:>={since.isoformat()}"
    data = c.fetch_json(
        GRAPHQL,
        NAME,
        method="POST",
        json_body={"query": DISCUSSIONS_Q, "variables": {"q": q, "n": min(100, limit)}},
        headers=_headers(),
    )
    out = []
    for d in (data.get("data") or {}).get("search", {}).get("nodes", []):
        if not d:
            continue
        src = c.add_source(
            adapter=NAME,
            kind="forum",
            platform="github-discussions",
            url=d["url"],
            text=f"{d.get('title', '')}\n\n{d.get('body') or ''}",
            author=(d.get("author") or {}).get("login"),
            published_at=ts(d.get("createdAt")),
            access_basis=ACCESS_BASIS,
            terms_url=TERMS_URL,
            geography="GLOBAL",
        )
        if src:
            out.append(src)
    return out


def collect(c: Collector, query: str, since: date, limit: int = 100):
    out = issues(c, query, since, limit)
    if env("GITHUB_TOKEN"):
        out += discussions(c, query, since, min(50, limit))
    return out
