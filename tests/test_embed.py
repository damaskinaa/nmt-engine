import json

import httpx
import numpy as np
import pytest

from nmt_engine.embed import Embedder
from nmt_engine.llm import LLMDisabled


def fake(calls, fail_first=0):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) <= fail_first:
            return httpx.Response(429, headers={"retry-after": "2"})
        texts = json.loads(request.content)["input"]
        rows = [{"index": i, "embedding": [len(t), 1.0, 0.0]} for i, t in enumerate(texts)]
        return httpx.Response(200, json={"data": rows[::-1], "usage": {"prompt_tokens": 10}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def embedder(tmp_path, client, url="https://api.tensorx.ai/v1"):
    return Embedder(
        tmp_path / "run",
        base_url=url,
        cache_dir=tmp_path / "cache",
        client=client,
        sleep=waits.append,
    )


waits: list[float] = []


def test_embed_caches_normalises_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("TENSORX_API_KEY", "sk-test-secret")
    calls: list = []
    with embedder(tmp_path, fake(calls)) as e:
        v = e.embed(["ab", "abcd", "ab"])
        assert v.shape == (3, 3) and np.allclose(np.linalg.norm(v, axis=1), 1.0)
        assert np.allclose(v[0], v[2]) and not np.allclose(v[0], v[1])
        assert len(calls) == 1 and json.loads(calls[0].content)["input"] == ["ab", "abcd"]
        assert calls[0].headers["authorization"] == "Bearer sk-test-secret"
        e.embed(["abcd", "ab"])
        assert len(calls) == 1  # all cached
    log = (tmp_path / "run" / "llm_log.jsonl").read_text()
    assert "sk-test-secret" not in log
    entry = json.loads(log)
    assert entry["host"] == "api.tensorx.ai" and entry["tokens_in"] == 10
    assert entry["cost_usd"] == pytest.approx(10 * 0.02 / 1e6)
    assert e.client is None  # closed on exit


def test_embed_cache_is_per_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("TENSORX_API_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    calls: list = []
    embedder(tmp_path, fake(calls)).embed(["x"])
    embedder(tmp_path, fake(calls), "https://api.openai.com/v1").embed(["x"])
    assert len(calls) == 2


def test_embed_retries_on_429_with_retry_after(tmp_path, monkeypatch):
    monkeypatch.setenv("TENSORX_API_KEY", "k")
    waits.clear()
    calls: list = []
    embedder(tmp_path, fake(calls, fail_first=2)).embed(["x"])
    assert len(calls) == 3 and waits[:2] == [2.0, 2.0]


def test_embed_needs_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TENSORX_API_KEY", raising=False)
    with pytest.raises(LLMDisabled):
        embedder(tmp_path, fake([])).embed(["x"])
