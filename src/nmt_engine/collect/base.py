"""Shared collector plumbing: polite HTTP (cache, rate limit, retries, forbidden hosts),
Source + retrieval-log writing, salted author hashes, as_of_date on everything.

Each adapter module states its `access_basis` and terms URL in its docstring and in
`ACCESS_BASIS` / `TERMS_URL`. Adapters never log in, never bypass CAPTCHAs and never fetch a
forbidden host.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from nmt_engine.gates.base import GateConfig
from nmt_engine.schema import RetrievalLogEntry, Source
from nmt_engine.store import Store
from nmt_engine.util import author_hash, sha256_text

FORBIDDEN_HOSTS: tuple[str, ...] = GateConfig().forbidden_hosts
MAX_REDIRECTS = 5
CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key"})
USER_AGENT = "nmt-engine/0.1 (outside-in research; +https://github.com/damaskinaa/nmt-engine)"


class ForbiddenHostError(ValueError):
    """The URL's host is on the forbidden list (ARCHITECTURE §7)."""


class MissingKeyError(RuntimeError):
    """An adapter that needs an API key was used without one."""


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(
    r"(?<![\w/.-])(?:\+\d{1,3}[ .-]?)?(?:\(?\d{1,4}\)?[ .-]){2,4}\d{3,4}(?![\w/.-])"
)


def scrub_pii(text: str) -> str:
    """Mask e-mail addresses and phone numbers before public text is stored."""

    def phone(m: re.Match[str]) -> str:
        return "[phone]" if sum(ch.isdigit() for ch in m.group()) >= 9 else m.group()

    return _PHONE.sub(phone, _EMAIL.sub("[email]", text))


