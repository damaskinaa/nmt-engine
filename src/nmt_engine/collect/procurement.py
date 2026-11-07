"""Public procurement awards: UK Contracts Finder (OCDS) and EU TED (v3 search API).

access_basis: open_licence (Contracts Finder: OGL v3.0; TED: free reuse, Commission Decision
2011/833/EU)
terms: https://www.contractsfinder.service.gov.uk/apidocumentation and
https://ted.europa.eu/en/legal-notice
"""

from __future__ import annotations

import json
from datetime import date

from nmt_engine.collect.base import Collector, ts

NAME = "procurement"
ACCESS_BASIS = "open_licence"
TERMS_URL = "https://www.contractsfinder.service.gov.uk/apidocumentation"
TED_TERMS_URL = "https://ted.europa.eu/en/legal-notice"
CF_NOTICE = "https://www.contractsfinder.service.gov.uk/Notice/"
CF = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
TED = "https://api.ted.europa.eu/v3/notices/search"
TED_FIELDS = [
    "publication-number",
    "notice-title",
    "total-value",
    "buyer-country",
    "publication-date",
]


def contracts_finder(c: Collector, keyword: str, since: date, limit: int = 100):
    """Award notices published since `since` whose title/description mention `keyword`.
    The OCDS endpoint has no keyword filter, so matching is done locally."""
    data = c.fetch_json(
        CF,
        NAME,
        params={"stages": "award", "publishedFrom": f"{since.isoformat()}T00:00:00Z", "limit": 100},
    )
    out, kw = [], keyword.lower()
    for rel in data.get("releases", []):
        tender = rel.get("tender") or {}
        text_blob = f"{tender.get('title', '')} {tender.get('description', '')}"
        if kw not in text_blob.lower():
            continue
        awards = rel.get("awards") or []
        values = [a.get("value", {}).get("amount") for a in awards if a.get("value")]
        text = (
            f"{tender.get('title', '')}\n\n{tender.get('description', '')}\n\n"
            f"Award values: {', '.join(str(v) for v in values if v is not None) or 'n/a'} "
            f"{(awards[0].get('value') or {}).get('currency', '') if awards else ''}"
        )
        src = c.add_source(
            adapter=NAME,
            kind="procurement",
            platform="contracts_finder",
            publisher=(rel.get("buyer") or {}).get("name"),
            url=CF_NOTICE + str(rel.get("ocid") or rel.get("id")).removeprefix("ocds-b5fd17-"),
            text=text,
            published_at=ts(rel.get("date")),
            access_basis=ACCESS_BASIS,
            terms_url=TERMS_URL,
            geography="GB",
        )
        if src:
            out.append(src)
        if len(out) >= limit:
            break
    return out


def ted(c: Collector, keyword: str, since: date, limit: int = 50, country: str | None = None):
    """Contract award notices (full-text match) published since `since`."""
    q = f'FT~"{keyword}" AND notice-type=can-standard AND publication-date>={since:%Y%m%d}'
    if country:
        q += f" AND buyer-country={country}"
    data = c.fetch_json(
        TED, NAME, method="POST", json_body={"query": q, "fields": TED_FIELDS, "limit": limit}
    )
    out = []
    for n in data.get("notices", []):
        title = n.get("notice-title") or {}
        title = (
            title.get("eng") or next(iter(title.values()), "") if isinstance(title, dict) else title
        )
        countries = n.get("buyer-country") or []
        src = c.add_source(
            adapter=NAME,
            kind="procurement",
            platform="ted",
            url=f"https://ted.europa.eu/en/notice/-/detail/{n['publication-number']}",
            text=f"{title}\n\nTotal value: {json.dumps(n.get('total-value'))}\n"
            f"Buyer country: {', '.join(countries) if isinstance(countries, list) else countries}",
            published_at=ts(str(n.get("publication-date", ""))[:10] or None),
            access_basis=ACCESS_BASIS,
            terms_url=TED_TERMS_URL,
            geography=countries[0] if isinstance(countries, list) and countries else "EU",
        )
        if src:
            out.append(src)
    return out
