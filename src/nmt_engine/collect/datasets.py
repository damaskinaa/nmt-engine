"""Public datasets: Kickstarter (Web Robots monthly dumps), npm / PyPI download counts, the
Twin-2K-500 digital-twin panel (Hugging Face), and Product Hunt (disabled by default).

access_basis per source:
- Web Robots Kickstarter dataset: public_page_terms_ok (https://webrobots.io/kickstarter-datasets/)
- npm downloads API: public_api_terms_ok (https://github.com/npm/registry/blob/main/docs/download-counts.md)
- pypistats.org API: public_api_terms_ok (https://pypistats.org/api/)
- Twin-2K-500: open_licence, CC BY 4.0 (https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500)
- Product Hunt API v2: commercial use needs Product Hunt's approval
  (https://api.producthunt.com/v2/docs), so `producthunt_posts` needs PRODUCTHUNT_TOKEN *and*
  NMT_PRODUCTHUNT_TERMS_OK=1.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from nmt_engine.collect.base import (
    Collector,
    MissingKeyError,
    env,
)

NAME = "datasets"
KICKSTARTER_INDEX = "https://webrobots.io/kickstarter-datasets/"
KICKSTARTER_TERMS = "https://webrobots.io/kickstarter-datasets/"
NPM = "https://api.npmjs.org/downloads/range/{start}:{end}/{package}"
NPM_TERMS = "https://github.com/npm/registry/blob/main/docs/download-counts.md"
PYPI = "https://pypistats.org/api/packages/{package}/overall"
PYPI_TERMS = "https://pypistats.org/api/"
TWIN = "LLM-Digital-Twin/Twin-2K-500"
TWIN_ROWS = "https://datasets-server.huggingface.co/rows"
TWIN_META = "https://huggingface.co/api/datasets/" + TWIN
TWIN_TERMS = "https://huggingface.co/datasets/" + TWIN
PH = "https://api.producthunt.com/v2/api/graphql"
PH_TERMS = "https://api.producthunt.com/v2/docs"
KS_COLUMNS = [
    "id",
    "name",
    "blurb",
    "goal",
    "pledged",
    "usd_pledged",
    "backers_count",
    "state",
    "country",
    "currency",
    "created_at",
    "launched_at",
    "deadline",
    "category",
]


# --- Kickstarter -----------------------------------------------------------------------------


def kickstarter_dumps(c: Collector) -> list[str]:
    """Monthly dump URLs listed on the Web Robots index page (newest first)."""
    page = c.fetch(KICKSTARTER_INDEX, NAME)
    return sorted(set(re.findall(r"https://[^\"']+Kickstarter[^\"']+\.zip", page)), reverse=True)


def kickstarter_download(c: Collector, url: str, dest: Path) -> Path:
    """Stream a dump zip to `dest` (dumps are hundreds of MB, so they bypass the text cache)."""
    return c.download(url, NAME, dest)


def kickstarter_projects(zip_path: Path, category: str | None = None) -> pd.DataFrame:
    """Load a Web Robots dump (zip of CSVs or JSON lines) into a tidy frame; optional category
    substring filter on the category slug/name."""
    frames = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            with zf.open(name) as fh:
                if name.endswith(".csv"):
                    frames.append(pd.read_csv(fh))
                elif name.endswith((".json", ".jsonl")):
                    rows = [
                        json.loads(ln).get("data", json.loads(ln))
                        for ln in io.TextIOWrapper(fh)
                        if ln.strip()
                    ]
                    frames.append(pd.DataFrame(rows))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=KS_COLUMNS)
    if "category" in df:
        df["category"] = df["category"].map(_category_name)
    df = df[[col for col in KS_COLUMNS if col in df]]
    if category:
        df = df[df["category"].fillna("").str.contains(category, case=False)]
    return df.reset_index(drop=True)


def _category_name(value) -> str | None:
    if isinstance(value, str) and value.startswith("{"):
        value = json.loads(value)
    if isinstance(value, dict):
        return value.get("slug") or value.get("name")
    return value if isinstance(value, str) else None


# --- npm / PyPI ------------------------------------------------------------------------------


def npm_downloads(c: Collector, package: str, start: date, end: date) -> pd.DataFrame:
    url = NPM.format(start=start.isoformat(), end=end.isoformat(), package=package)
    raw = c.fetch(url, NAME)
    src = c.add_source(
        adapter=NAME,
        kind="dataset",
        platform="npm",
        url=url,
        text=raw,
        access_basis="public_api_terms_ok",
        terms_url=NPM_TERMS,
        geography="GLOBAL",
    )
    df = pd.DataFrame(json.loads(raw).get("downloads", []))
    df["package"], df["source_id"] = package, src.id if src else None
    return df


def pypi_downloads(c: Collector, package: str) -> pd.DataFrame:
    url = PYPI.format(package=package)
    raw = c.fetch(url, NAME, params={"mirrors": "false"})
    src = c.add_source(
        adapter=NAME,
        kind="dataset",
        platform="pypi",
        url=url,
        text=raw,
        access_basis="public_api_terms_ok",
        terms_url=PYPI_TERMS,
        geography="GLOBAL",
    )
    df = pd.DataFrame(json.loads(raw).get("data", []))
    df["package"], df["source_id"] = package, src.id if src else None
    return df


# --- Twin-2K-500 -----------------------------------------------------------------------------


def twin2k(
    c: Collector, config: str = "wave_split", offset: int = 0, length: int = 100
) -> pd.DataFrame:
    """Rows from the Twin-2K-500 panel via the HF datasets-server. Refuses if the licence on the
    dataset card is no longer CC BY 4.0."""
    meta = c.fetch_json(TWIN_META, NAME)
    licences = (meta.get("cardData") or {}).get("license") or []
    if "cc-by-4.0" not in (licences if isinstance(licences, list) else [licences]):
        raise PermissionError(f"{TWIN} licence changed: {licences}")
    raw = c.fetch(
        TWIN_ROWS,
        NAME,
        params={
            "dataset": TWIN,
            "config": config,
            "split": "data",
            "offset": offset,
            "length": min(100, length),
        },
    )
    data = json.loads(raw)
    src = c.add_source(
        adapter=NAME,
        kind="dataset",
        platform="huggingface",
        publisher=TWIN,
        url=f"{TWIN_TERMS}?config={config}&offset={offset}",
        text=raw,
        access_basis="open_licence",
        terms_url=TWIN_TERMS,
        geography="US",
    )
    df = pd.DataFrame([r["row"] for r in data.get("rows", [])])
    df["source_id"] = src.id if src else None
    return df


# --- Product Hunt ----------------------------------------------------------------------------

PH_QUERY = """query($topic: String!, $n: Int!) { posts(topic: $topic, first: $n, order: VOTES) {
  edges { node { name tagline description url votesCount createdAt } } } }"""


def producthunt_posts(c: Collector, topic: str, limit: int = 20):
    token = env("PRODUCTHUNT_TOKEN", required_by="producthunt")
    if env("NMT_PRODUCTHUNT_TERMS_OK") != "1":
        raise MissingKeyError(
            "Product Hunt API needs approval for commercial use; "
            "set NMT_PRODUCTHUNT_TERMS_OK=1 once granted"
        )
    data = c.fetch_json(
        PH,
        NAME,
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        json_body={"query": PH_QUERY, "variables": {"topic": topic, "n": limit}},
    )
    out = []
    for edge in (data.get("data") or {}).get("posts", {}).get("edges", []):
        n = edge["node"]
        src = c.add_source(
            adapter=NAME,
            kind="web",
            platform="producthunt",
            url=n["url"],
            text=f"{n['name']}: {n.get('tagline', '')}\n\n{n.get('description') or ''}"
            f"\n\nVotes: {n.get('votesCount')}",
            access_basis="public_api_terms_ok",
            terms_url=PH_TERMS,
            geography="GLOBAL",
        )
        if src:
            out.append(src)
    return out
