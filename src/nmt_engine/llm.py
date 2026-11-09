"""The one LLM client (master prompt rule 9).

Provider-agnostic (Anthropic, or any OpenAI-compatible endpoint such as TensorX via
NMT_LLM_BASE_URL); model names come from config/env. Every call is logged to
runs/<id>/llm_log.jsonl with prompt hash, host, model, tokens and a cost estimate, and cached on
disk by prompt hash so reruns are free and byte-identical (the cache, not a provider `seed`, is
what makes reruns deterministic). `no_llm=True` makes every
call raise `LLMDisabled`, which LLM-dependent steps catch to skip cleanly.

LLMs only classify, extract verbatim spans, label clusters and write prose. Callers never take
numbers from a completion.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from nmt_engine.config import repo_root
from nmt_engine.util import canonical_json, sha256_text

DEFAULT_BASE_URL = {
    "anthropic": "https://api.anthropic.com/v1",
    "openai": "https://api.openai.com/v1",
}
ENDPOINT = {"anthropic": "/messages", "openai": "/chat/completions"}
DEFAULT_MODEL = {"anthropic": "claude-haiku-4-5", "openai": "gpt-4o-mini"}
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
# OpenAI-compatible hosts with their own key variable (checked before KEY_ENV).
HOST_KEY_ENV = {"api.tensorx.ai": "TENSORX_API_KEY"}
RETRY_STATUS = (429, 500, 502, 503, 504, 529)
BACKOFF_START, BACKOFF_MAX = 5.0, 60.0
# USD per million (input, output) tokens, from the providers' public price pages. A model that is
# not listed gets cost_usd = null in the log rather than a guess. Override with NMT_LLM_PRICES
# ('{"model": [in, out]}').
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-opus-4-1": (15.0, 75.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
    "gpt-4.1-mini": (0.40, 1.60),
    # TensorX (tensorx.ai/models, 8 Nov 2026)
    "z-ai/glm-5.3": (1.75, 4.50),
    "deepseek/deepseek-v4.1-flash": (0.50, 1.50),
    "z-ai/glm-5.3-flash": (0.20, 0.50),
    "moonshotai/kimi-k3.1-pro": (3.00, 15.00),
    "qwen/qwen3.8-2.4t-a95b": (2.50, 6.00),
}
# Auditor/council default for each producer family: always another vendor.
CROSS_VENDOR_AUDITOR = {"z-ai": "moonshotai/kimi-k3.1-pro"}
FALLBACK_AUDITOR = "z-ai/glm-5.3"


class LLMDisabled(Exception):
    """--no-llm, or no API key: the calling step must skip."""


class LLMError(Exception):
    pass


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float | None:
    prices = dict(PRICES)
    if os.environ.get("NMT_LLM_PRICES"):
        prices.update({k: tuple(v) for k, v in json.loads(os.environ["NMT_LLM_PRICES"]).items()})
    if model not in prices:
        return None
    p_in, p_out = prices[model]
    return round((tokens_in * p_in + tokens_out * p_out) / 1e6, 6)


def model_family(model: str) -> str:
    """Vendor family of a model id: the `vendor/` prefix, else a known name prefix."""
    if "/" in model:
        return model.split("/", 1)[0].lower()
    for prefix, fam in (("claude", "anthropic"), ("gpt", "openai"), ("o1", "openai")):
        if model.lower().startswith(prefix):
            return fam
    return model.split("-", 1)[0].lower()


def auditor_model(producer: str, override: str | None = None) -> str:
    """Model for an auditor/council step: NMT_LLM_AUDITOR_MODEL or a cross-vendor default. Raises
    if it is from the producer's family (an auditor must not grade its own vendor's output)."""
    model = override or os.environ.get("NMT_LLM_AUDITOR_MODEL")
    if not model:
        model = CROSS_VENDOR_AUDITOR.get(model_family(producer), FALLBACK_AUDITOR)
    if model_family(model) == model_family(producer):
        raise ValueError(f"auditor {model!r} is from the same family as producer {producer!r}")
    return model


def backoff(attempt: int, retry_after: str | None) -> float:
    """Seconds to wait before retry `attempt` (0-based): `retry-after` if the server sent one,
    else 5 s doubling (+-20% jitter), capped at 60 s."""
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return min(BACKOFF_MAX, BACKOFF_START * 2**attempt * random.uniform(0.8, 1.2))


def parse_json(text: str) -> Any:
    """The first JSON object/array in a completion (models sometimes wrap it in a fence)."""
    m = re.search(r"[\[{]", text)
    if not m:
        raise LLMError("completion contains no JSON")
    try:
        return json.JSONDecoder().raw_decode(text[m.start() :])[0]
    except ValueError as exc:
        raise LLMError(f"completion is not valid JSON: {exc}") from exc


@dataclass
class LLM:
    run_dir: Path
    provider: str = field(default_factory=lambda: os.environ.get("NMT_LLM_PROVIDER", "anthropic"))
    model: str | None = None
    base_url: str | None = None
    no_llm: bool = False
    cache_dir: Path | None = None
    client: httpx.Client | None = None
    max_tokens: int = field(
        default_factory=lambda: int(os.environ.get("NMT_LLM_MAX_TOKENS") or 4096)
    )
    reasoning_effort: str | None = field(
        default_factory=lambda: os.environ.get("NMT_LLM_REASONING_EFFORT") or None
    )
    retries: int = 6
    timeout: float = 180
    sleep: Callable[[float], None] = time.sleep
    calls: int = 0
    cost: float = 0.0
    unpriced_calls: int = 0

    def __post_init__(self) -> None:
        if self.provider not in DEFAULT_MODEL:
            raise ValueError(f"unknown LLM provider {self.provider!r}")
        self.model = self.model or os.environ.get("NMT_LLM_MODEL") or DEFAULT_MODEL[self.provider]
        base = (
            self.base_url or os.environ.get("NMT_LLM_BASE_URL") or DEFAULT_BASE_URL[self.provider]
        )
        self.base_url = base.rstrip("/")
        self.cache_dir = Path(self.cache_dir or repo_root() / "cache" / "llm")
        self.run_dir = Path(self.run_dir)

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    @property
    def key_env(self) -> str:
        if self.provider == "openai" and self.host in HOST_KEY_ENV:
            return HOST_KEY_ENV[self.host]
        return KEY_ENV[self.provider]

    @property
    def enabled(self) -> bool:
        return not self.no_llm and bool(os.environ.get(self.key_env))

    def complete(
        self,
        prompt: str,
        system: str = "",
        purpose: str = "",
        json_mode: bool = False,
        check: Callable[[str], Any] | None = None,
    ) -> str:
        """`check` runs on a fresh answer before it is cached; an `LLMError` from it is billed
        and logged but leaves the cache empty so a rerun asks again."""
        if self.no_llm:
            raise LLMDisabled("--no-llm")
        json_mode = json_mode and self.provider == "openai"  # Anthropic has no JSON mode flag
        req = {
            "provider": self.provider,
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "max_tokens": self.max_tokens,
        }
        if self.base_url != DEFAULT_BASE_URL[self.provider]:
            req["base_url"] = self.base_url
        if json_mode:
            req["json_mode"] = True
        if self.reasoning_effort and self.provider == "openai":
            req["reasoning_effort"] = self.reasoning_effort
        phash = sha256_text(canonical_json(req))
        cached = self.cache_dir / f"{phash}.json"
        if cached.is_file():
            hit = json.loads(cached.read_text("utf-8"))
            self._log(purpose, phash, hit["tokens_in"], hit["tokens_out"], cached=True)
            return hit["text"]
        key = os.environ.get(self.key_env)
        if not key:
            raise LLMDisabled(f"${self.key_env} is not set")
        text, t_in, t_out, truncated = self._call(key, system, prompt, json_mode)
        if truncated:  # billed, never cached: a cut-off answer must not be replayed
            self._log(purpose, phash, t_in, t_out, cached=False, truncated=True)
            raise LLMError(f"{self.host} answer cut off at max_tokens={self.max_tokens}")
        if check is not None:
            try:
                check(text)
            except LLMError:
                self._log(purpose, phash, t_in, t_out, cached=False)
                raise
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        hit = {"text": text, "tokens_in": t_in, "tokens_out": t_out, "model": self.model}
        cached.write_text(json.dumps(hit, ensure_ascii=False), "utf-8")
        self._log(purpose, phash, t_in, t_out, cached=False)
        return text

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def complete_json(self, prompt: str, system: str = "", purpose: str = "") -> Any:
        return parse_json(self.complete(prompt, system, purpose, json_mode=True, check=parse_json))

    def _call(
        self, key: str, system: str, prompt: str, json_mode: bool
    ) -> tuple[str, int, int, bool]:
        if self.client is None:
            self.client = httpx.Client(timeout=self.timeout)  # one pooled client per LLM, reused
        client = self.client
        url = self.base_url + ENDPOINT[self.provider]
        if self.provider == "anthropic":
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            body: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                body["system"] = system
        else:
            headers = {"Authorization": f"Bearer {key}"}
            msgs = ([{"role": "system", "content": system}] if system else []) + [
                {"role": "user", "content": prompt}
            ]
            body = {
                "model": self.model,
                "max_completion_tokens": self.max_tokens,
                "temperature": 0,
                "messages": msgs,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            if self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
        for attempt in range(self.retries + 1):
            try:
                resp = client.post(url, headers=headers, json=body)
            except httpx.TransportError as exc:  # timeouts, dropped connections
                if attempt == self.retries:
                    raise LLMError(f"{self.host} {type(exc).__name__}") from exc
                self.sleep(backoff(attempt, None))
                continue
            if resp.status_code not in RETRY_STATUS or attempt == self.retries:
                break
            self.sleep(backoff(attempt, resp.headers.get("retry-after")))
        if resp.status_code != 200:
            raise LLMError(f"{self.host} HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if self.provider == "anthropic":
            text = "".join(b.get("text", "") for b in data.get("content", []))
            usage = data.get("usage", {})
            cut = data.get("stop_reason") == "max_tokens"
            return text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)), cut
        usage = data.get("usage", {})
        choice = data["choices"][0]
        text = choice["message"]["content"] or ""
        cut = choice.get("finish_reason") == "length"
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), cut

    def _log(
        self, purpose: str, phash: str, t_in: int, t_out: int, cached: bool, truncated=False
    ) -> None:
        cost = 0.0 if cached else cost_usd(self.model or "", t_in, t_out)
        self.calls += 0 if cached else 1
        self.cost += cost or 0.0
        self.unpriced_calls += cost is None
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "purpose": purpose,
            "prompt_hash": phash,
            "provider": self.provider,
            "host": self.host,
            "model": self.model,
            "tokens_in": t_in,
            "tokens_out": t_out,
            "cost_usd": cost,
            "cached": cached,
        }
        if truncated:
            entry["truncated"] = True
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "llm_log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
