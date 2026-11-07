"""UK Companies House Public Data API (needs COMPANIES_HOUSE_API_KEY): active-company counts by
SIC code, accounts filing history, and turnover parsed from iXBRL accounts where present.

access_basis: public_api_terms_ok
terms: https://developer.company-information.service.gov.uk/terms-and-conditions
"""

from __future__ import annotations

import base64
import re

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


def _period_ends(xhtml: str) -> dict[str, str]:
    """contextRef -> period end date, for contexts without dimensional segments (totals)."""
    out = {}
    for m in _CONTEXT.finditer(xhtml):
        end = _PERIOD_END.search(m.group("body"))
        if end and not _SEGMENT.search(m.group("body")):
            out[m.group("id")] = end.group(1)
    return out


def ixbrl_turnover(xhtml: str) -> float | None:
    """Current-period turnover/revenue in an iXBRL document, applying `scale` and `sign`.
    Accounts also tag the comparative year, so the fact whose (undimensioned) context ends
    latest wins; documents without parseable contexts fall back to the first fact."""
    facts = list(_TURNOVER.finditer(xhtml))
    if not facts:
        return None
    ends = _period_ends(xhtml)

    def end(f: re.Match[str]) -> str:
        ref = re.search(r"\bcontextRef=\"([^\"]+)\"", f.group("attrs"))
        return ends.get(ref.group(1), "") if ref else ""

    dated = [f for f in facts if end(f)]
    m = max(dated, key=end) if dated else facts[0]
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
        except Exception:  # noqa: BLE001 - PDF-only filings return 406
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
