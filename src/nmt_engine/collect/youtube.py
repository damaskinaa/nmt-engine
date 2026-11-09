"""YouTube Data API v3: video titles/descriptions and top-level comments (needs YOUTUBE_API_KEY).

access_basis: public_api_terms_ok
terms: https://developers.google.com/youtube/terms/api-services-terms-of-service
"""

from __future__ import annotations

from datetime import date

from nmt_engine.collect.base import Collector, env, ts

NAME = "youtube"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://developers.google.com/youtube/terms/api-services-terms-of-service"
API = "https://www.googleapis.com/youtube/v3"


def collect(c: Collector, query: str, since: date, videos: int = 10, comments: int = 50):
    key = env("YOUTUBE_API_KEY", required_by=NAME)
    found = c.fetch_json(
        f"{API}/search",
        NAME,
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(50, videos),
            "publishedAfter": f"{since.isoformat()}T00:00:00Z",
            "key": key,
        },
    )
    out = []
    for item in found.get("items", []):
        vid, sn = (item.get("id") or {}).get("videoId"), item.get("snippet") or {}
        if not vid:
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        src = c.add_source(
            adapter=NAME,
            kind="web",
            platform="youtube",
            evidence_family="market_record",  # creator's title/description, not a customer
            publisher=sn.get("channelTitle"),
            url=url,
            text=f"{sn.get('title', '')}\n\n{sn.get('description', '')}",
            published_at=ts(sn.get("publishedAt")),
            access_basis=ACCESS_BASIS,
            terms_url=TERMS_URL,
            geography="GLOBAL",
        )
        if src:
            out.append(src)
        if comments <= 0:
            continue
        threads = c.fetch_json(
            f"{API}/commentThreads",
            NAME,
            params={
                "part": "snippet",
                "videoId": vid,
                "maxResults": min(100, comments),
                "textFormat": "plainText",
                "key": key,
            },
        )
        for t in threads.get("items", []):
            top = (t.get("snippet") or {}).get("topLevelComment") or {}
            cs = top.get("snippet") or {}
            if not top.get("id"):
                continue
            src = c.add_source(
                adapter=NAME,
                kind="forum",
                platform="youtube-comments",
                url=f"{url}&lc={top['id']}",
                text=cs.get("textOriginal") or cs.get("textDisplay", ""),
                author=(cs.get("authorChannelId") or {}).get("value")
                or cs.get("authorDisplayName"),
                published_at=ts(cs.get("publishedAt")),
                access_basis=ACCESS_BASIS,
                terms_url=TERMS_URL,
                geography="GLOBAL",
            )
            if src:
                out.append(src)
    return out
