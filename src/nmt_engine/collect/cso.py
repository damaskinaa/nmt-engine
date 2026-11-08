"""CSO Ireland PxStat API (JSON-stat 2.0). CSO data is published under CC BY 4.0.

access_basis: open_licence
terms: https://www.cso.ie/en/aboutus/lgdp/csodatapolicies/copyrightpolicy/
"""

from __future__ import annotations

import json

import pandas as pd

from nmt_engine.collect.base import Collector
from nmt_engine.collect.stats import dataset_source, jsonstat_frame, with_source

NAME = "cso"
ACCESS_BASIS = "open_licence"
TERMS_URL = "https://www.cso.ie/en/aboutus/lgdp/csodatapolicies/copyrightpolicy/"
API = (
    "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{table}/JSON-stat/2.0/en"
)

TABLES = {
    "household_budget_survey": "HBS01",  # average weekly household expenditure
    "earnings": "EHQ03",  # earnings and labour costs (quarterly)
    "business_demography": "BRA08",  # active enterprises by NACE
}


def table(c: Collector, code: str) -> pd.DataFrame:
    url = API.format(table=code)
    raw = c.fetch(url, NAME)
    src = dataset_source(
        c,
        adapter=NAME,
        platform="cso",
        publisher="Central Statistics Office Ireland",
        url=url,
        raw=raw,
        access_basis=ACCESS_BASIS,
        terms_url=TERMS_URL,
        geography="IE",
    )
    return with_source(jsonstat_frame(json.loads(raw)), src)


def topic(c: Collector, name: str) -> pd.DataFrame:
    return table(c, TABLES[name])
