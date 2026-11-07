"""Internet Archive Wayback Machine: CDX snapshot lists, archived page text, and diffs between
consecutive snapshots (e.g. pricing-page changes).

access_basis: public_api_terms_ok
terms: https://archive.org/about/terms.php (CDX server API is public; one request/second)
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from nmt_engine.collect.base import Collector
from nmt_engine.collect.text import html_to_text

NAME = "wayback"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://archive.org/about/terms.php"
CDX = "https://web.archive.org/cdx/search/cdx"


def snapshots(c: Collector, url: str, since: date, limit: int = 12) -> list[dict]:
    """One snapshot per month (collapse=timestamp:6), status 200 only."""
    rows = c.fetch_json(
        CDX,
        NAME,
        params={
            "url": url,
            "from": since.strftime("%Y%m%d"),
            "output": "json",
            "filter": "statuscode:200",
            "collapse": "timestamp:6",
            "limit": limit,
        },
    )
    if not rows:
        return []
    head, *body = rows
    return [dict(zip(head, r, strict=False)) for r in body]


def _when(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def snapshot_text(c: Collector, original: str, stamp: str) -> str:
    raw = c.fetch(f"https://web.archive.org/web/{stamp}id_/{original}", NAME)
    return html_to_text(raw)


def diff(old: str, new: str) -> str:
    """Lines added and removed between snapshots, ignoring order and blank lines."""
    a = {ln.strip() for ln in old.splitlines() if ln.strip()}
    b = {ln.strip() for ln in new.splitlines() if ln.strip()}
    added = [f"+{ln}" for ln in dict.fromkeys(x.strip() for x in new.splitlines()) if ln in b - a]
    removed = [f"-{ln}" for ln in dict.fromkeys(x.strip() for x in old.splitlines()) if ln in a - b]
    return "\n".join(added + removed)


def collect(c: Collector, url: str, since: date, limit: int = 6, kind: str = "pricing"):
    """Snapshot texts plus a diff source for every change between consecutive snapshots."""
    out, prev = [], None
    for snap in snapshots(c, url, since, limit):
        stamp, original = snap["timestamp"], snap["original"]
        text = snapshot_text(c, original, stamp)
        when = _when(stamp)
        common = {
            "adapter": NAME,
            "platform": "wayback",
            "publisher": original,
            "published_at": when,
            "access_basis": ACCESS_BASIS,
            "terms_url": TERMS_URL,
            "geography": "GLOBAL",
        }
        snap_url = f"https://web.archive.org/web/{stamp}/{original}"
        if src := c.add_source(kind=kind, url=snap_url, text=text, **common):
            out.append(src)
        if prev is not None and (d := diff(prev[1], text)):
            change = f"Changes on {original} between {prev[0]} and {stamp}:\n{d}"
            if src := c.add_source(
                kind="changelog", url=f"{snap_url}#diff-{prev[0]}", text=change, **common
            ):
                out.append(src)
        prev = (stamp, text)
    return out
