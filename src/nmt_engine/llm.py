"""The one LLM client (master prompt rule 9).

Provider-agnostic (Anthropic default, OpenAI optional); model names come from config/env. Every
call is logged to runs/<id>/llm_log.jsonl with prompt hash, model, tokens and a cost estimate, and
cached on disk by prompt hash so reruns are free and byte-identical. `no_llm=True` makes every
call raise `LLMDisabled`, which LLM-dependent steps catch to skip cleanly.

LLMs only classify, extract verbatim spans, label clusters and write prose. Callers never take
numbers from a completion.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from nmt_engine.config import repo_root
from nmt_engine.util import canonical_json, sha256_text

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = {"anthropic": "claude-haiku-4-5", "openai": "gpt-4o-mini"}
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
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
}


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
    no_llm: bool = False
    cache_dir: Path | None = None
    client: httpx.Client | None = None
    max_tokens: int = 4096
    retries: int = 4
    calls: int = 0
    cost: float = 0.0

    def __post_init__(self) -> None:
        if self.provider not in DEFAULT_MODEL:
            raise ValueError(f"unknown LLM provider {self.provider!r}")
        self.model = self.model or os.environ.get("NMT_LLM_MODEL") or DEFAULT_MODEL[self.provider]
        self.cache_dir = Path(self.cache_dir or repo_root() / "cache" / "llm")
        self.run_dir = Path(self.run_dir)

    @property
    def enabled(self) -> bool:
        return not self.no_llm and bool(os.environ.get(KEY_ENV[self.provider]))

    def complete(self, prompt: str, system: str = "", purpose: str = "") -> str:
        if self.no_llm:
            raise LLMDisabled("--no-llm")
        req = {
            "provider": self.provider,
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "max_tokens": self.max_tokens,
        }
        phash = sha256_text(canonical_json(req))
        cached = self.cache_dir / f"{phash}.json"
        if cached.is_file():
            hit = json.loads(cached.read_text("utf-8"))
            self._log(purpose, phash, hit["tokens_in"], hit["tokens_out"], cached=True)
            return hit["text"]
        key = os.environ.get(KEY_ENV[self.provider])
        if not key:
            raise LLMDisabled(f"${KEY_ENV[self.provider]} is not set")
        text, t_in, t_out = self._call(key, system, prompt)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        hit = {"text": text, "tokens_in": t_in, "tokens_out": t_out, "model": self.model}
        cached.write_text(json.dumps(hit, ensure_ascii=False), "utf-8")
        self._log(purpose, phash, t_in, t_out, cached=False)
        return text

    def complete_json(self, prompt: str, system: str = "", purpose: str = "") -> Any:
        return parse_json(self.complete(prompt, system, purpose))

    def _call(self, key: str, system: str, prompt: str) -> tuple[str, int, int]:
        client = self.client or httpx.Client(timeout=180)
        if self.provider == "anthropic":
            url = ANTHROPIC_URL
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
            url = OPENAI_URL
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
        for attempt in range(self.retries + 1):
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code not in (429, 500, 502, 503, 504, 529) or attempt == self.retries:
                break
            time.sleep(float(resp.headers.get("retry-after", 2**attempt)))
        if resp.status_code != 200:
            raise LLMError(f"{self.provider} HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if self.provider == "anthropic":
            text = "".join(b.get("text", "") for b in data.get("content", []))
            usage = data.get("usage", {})
            return text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        usage = data.get("usage", {})
        text = data["choices"][0]["message"]["content"] or ""
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))

    def _log(self, purpose: str, phash: str, t_in: int, t_out: int, cached: bool) -> None:
        cost = 0.0 if cached else cost_usd(self.model or "", t_in, t_out)
        self.calls += 0 if cached else 1
        self.cost += cost or 0.0
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "purpose": purpose,
            "prompt_hash": phash,
            "provider": self.provider,
            "model": self.model,
            "tokens_in": t_in,
            "tokens_out": t_out,
            "cost_usd": cost,
            "cached": cached,
        }
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "llm_log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
