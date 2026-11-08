"""UK Companies House Public Data API (needs COMPANIES_HOUSE_API_KEY): active-company counts by
SIC code, accounts filing history, and turnover parsed from iXBRL accounts where present.

access_basis: public_api_terms_ok
terms: https://developer.company-information.service.gov.uk/terms-and-conditions
"""

from __future__ import annotations

import base64
import re

import httpx

from nmt_engine.collect.base import Collector, env

NAME = "companies_house"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://developer.company-information.service.gov.uk/terms-and-conditions"
API = "https://api.company-information.service.gov.uk"
DOCS = "https://document-api.company-information.service.gov.uk"

_TURNOVER = re.compile(
    r"<ix:nonFraction\b(?P<attrs>[^>]*\bname=\"[^\"]*:(?:TurnoverRevenue|Turnover|Revenue)\"[^>]*)>"
    r"(?P<value>[^<]*)</ix:nonFraction>",
    re.IGNORECASE,
)
_CONTEXT = re.compile(
    r"<(?:\w+:)?context\b[^>]*\bid=\"(?P<id>[^\"]+)\"[^>]*>(?P<body>.*?)</(?:\w+:)?context>",
    re.IGNORECASE | re.DOTALL,
)
_PERIOD_END = re.compile(r"<(?:\w+:)?(?:endDate|instant)>\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_SEGMENT = re.compile(r"<(?:\w+:)?(?:segment|scenario)\b", re.IGNORECASE)


def _headers() -> dict[str, str]:
    key = env("COMPANIES_HOUSE_API_KEY", required_by=NAME)
    return {"Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode()}


def count_by_sic(c: Collector, sic: str) -> int:
    """Active companies registered with a SIC code (advanced search `hits`)."""
    url = f"{API}/advanced-search/companies"
    data = c.fetch_json(
        url,
        NAME,
        params={"sic_codes": sic, "company_status": "active", "size": 1},
        headers=_headers(),
    )
    c.add_source(
        adapter=NAME,
        kind="stats",
        platform="companies_house",
        publisher="Companies House",
        url=f"{url}?sic_codes={sic}&company_status=active",
        text=f"Active companies with SIC {sic}: {data.get('hits', 0)}",
        access_basis=ACCESS_BASIS,
        terms_url=TERMS_URL,
        geography="GB",
    )
    return int(data.get("hits", 0))


def accounts(c: Collector, company_number: str, limit: int = 5) -> list[dict]:
    data = c.fetch_json(
        f"{API}/company/{company_number}/filing-history",
        NAME,
        params={"category": "accounts", "items_per_page": limit},
        headers=_headers(),
    )
    return data.get("items", [])


def _contexts(xhtml: str) -> dict[str, str | None]:
    """contextRef -> period end date; None for dimensioned (segment/scenario) contexts."""
    out: dict[str, str | None] = {}
    for m in _CONTEXT.finditer(xhtml):
        end = _PERIOD_END.search(m.group("body"))
        dimensioned = _SEGMENT.search(m.group("body"))
        out[m.group("id")] = None if dimensioned else (end.group(1) if end else "")
    return out


def ixbrl_turnover(xhtml: str) -> float | None:
    """Current-period turnover/revenue in an iXBRL document, applying `scale` and `sign`.
    Accounts also tag the comparative year, so the fact whose undimensioned context ends latest
    wins. Facts in dimensioned contexts are segment amounts, never the company total; facts
    whose context cannot be parsed are a last resort (first one wins)."""
    contexts = _contexts(xhtml)
    dated, unknown = [], []
    for f in _TURNOVER.finditer(xhtml):
        ref = re.search(r"\bcontextRef=\"([^\"]+)\"", f.group("attrs"))
        end = contexts.get(ref.group(1), "") if ref else ""
        if end:
            dated.append((end, f))
        elif end == "":
            unknown.append(f)
    if dated:
        m = max(dated, key=lambda t: t[0])[1]
    elif unknown:
        m = unknown[0]
    else:
        return None
    raw = re.sub(r"[^\d.]", "", m.group("value"))
    if not raw:
        return None
    attrs = m.group("attrs")
    scale = re.search(r"\bscale=\"(-?\d+)\"", attrs)
    value = float(raw) * 10 ** int(scale.group(1) if scale else 0)
    return -value if re.search(r"\bsign=\"-\"", attrs) else value


def turnover(c: Collector, company_number: str) -> float | None:
    """Turnover from the most recent accounts filed as iXBRL, else None."""
    for item in accounts(c, company_number):
        meta_url = (item.get("links") or {}).get("document_metadata")
        if not meta_url:
            continue
        doc_id = meta_url.rstrip("/").split("/")[-1]
        url = f"{DOCS}/document/{doc_id}/content"
        try:
            xhtml = c.fetch(url, NAME, headers={**_headers(), "Accept": "application/xhtml+xml"})
        except httpx.HTTPStatusError:  # PDF-only filings return 406
            continue
        value = ixbrl_turnover(xhtml)
        if value is not None:
            c.add_source(
                adapter=NAME,
                kind="filing",
                platform="companies_house",
                publisher=company_number,
                url=url,
                text=xhtml,
                access_basis=ACCESS_BASIS,
                terms_url=TERMS_URL,
                geography="GB",
            )
            return value
    return None
