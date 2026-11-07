"""Reddit official Data API (OAuth app-only token; needs REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
REDDIT_USER_AGENT). Respects the documented free-tier limit (100 QPM) via the collector's
rate limiter. No scraping of www.reddit.com HTML.

access_basis: public_api_terms_ok
terms: https://redditinc.com/policies/data-api-terms
"""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime, time

from nmt_engine.collect.base import Collector, env, ts

NAME = "reddit"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://redditinc.com/policies/data-api-terms"
TOKEN = "https://www.reddit.com/api/v1/access_token"
SEARCH = "https://oauth.reddit.com/search"


def _token(c: Collector) -> tuple[str, str]:
    cid = env("REDDIT_CLIENT_ID", required_by=NAME)
    secret = env("REDDIT_CLIENT_SECRET", required_by=NAME)
    ua = env("REDDIT_USER_AGENT", required_by=NAME)
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    resp = c.client.post(
        TOKEN,
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {basic}", "User-Agent": ua},
    )
    resp.raise_for_status()
    return resp.json()["access_token"], ua


def collect(c: Collector, query: str, since: date, limit: int = 100, subreddit: str | None = None):
    tok, ua = _token(c)
    headers = {"Authorization": f"Bearer {tok}", "User-Agent": ua}
    url = f"https://oauth.reddit.com/r/{subreddit}/search" if subreddit else SEARCH
    floor = datetime.combine(since, time(), UTC)
    out, after = [], None
    while len(out) < limit:
        params = {"q": query, "limit": 100, "sort": "relevance", "t": "all", "raw_json": 1}
        if subreddit:
            params["restrict_sr"] = 1
        if after:
            params["after"] = after
        data = c.fetch_json(url, NAME, params=params, headers=headers)["data"]
        for child in data.get("children", []):
            d = child["data"]
            created = ts(d.get("created_utc"))
            if created and created < floor:
                continue
            src = c.add_source(
                adapter=NAME,
                kind="forum",
                platform=f"reddit:r/{d.get('subreddit', '')}",
                url=f"https://www.reddit.com{d['permalink']}",
                text=f"{d.get('title', '')}\n\n{d.get('selftext') or ''}",
                author=d.get("author"),
                published_at=created,
                access_basis=ACCESS_BASIS,
                terms_url=TERMS_URL,
                geography="GLOBAL",
            )
            if src:
                out.append(src)
        after = data.get("after")
        if not after:
            break
    return out[:limit]
