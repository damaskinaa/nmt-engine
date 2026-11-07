"""ONS (UK): CMD API datasets (ASHE tables, UK business counts) as CSV. Releases outside the API
(Living Costs and Food, Annual Business Survey) are spreadsheet downloads listed in RELEASES;
they are OGL too but are not fetched automatically.

access_basis: open_licence (Open Government Licence v3.0)
terms: https://www.ons.gov.uk/methodology/geography/licences
"""

from __future__ import annotations

import io
import json

import pandas as pd

from nmt_engine.collect.base import Collector
from nmt_engine.collect.stats import dataset_source, with_source

NAME = "ons"
ACCESS_BASIS = "open_licence"
TERMS_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
API = "https://api.beta.ons.gov.uk/v1"

DATASETS = {
    "ashe_earnings_by_occupation": "ashe-tables-3",
    "ashe_earnings_by_industry": "ashe-tables-7-and-8",
    "uk_business_counts": "uk-business-by-enterprises-and-local-units",
}
# Release pages for spreadsheets not exposed in the API.
RELEASES = {
    "living_costs_and_food": "https://www.ons.gov.uk/peoplepopulationandcommunity/personalandhouseholdfinances/expenditure/datasets/familyspendingworkbook1detailedexpenditureandtrends",
    "annual_business_survey": "https://www.ons.gov.uk/businessindustryandtrade/business/businessservices/datasets/uknonfinancialbusinesseconomyannualbusinesssurveysectionsas",
}


MAX_CSV_BYTES = 50_000_000  # full ASHE CSVs run to hundreds of MB; use `observations` then


def _latest(c: Collector, dataset_id: str) -> dict:
    meta = c.fetch_json(f"{API}/datasets/{dataset_id}", NAME)
    return c.fetch_json(meta["links"]["latest_version"]["href"], NAME)


def _source(c: Collector, url: str, raw: str):
    return dataset_source(
        c,
        adapter=NAME,
        platform="ons",
        publisher="Office for National Statistics",
        url=url,
        raw=raw,
        access_basis=ACCESS_BASIS,
        terms_url=TERMS_URL,
        geography="GB",
    )


def dataset(c: Collector, dataset_id: str) -> pd.DataFrame:
    """Whole latest-version CSV (refused above MAX_CSV_BYTES)."""
    csv = _latest(c, dataset_id)["downloads"]["csv"]
    if int(csv.get("size") or 0) > MAX_CSV_BYTES:
        raise ValueError(f"{dataset_id} CSV is {csv['size']} bytes; use observations()")
    raw = c.fetch(csv["href"], NAME)
    return with_source(pd.read_csv(io.StringIO(raw)), _source(c, csv["href"], raw))


def observations(c: Collector, dataset_id: str, **dims: str) -> pd.DataFrame:
    """Filtered observations (every dimension must be given; at most one may be "*")."""
    version = _latest(c, dataset_id)
    url = version["links"]["self"]["href"] + "/observations"
    raw = c.fetch(url, NAME, params=dims)
    rows = []
    for ob in json.loads(raw).get("observations") or []:
        row = {d: v.get("label") or v.get("id") for d, v in (ob.get("dimensions") or {}).items()}
        row["value"] = pd.to_numeric(ob.get("observation"), errors="coerce")
        rows.append(row)
    src = _source(c, f"{url}?" + "&".join(f"{k}={v}" for k, v in sorted(dims.items())), raw)
    return with_source(pd.DataFrame(rows), src)


def topic(c: Collector, name: str) -> pd.DataFrame:
    return dataset(c, DATASETS[name])
