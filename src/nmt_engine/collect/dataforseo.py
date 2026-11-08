"""DataForSEO (optional, paid; needs DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD): search volume,
CPC and monthly history; Google autocomplete; people-also-ask and related searches from SERPs.
Outputs are search-demand PROXY metrics, never customer counts.

access_basis: licensed
terms: https://dataforseo.com/terms-of-service
"""

from __future__ import annotations

import base64
import json

import pandas as pd

from nmt_engine.collect.base import Collector, env

NAME = "dataforseo"
ACCESS_BASIS = "licensed"
TERMS_URL = "https://dataforseo.com/terms-of-service"
API = "https://api.dataforseo.com/v3"
# DataForSEO location codes; extend as needed.
LOCATIONS = {"IE": 2372, "GB": 2826, "US": 2840, "DE": 2276, "FR": 2250}


def _headers() -> dict[str, str]:
    login = env("DATAFORSEO_LOGIN", required_by=NAME)
    pwd = env("DATAFORSEO_PASSWORD", required_by=NAME)
    return {"Authorization": "Basic " + base64.b64encode(f"{login}:{pwd}".encode()).decode()}


def _post(c: Collector, path: str, task: dict) -> list[dict]:
    data = c.fetch_json(f"{API}/{path}", NAME, method="POST", json_body=[task], headers=_headers())
    out = []
    for t in data.get("tasks", []):
        out += t.get("result") or []
    return out


def _source(c: Collector, url: str, payload: object, geo: str):
    return c.add_source(
        adapter=NAME,
        kind="search",
        platform="dataforseo",
        url=url,
        text=json.dumps(payload, sort_keys=True, indent=1),
        access_basis=ACCESS_BASIS,
        terms_url=TERMS_URL,
        geography=geo,
    )


def search_volume(c: Collector, keywords: list[str], geo: str = "IE") -> pd.DataFrame:
    """Columns: keyword, search_volume, cpc, competition, month, monthly_volume."""
    res = _post(
        c,
        "keywords_data/google_ads/search_volume/live",
        {"keywords": keywords, "location_code": LOCATIONS[geo], "language_code": "en"},
    )
    src = _source(c, f"{API}/keywords_data/google_ads/search_volume/live#{geo}", res, geo)
    rows = []
    for r in res:
        for m in r.get("monthly_searches") or [{}]:
            rows.append(
                {
                    "keyword": r.get("keyword"),
                    "search_volume": r.get("search_volume"),
                    "cpc": r.get("cpc"),
                    "competition": r.get("competition"),
                    "month": f"{m['year']}-{m['month']:02d}"
                    if isinstance(m.get("year"), int) and isinstance(m.get("month"), int)
                    else None,
                    "monthly_volume": m.get("search_volume"),
                    "source_id": src.id if src else None,
                }
            )
    return pd.DataFrame(rows)


def autocomplete(c: Collector, keyword: str, geo: str = "IE") -> list[str]:
    res = _post(
        c,
        "serp/google/autocomplete/live/advanced",
        {"keyword": keyword, "location_code": LOCATIONS[geo], "language_code": "en"},
    )
    _source(c, f"{API}/serp/google/autocomplete#{geo}:{keyword}", res, geo)
    return [i["suggestion"] for r in res for i in r.get("items") or [] if i.get("suggestion")]


def serp_questions(c: Collector, keyword: str, geo: str = "IE") -> dict[str, list[str]]:
    """People-also-ask questions and related searches for a keyword."""
    res = _post(
        c,
        "serp/google/organic/live/advanced",
        {"keyword": keyword, "location_code": LOCATIONS[geo], "language_code": "en"},
    )
    paa, related = [], []
    for r in res:
        for item in r.get("items") or []:
            if item.get("type") == "people_also_ask":
                paa += [q.get("title") for q in item.get("items") or [] if q.get("title")]
            elif item.get("type") == "related_searches":
                related += [q for q in item.get("items") or [] if isinstance(q, str)]
    _source(c, f"{API}/serp/google/organic#{geo}:{keyword}", {"paa": paa, "related": related}, geo)
    return {"people_also_ask": paa, "related": related}