def _scrub_json(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_pii(value)
    if isinstance(value, list):
        return [_scrub_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_json(v) for k, v in value.items()}
    return value


def scrub_payload(text: str) -> str:
    """scrub_pii for a response body; JSON is masked string by string so escapes stay valid."""
    try:
        data = json.loads(text)
    except ValueError:
        return scrub_pii(text)
    return json.dumps(_scrub_json(data), ensure_ascii=False)


_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


def is_internal_host(host: str) -> bool:
    """Loopback, private, link-local (e.g. cloud metadata) or reserved literal IPs and
    local-only names. Hostnames are not resolved, so tests stay offline."""
    host = host.lower().strip("[]").rstrip(".")
    if not host or host == "localhost" or host.endswith(_INTERNAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not ip.is_global or ip.is_multicast


def is_forbidden(url: str) -> bool:
    """Denylisted platforms, and any internal/non-public host (egress control)."""
    host = (urlparse(url).hostname or "").lower()
    return any(f in host for f in FORBIDDEN_HOSTS) or is_internal_host(host)


SECRET_PARAMS = frozenset(
    {"key", "api_key", "app_key", "app_id", "client_secret", "token", "access_token"}
)


def redact(url: str) -> str:
    """Drop secret query values before a URL is logged."""
    p = urlparse(url)
    if not p.query:
        return url
    q = [(k, "REDACTED" if k.lower() in SECRET_PARAMS else v) for k, v in parse_qsl(p.query, True)]
    return urlunparse(p._replace(query=urlencode(q)))


def env(name: str, required_by: str | None = None) -> str | None:
    value = os.environ.get(name) or None
    if value is None and required_by:
        raise MissingKeyError(f"{required_by} needs ${name}")
    return value


@dataclass
class Collector:
    """Per-run collection context. All adapters write through `fetch` and `add_source`."""

    run_dir: Path
    as_of: date = field(default_factory=lambda: datetime.now(UTC).date())
    geo: str = "IE"
    cache_dir: Path | None = None
    min_interval_s: float = 1.0
    retries: int = 3
    client: httpx.Client | None = None
    salt: str | None = None
    _last: dict[str, float] = field(default_factory=dict)
    _ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        (self.run_dir / "sources").mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(self.cache_dir or self.run_dir / "cache")
        self.client = self.client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=False
        )
        self.store = Store(self.run_dir / "store")
        self._ids = set(self.store.current("source"))

    # --- HTTP ---------------------------------------------------------------------------

    def _cache_key(
        self, method: str, url: str, body: Any, headers: Mapping[str, str] | None = None
    ) -> str:
        # Headers carry credentials (Authorization, API keys) and content negotiation, so
        # responses fetched under different accounts never share a cache entry. Only the
        # hash is written to disk.
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        raw = f"{method} {url} {canonical(body)} {canonical(hdrs)} {self.as_of.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delay = self.min_interval_s - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
        self._last[host] = time.monotonic()

    def fetch(
        self,
        url: str,
        adapter: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        method: str = "GET",
        json_body: Any = None,
    ) -> str:
        """Fetch text with cache (URL + params + body + headers + as_of date), rate limit and
        retries.
        The body is PII-masked before it is cached or returned."""
        if params:
            url = f"{url}{'&' if '?' in url else '?'}{urlencode(params, doseq=True)}"
        if is_forbidden(url):
            raise ForbiddenHostError(url)
        key = self._cache_key(method, url, json_body, headers)
        cached = self.cache_dir / f"{key}.json"
        host = urlparse(url).hostname or ""
        if cached.is_file():
            entry = json.loads(cached.read_text("utf-8"))
            self._log(url, host, adapter, entry["status"], None, key)
            return entry["text"]
        resp = self._request(method, url, host, dict(headers or {}), json_body)
        self._log(url, host, adapter, resp.status_code, None, key)
        resp.raise_for_status()
        text = scrub_payload(resp.text)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({"status": resp.status_code, "text": text}), "utf-8")
        return text

    def _request(
        self, method: str, url: str, host: str, headers: dict[str, str], body: Any
    ) -> httpx.Response:
        """Send with retries; follow redirects by hand so every hop passes the host check."""
        for _hop in range(MAX_REDIRECTS + 1):
            resp = None
            for attempt in range(self.retries + 1):
                self._wait(host)
                resp = self.client.request(
                    method, url, headers=headers, json=body, follow_redirects=False
                )
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    break
                time.sleep(float(resp.headers.get("Retry-After", 2**attempt)))
            assert resp is not None
            if not resp.has_redirect_location:
                return resp
            prev = resp.url
            url = str(prev.join(resp.headers["Location"]))
            if is_forbidden(url):
                raise ForbiddenHostError(url)
            nxt = urlparse(url)
            host = nxt.hostname or ""
            if host != prev.host or (prev.scheme == "https" and nxt.scheme != "https"):
                headers = {k: v for k, v in headers.items() if k.lower() not in CREDENTIAL_HEADERS}
            if resp.status_code == 303 or (resp.status_code in (301, 302) and method == "POST"):
                method, body = "GET", None
        raise httpx.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects", request=resp.request)

    def download(self, url: str, adapter: str, dest: Path) -> Path:
        """Stream a large file to `dest` (bypasses the text cache); redirects are followed by
        hand so every hop passes the host check, like `fetch`."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        for _hop in range(MAX_REDIRECTS + 1):
            if is_forbidden(url):
                raise ForbiddenHostError(url)
            host = urlparse(url).hostname or ""
            self._wait(host)
            with self.client.stream("GET", url, follow_redirects=False) as resp:
                if resp.has_redirect_location:
                    url = str(resp.url.join(resp.headers["Location"]))
                    continue
                self._log(url, host, adapter, resp.status_code, None, None)
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
                return dest
        raise httpx.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects")

    def fetch_json(self, url: str, adapter: str, **kw: Any) -> Any:
        return json.loads(self.fetch(url, adapter, **kw))

    def _log(
        self,
        url: str,
        host: str,
        adapter: str,
        status: int | None,
        sid: str | None,
        key: str | None,
        sha: str | None = None,
    ) -> RetrievalLogEntry:
        entry = RetrievalLogEntry(
            source_id=sid,
            url=redact(url),
            host=host,
            retrieved_at=datetime.now(UTC),
            adapter=adapter,
            status_code=status,
            sha256=sha,
            cache_key=key,
        )
        with (self.run_dir / "retrieval_log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json(exclude_none=True) + "\n")
        return entry

    # --- Sources ------------------------------------------------------------------------

    def add_source(
        self,
        *,
        adapter: str,
        kind: str,
        platform: str,
        url: str,
        text: str,
        access_basis: str,
        terms_url: str,
        author: str | None = None,
        published_at: datetime | None = None,
        publisher: str | None = None,
        geography: str | None = None,
        as_of_date: date | None = None,
        existing_ok: bool = False,
    ) -> Source | None:
        """Store PII-scrubbed text under sources/<id>.txt, append the Source and its log entry.
        Returns None for empty text, and for an already-stored source unless `existing_ok`
        (then the stored Source is returned so callers can still cite it)."""
        text = scrub_pii(text.strip())
        if not text:
            return None
        if is_forbidden(url):
            raise ForbiddenHostError(url)
        sid = "S-" + hashlib.sha256(f"{url}\n{text}".encode()).hexdigest()[:16]
        if sid in self._ids:
            return self.store.current("source").get(sid) if existing_ok else None
        rel = f"sources/{sid}.txt"
        (self.run_dir / rel).write_text(text, "utf-8")
        src = Source(
            id=sid,
            kind=kind,
            platform=platform,
            publisher=publisher,
            url=url,
            author_hash=author_hash(platform, author, self.salt) if author else None,
            retrieved_at=datetime.now(UTC),
            published_at=published_at,
            as_of_date=as_of_date or (published_at.date() if published_at else self.as_of),
            geography=geography or self.geo,
            access_basis=access_basis,
            terms_url=terms_url,
            text_path=rel,
            sha256=sha256_text(text),
        )
        self.store.append(src)
        self._log(url, urlparse(url).hostname or "", adapter, 200, sid, None, src.sha256)
        self._ids.add(sid)
        return src


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def ts(value: Any) -> datetime | None:
    """Parse epoch seconds or ISO-8601 into an aware datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC)
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
