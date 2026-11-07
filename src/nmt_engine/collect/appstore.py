"""Apple App Store: iTunes Search API to find apps, customer-reviews RSS (JSON) for reviews.

access_basis: public_api_terms_ok
terms: https://performance-partners.apple.com/search-api (Search API) and the public
customer-reviews RSS feed generator (https://rss.marketingtools.apple.com/)
"""

from __future__ import annotations

from nmt_engine.collect.base import Collector, ts

NAME = "appstore"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://performance-partners.apple.com/search-api"
SEARCH = "https://itunes.apple.com/search"
REVIEWS = "https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"


def find_apps(c: Collector, term: str, country: str = "ie", limit: int = 5) -> list[dict]:
    data = c.fetch_json(
        SEARCH,
        NAME,
        params={"term": term, "entity": "software", "country": country, "limit": limit},
    )
    return [
        {"id": r["trackId"], "name": r["trackName"], "seller": r.get("sellerName")}
        for r in data.get("results", [])
    ]


def reviews(c: Collector, app_id: int, country: str = "ie", pages: int = 2, app_name: str = ""):
    out = []
    for page in range(1, pages + 1):
        url = REVIEWS.format(country=country, page=page, app_id=app_id)
        entries = c.fetch_json(url, NAME).get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            if "im:rating" not in e:  # first entry on page 1 can be the app itself
                continue
            title = e.get("title", {}).get("label", "")
            body = e.get("content", {}).get("label", "")
            rid = e.get("id", {}).get("label", "")
            src = c.add_source(
                adapter=NAME,
                kind="review",
                platform="appstore",
                publisher=app_name or None,
                url=f"https://apps.apple.com/{country}/app/id{app_id}#review-{rid}",
                text=f"{title}\n\n{body}\n\nRating: {e['im:rating']['label']}/5",
                author=e.get("author", {}).get("name", {}).get("label"),
                published_at=ts(e.get("updated", {}).get("label")),
                access_basis=ACCESS_BASIS,
                terms_url=TERMS_URL,
                geography=country.upper(),
            )
            if src:
                out.append(src)
        if not entries:
            break
    return out


def collect(c: Collector, query: str, country: str = "ie", apps: int = 5, pages: int = 2):
    out = []
    for app in find_apps(c, query, country, apps):
        out += reviews(c, app["id"], country, pages, app["name"])
    return out
