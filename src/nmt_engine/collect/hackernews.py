"""Hacker News via the Algolia search API (stories and comments).

access_basis: public_api_terms_ok
terms: https://hn.algolia.com/api (public, no key; HN content is public)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from nmt_engine.collect.base import Collector, ts
from nmt_engine.collect.text import html_to_text

NAME = "hackernews"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://hn.algolia.com/api"
API = "https://hn.algolia.com/api/v1/search"


def collect(c: Collector, query: str, since: date, limit: int = 200, tags: str = "comment"):
    """Search stories or comments matching `query` created on/after `since`."""
    epoch = int(datetime.combine(since, time(), UTC).timestamp())
    out, page = [], 0
    while len(out) < limit:
        data = c.fetch_json(
            API,
            NAME,
            params={
                "query": query,
                "tags": tags,
                "numericFilters": f"created_at_i>={epoch}",
                "hitsPerPage": min(100, limit),
                "page": page,
            },
        )
        for hit in data.get("hits", []):
            body = hit.get("comment_text") or hit.get("story_text") or ""
            text = "\n\n".join(t for t in (hit.get("title") or "", html_to_text(body)) if t)
            src = c.add_source(
                adapter=NAME,
                kind="forum",
                platform="hackernews",
                url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                text=text,
                author=hit.get("author"),
                published_at=ts(hit.get("created_at_i")),
                access_basis=ACCESS_BASIS,
                terms_url=TERMS_URL,
                geography="GLOBAL",
            )
            if src:
                out.append(src)
        page += 1
        if page >= data.get("nbPages", 0):
            break
    return out[:limit]
