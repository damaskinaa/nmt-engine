"""Shared helpers for official statistics: JSON-stat 2.0 decoding and dataset Sources."""

from __future__ import annotations

import itertools
from typing import Any

import pandas as pd

from nmt_engine.collect.base import Collector


def jsonstat_frame(js: dict[str, Any]) -> pd.DataFrame:
    """Decode a JSON-stat 2.0 dataset to a tidy frame: one column per dimension (labels) plus
    `<dim>_code` and `value`. Missing cells are dropped."""
    ids: list[str] = js["id"]
    dims = js["dimension"]
    cats = []
    for d in ids:
        cat = dims[d]["category"]
        index = cat.get("index")
        if index is None:
            codes = list(cat.get("label", {}))
        elif isinstance(index, dict):
            codes = sorted(index, key=index.get)
        else:
            codes = list(index)
        labels = cat.get("label", {})
        cats.append([(code, labels.get(code, code)) for code in codes])
    values = js.get("value", [])
    get = (
        values.get
        if isinstance(values, dict)
        else (lambda i: values[i] if i < len(values) else None)
    )
    rows = []
    for i, combo in enumerate(itertools.product(*cats)):
        v = get(str(i)) if isinstance(values, dict) else get(i)
        if v is None:
            continue
        row = {}
        for d, (code, label) in zip(ids, combo, strict=True):
            row[d] = label
            row[f"{d}_code"] = code
        row["value"] = float(v)
        rows.append(row)
    return pd.DataFrame(rows)


def dataset_source(
    c: Collector,
    *,
    adapter: str,
    platform: str,
    publisher: str,
    url: str,
    raw: str,
    access_basis: str,
    terms_url: str,
    geography: str,
):
    """Register the raw dataset payload as a `stats` Source so Calc inputs can cite it."""
    return c.add_source(
        adapter=adapter,
        kind="stats",
        platform=platform,
        publisher=publisher,
        url=url,
        text=raw,
        access_basis=access_basis,
        terms_url=terms_url,
        geography=geography,
        existing_ok=True,
    )


def with_source(df: pd.DataFrame, src) -> pd.DataFrame:
    df = df.copy()
    df["source_id"] = src.id if src else None
    return df
