"""Stack Exchange API v2.3 (questions with bodies). STACKEXCHANGE_KEY is optional (raises quota).

access_basis: public_api_terms_ok
terms: https://stackexchange.com/legal/api-terms-of-use (content CC BY-SA, attribution kept via URL)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from nmt_engine.collect.base import Collector, env, ts
from nmt_engine.collect.text import html_to_text

NAME = "stackexchange"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://stackexchange.com/legal/api-terms-of-use"
API = "https://api.stackexchange.com/2.3/search/advanced"


def collect(c: Collector, query: str, since: date, site: str = "stackoverflow", limit: int = 100):
    out, page = [], 1
    params = {
        "q": query,
        "site": site,
        "fromdate": int(datetime.combine(since, time(), UTC).timestamp()),
        "order": "desc",
        "sort": "relevance",
        "filter": "withbody",
        "pagesize": min(100, limit),
    }
    if key := env("STACKEXCHANGE_KEY"):
        params["key"] = key
    while len(out) < limit:
        data = c.fetch_json(API, NAME, params={**params, "page": page})
        for q in data.get("items", []):
            src = c.add_source(
                adapter=NAME,
                kind="qa",
                platform=f"stackexchange:{site}",
                url=q["link"],
                text=f"{html_to_text(q.get('title', ''))}\n\n{html_to_text(q.get('body', ''))}",
                author=str((q.get("owner") or {}).get("user_id") or "") or None,
                published_at=ts(q.get("creation_date")),
                access_basis=ACCESS_BASIS,
                terms_url=TERMS_URL,
                geography="GLOBAL",
            )
            if src:
                out.append(src)
        if not data.get("has_more"):
            break
        page += 1
    return out[:limit]
