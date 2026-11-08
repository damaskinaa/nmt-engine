"""Public web pages (pricing, changelogs, docs, "alternatives to X") fetched with httpx only
where robots.txt allows our user agent. Optional Firecrawl rendering when FIRECRAWL_API_KEY is
set. Forbidden hosts (LinkedIn, Glassdoor, G2, Capterra, Trustpilot, ...) are refused.

access_basis: public_page_terms_ok (caller asserts the site's terms allow it; robots.txt enforced)
terms: per-site; recorded as the site's /terms URL guess unless supplied
"""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from nmt_engine.collect.base import USER_AGENT, Collector, HostNotAllowedError, env
from nmt_engine.collect.text import html_to_text

NAME = "web"
ACCESS_BASIS = "public_page_terms_ok"
TERMS_URL = "per-site"
FIRECRAWL = "https://api.firecrawl.dev/v1/scrape"


class RobotsDisallowedError(PermissionError):
    pass


def allowed(c: Collector, url: str) -> bool:
    p = urlparse(url)
    robots = f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        body = c.fetch(robots, NAME)
    except httpx.HTTPStatusError as exc:
        return exc.response.status_code in (404, 410)  # no robots.txt: allowed
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return rp.can_fetch(USER_AGENT, url)


def page(c: Collector, url: str, kind: str = "web", terms_url: str | None = None):
    if not allowed(c, url):
        raise RobotsDisallowedError(url)
    if key := env("FIRECRAWL_API_KEY"):
        data = c.fetch_json(
            FIRECRAWL,
            NAME,
            method="POST",
            json_body={"url": url, "formats": ["markdown"]},
            headers={"Authorization": f"Bearer {key}"},
        )
        text = (data.get("data") or {}).get("markdown", "")
    else:
        text = html_to_text(c.fetch(url, NAME))
    host = urlparse(url).netloc
    return c.add_source(
        adapter=NAME,
        kind=kind,
        platform="web",
        publisher=host,
        url=url,
        text=text,
        access_basis=ACCESS_BASIS,
        terms_url=terms_url or f"https://{host}/terms",
        geography="GLOBAL",
    )


PAGE_KIND = {"pricing": "pricing", "features": "web", "docs": "web", "changelog": "changelog"}


def competitor_pages(c: Collector, domain: str, paths=("pricing", "features", "docs", "changelog")):
    """Fetch common public pages for a competitor domain; skips missing or disallowed pages.

    Redirects never leave the requested host, so when the apex redirects elsewhere the page is
    requested afresh on its `www.` twin (or the apex, for a `www.` domain), under that host's own
    robots.txt."""
    hosts = [domain, domain[4:] if domain.startswith("www.") else f"www.{domain}"]
    out = []
    for path in paths:
        kind = PAGE_KIND[path]  # only pricing, features, docs and changelog pages are fetched
        for host in hosts:
            try:
                src = page(c, f"https://{host}/{path}", kind=kind)
            except HostNotAllowedError:
                continue  # cross-host redirect refused (or host not allowed): try the next host
            except (httpx.HTTPError, RobotsDisallowedError):
                break
            if src:
                out.append(src)
            break
    return out
