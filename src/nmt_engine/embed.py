"""Text embeddings over an OpenAI-compatible `/embeddings` endpoint (TensorX by default).

Vectors are cached per (endpoint host, model, text hash) as float32 `.npy`, so reruns are free
and identical.
Every request is logged to runs/<id>/llm_log.jsonl with tokens and cost, like `LLM` calls.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np

from nmt_engine.config import repo_root
from nmt_engine.llm import HOST_KEY_ENV, RETRY_STATUS, LLMDisabled, LLMError, backoff
from nmt_engine.util import sha256_text

EMBED_MODEL = "qwen/qwen3-embedding-8b"
# USD per million input tokens (tensorx.ai/models).
EMBED_PRICES = {"qwen/qwen3-embedding-8b": 0.02}


@dataclass
class Embedder:
    run_dir: Path
    model: str = field(default_factory=lambda: os.environ.get("NMT_EMBED_MODEL", EMBED_MODEL))
    base_url: str = field(
        default_factory=lambda: os.environ.get("NMT_LLM_BASE_URL", "https://api.tensorx.ai/v1")
    )
    cache_dir: Path | None = None
    client: httpx.Client | None = None
    batch: int = 64
    retries: int = 6
    sleep: Callable[[float], None] = time.sleep
    tokens: int = 0
    cost: float = 0.0
    calls: int = 0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.run_dir = Path(self.run_dir)
        root = Path(self.cache_dir or repo_root() / "cache" / "embed")
        host = httpx.URL(self.base_url).host or "local"
        self.cache_dir = root / host / self.model.replace("/", "__")

    @property
    def key_env(self) -> str:
        host = httpx.URL(self.base_url).host
        return HOST_KEY_ENV.get(host, "OPENAI_API_KEY")

    def _path(self, text: str) -> Path:
        return self.cache_dir / f"{sha256_text(text)}.npy"

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

    def __enter__(self) -> Embedder:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def embed(self, texts: list[str], purpose: str = "embed") -> np.ndarray:
        """Unit-normalised vectors, one row per text, in order."""
        todo = sorted({t for t in texts if not self._path(t).is_file()})
        for i in range(0, len(todo), self.batch):
            self._fetch(todo[i : i + self.batch], purpose)
        out = np.stack([np.load(self._path(t)) for t in texts]) if texts else np.zeros((0, 0))
        norms = np.linalg.norm(out, axis=1, keepdims=True) if texts else 1.0
        return out / np.where(norms == 0, 1.0, norms)

    def _fetch(self, texts: list[str], purpose: str) -> None:
        key = os.environ.get(self.key_env)
        if not key:
            raise LLMDisabled(f"${self.key_env} is not set")
        if self.client is None:
            self.client = httpx.Client(timeout=180)
        body = {"model": self.model, "input": texts}
        headers = {"Authorization": f"Bearer {key}"}
        for attempt in range(self.retries + 1):
            resp = self.client.post(self.base_url + "/embeddings", headers=headers, json=body)
            if resp.status_code not in RETRY_STATUS or attempt == self.retries:
                break
            self.sleep(backoff(attempt, resp.headers.get("retry-after")))
        if resp.status_code != 200:
            raise LLMError(f"embeddings HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        rows = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        if len(rows) != len(texts):
            raise LLMError(f"embeddings returned {len(rows)} rows for {len(texts)} texts")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for text, row in zip(texts, rows, strict=True):
            np.save(self._path(text), np.asarray(row["embedding"], dtype=np.float32))
        tokens = int(data.get("usage", {}).get("prompt_tokens") or 0)
        price = EMBED_PRICES.get(self.model)
        cost = None if price is None else round(tokens * price / 1e6, 8)
        self.tokens += tokens
        self.cost += cost or 0.0
        self.calls += 1
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "purpose": purpose,
            "host": httpx.URL(self.base_url).host,
            "model": self.model,
            "texts": len(texts),
            "tokens_in": tokens,
            "tokens_out": 0,
            "cost_usd": cost,
            "cached": False,
        }
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "llm_log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
