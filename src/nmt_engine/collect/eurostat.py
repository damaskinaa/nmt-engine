"""Eurostat dissemination API (JSON-stat 2.0). Reuse is free with attribution.

access_basis: open_licence
terms: https://ec.europa.eu/eurostat/about-us/policies/copyright
"""

from __future__ import annotations

import json

import pandas as pd

from nmt_engine.collect.base import Collector
from nmt_engine.collect.stats import dataset_source, jsonstat_frame, with_source

NAME = "eurostat"
ACCESS_BASIS = "open_licence"
TERMS_URL = "https://ec.europa.eu/eurostat/about-us/policies/copyright"
API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

# Topic -> dataset code (master prompt PR 3 list). Any other code works with `dataset`.
DATASETS = {
    "sbs_enterprises_turnover": "sbs_sc_ovw",  # SBS by NACE and size class
    "sbs_by_activity": "sbs_ovw_act",
    "hbs_by_coicop": "hbs_str_t211",  # HBS structure of consumption expenditure
    "ict_usage_enterprises": "isoc_cicce_use",  # cloud computing use by enterprises
    "hetus_time_use": "tus_00startime",
    "supply_use_io": "naio_10_cp1700",  # symmetric input-output table
    "structure_of_earnings": "earn_ses_pub2s",
}


def dataset(c: Collector, code: str, **filters: str | list[str]) -> pd.DataFrame:
    """Fetch a dataset with dimension filters (e.g. geo="IE", nace_r2="J62") as a tidy frame."""
    params = {"format": "JSON", "lang": "EN", **filters}
    raw = c.fetch(f"{API}/{code}", NAME, params=params)
    js = json.loads(raw)
    geo = filters.get("geo")
    src = dataset_source(
        c,
        adapter=NAME,
        platform="eurostat",
        publisher="Eurostat",
        url=f"{API}/{code}?" + "&".join(f"{k}={v}" for k, v in sorted(filters.items())),
        raw=raw,
        access_basis=ACCESS_BASIS,
        terms_url=TERMS_URL,
        geography=geo if isinstance(geo, str) else "EU",
    )
    return with_source(jsonstat_frame(js), src)


def topic(c: Collector, name: str, **filters: str | list[str]) -> pd.DataFrame:
    return dataset(c, DATASETS[name], **filters)
