"""SEC EDGAR XBRL company facts (Revenues, GrossProfit, tagged customer counts).
SEC fair-access policy requires a declared User-Agent with contact details: SEC_USER_AGENT.

access_basis: public_api_terms_ok
terms: https://www.sec.gov/os/accessing-edgar-data
"""

from __future__ import annotations

import json

import pandas as pd

from nmt_engine.collect.base import Collector, env

NAME = "sec_edgar"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://www.sec.gov/os/accessing-edgar-data"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKERS = "https://www.sec.gov/files/company_tickers.json"
CONCEPTS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "GrossProfit",
    "NumberOfCustomers",
)


def _headers() -> dict[str, str]:
    return {"User-Agent": env("SEC_USER_AGENT", required_by=NAME)}


def cik_for(c: Collector, ticker: str) -> int:
    data = c.fetch_json(TICKERS, NAME, headers=_headers())
    for row in data.values():
        if row["ticker"].upper() == ticker.upper():
            return int(row["cik_str"])
    raise KeyError(ticker)


def company_facts(c: Collector, cik: int, concepts=CONCEPTS) -> pd.DataFrame:
    """Annual (10-K, FY) facts for the chosen concepts: concept, unit, fy, end, value, form."""
    url = FACTS.format(cik=cik)
    raw = c.fetch(url, NAME, headers=_headers())
    data = json.loads(raw)
    rows = []
    for taxonomy in data.get("facts", {}).values():
        for concept, body in taxonomy.items():
            if not any(concept == k or concept.endswith(k) for k in concepts):
                continue
            for unit, facts in body.get("units", {}).items():
                for f in facts:
                    if not isinstance(f.get("val"), int | float):
                        continue
                    if f.get("fp") == "FY" and str(f.get("form", "")).startswith("10-K"):
                        rows.append(
                            {
                                "concept": concept,
                                "unit": unit,
                                "fy": f.get("fy"),
                                "end": f.get("end"),
                                "value": float(f["val"]),
                                "form": f.get("form"),
                            }
                        )
    kept = json.dumps({"cik": cik, "entityName": data.get("entityName"), "facts": rows}, indent=1)
    src = c.add_source(
        adapter=NAME,
        kind="filing",
        platform="sec_edgar",
        publisher=data.get("entityName"),
        url=url,
        text=kept,
        access_basis=ACCESS_BASIS,
        terms_url=TERMS_URL,
        geography="US",
    )
    df = pd.DataFrame(rows).drop_duplicates(subset=["concept", "unit", "end", "value"])
    df["source_id"] = src.id if src else None
    return df
