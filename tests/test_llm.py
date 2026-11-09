"""TensorX/OpenAI-compatible LLM client: cache, log, retries, budgets (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from nmt_engine.llm import LLM, LLMDisabled, LLMError


def _anthropic(handler_log):
    def handler(req):
        handler_log.append(req)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "usage": {"input_tokens": 1000, "output_tokens": 200},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_llm_logs_caches_and_never_logs_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret")
    seen = []
    llm = LLM(
        tmp_path / "run",
        provider="anthropic",
        model="claude-haiku-4-5",
        cache_dir=tmp_path / "c",
        client=_anthropic(seen),
    )
    assert llm.complete_json("hello", "sys", purpose="t") == {"ok": True}
    assert llm.complete_json("hello", "sys", purpose="t") == {"ok": True}
    assert len(seen) == 1 and seen[0].headers["x-api-key"] == "sk-test-secret"
    log_text = (tmp_path / "run" / "llm_log.jsonl").read_text()
    assert "sk-test-secret" not in log_text
    first, second = [json.loads(x) for x in log_text.splitlines()]
    assert first["cost_usd"] == pytest.approx(0.002) and not first["cached"]
    assert second["cached"] and second["prompt_hash"] == first["prompt_hash"]
    assert llm.calls == 1
    llm.complete("another prompt")
    assert len(seen) == 2 and llm.client is not None  # one client reused across calls


def test_unpriced_model_calls_are_counted(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("NMT_LLM_PRICES", raising=False)
    llm = LLM(
        tmp_path / "run",
        provider="anthropic",
        model="some-new-model",
        cache_dir=tmp_path / "c",
        client=_anthropic([]),
    )
    llm.complete("x")
    assert llm.cost == 0.0 and llm.unpriced_calls == 1


def test_llm_disabled_without_key_or_with_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMDisabled):
        LLM(tmp_path, cache_dir=tmp_path / "c").complete("x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    with pytest.raises(LLMDisabled):
        LLM(tmp_path, no_llm=True, cache_dir=tmp_path / "c").complete("x")


def _openai(log, responses=None):
    queue = list(responses or [])

    def handler(req):
        log.append(req)
        if queue:
            return queue.pop(0)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_blank_max_tokens_env_uses_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NMT_LLM_MAX_TOKENS", "")
    assert LLM(tmp_path, no_llm=True, cache_dir=tmp_path / "c").max_tokens == 4096


def test_reasoning_effort_is_sent_and_keys_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TENSORX_API_KEY", "tx")
    seen: list = []
    kw = dict(provider="openai", model="z-ai/glm-5.3", base_url="https://api.tensorx.ai/v1")
    c = _openai(seen)
    LLM(tmp_path, cache_dir=tmp_path / "c", client=c, **kw).complete("p")
    monkeypatch.setenv("NMT_LLM_REASONING_EFFORT", "none")
    LLM(tmp_path, cache_dir=tmp_path / "c", client=c, **kw).complete("p")
    bodies = [json.loads(r.content) for r in seen]
    assert "reasoning_effort" not in bodies[0] and bodies[1]["reasoning_effort"] == "none"


def test_malformed_json_is_billed_but_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("TENSORX_API_KEY", "tx")
    bad = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"posts": [}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )
    seen: list = []
    llm = LLM(
        tmp_path / "run",
        provider="openai",
        model="z-ai/glm-5.3",
        base_url="https://api.tensorx.ai/v1",
        cache_dir=tmp_path / "c",
        client=_openai(seen, [bad]),
    )
    with pytest.raises(LLMError):
        llm.complete_json("p")
    assert llm.calls == 1 and not list((tmp_path / "c").glob("*.json"))
    assert llm.complete_json("p") == {"ok": True} and len(seen) == 2


def test_truncated_answer_is_billed_but_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("TENSORX_API_KEY", "tx")
    monkeypatch.setenv("NMT_LLM_MAX_TOKENS", "512")
    cut = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"jobs": ['}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 512},
        },
    )
    seen: list = []
    llm = LLM(
        tmp_path / "run",
        provider="openai",
        model="z-ai/glm-5.3",
        base_url="https://api.tensorx.ai/v1",
        cache_dir=tmp_path / "c",
        client=_openai(seen, [cut]),
    )
    with pytest.raises(LLMError, match="max_tokens=512"):
        llm.complete("p")
    assert json.loads(seen[0].content)["max_completion_tokens"] == 512
    assert llm.calls == 1 and llm.cost > 0
    assert json.loads((tmp_path / "run" / "llm_log.jsonl").read_text())["truncated"] is True
    assert llm.complete("p") == '{"ok": true}'  # retried, not replayed from cache
    assert len(seen) == 2


def test_tensorx_base_url_key_json_mode_and_log(tmp_path, monkeypatch):
    for k in ("OPENAI_API_KEY", "NMT_LLM_PRICES", "NMT_LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TENSORX_API_KEY", "tx-secret")
    monkeypatch.setenv("NMT_LLM_BASE_URL", "https://api.tensorx.ai/v1/")
    seen: list = []
    llm = LLM(
        tmp_path / "run",
        provider="openai",
        model="z-ai/glm-5.3",
        cache_dir=tmp_path / "c",
        client=_openai(seen),
    )
    assert llm.enabled and llm.key_env == "TENSORX_API_KEY"
    assert llm.complete_json("hi", "sys", purpose="t") == {"ok": True}
    req = seen[0]
    assert str(req.url) == "https://api.tensorx.ai/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer tx-secret"
    body = json.loads(req.content)
    assert body["response_format"] == {"type": "json_object"} and body["temperature"] == 0
    assert "seed" not in body and body["max_completion_tokens"] == llm.max_tokens
    log_text = (tmp_path / "run" / "llm_log.jsonl").read_text()
    assert "tx-secret" not in log_text
    entry = json.loads(log_text)
    assert entry["host"] == "api.tensorx.ai" and entry["model"] == "z-ai/glm-5.3"
    assert entry["cost_usd"] == pytest.approx((1000 * 1.75 + 200 * 4.50) / 1e6)
    llm.complete("hi", "sys")  # plain completion: different request, so not served from cache
    assert len(seen) == 2 and "response_format" not in json.loads(seen[1].content)


def test_cache_is_per_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("TENSORX_API_KEY", "tx")
    seen: list = []
    for base in ("https://api.tensorx.ai/v1", "https://api.tensorx.ai/v2"):
        llm = LLM(
            tmp_path / "run",
            provider="openai",
            model="z-ai/glm-5.3",
            base_url=base,
            cache_dir=tmp_path / "c",
            client=_openai(seen),
        )
        llm.complete("same prompt")
    assert [r.url.path for r in seen] == ["/v1/chat/completions", "/v2/chat/completions"]


def test_default_openai_host_still_uses_openai_key(tmp_path, monkeypatch):
    monkeypatch.delenv("NMT_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("TENSORX_API_KEY", "tx")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = LLM(tmp_path, provider="openai", cache_dir=tmp_path / "c")
    assert llm.host == "api.openai.com" and llm.key_env == "OPENAI_API_KEY" and not llm.enabled


def test_retry_honours_retry_after_else_backs_off(tmp_path, monkeypatch):
    from nmt_engine.llm import backoff

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    waits: list[float] = []
    seen: list = []
    busy = [
        httpx.Response(429, headers={"retry-after": "7"}),
        httpx.Response(503),
        httpx.Response(500),
    ]
    llm = LLM(
        tmp_path,
        provider="openai",
        model="gpt-4o-mini",
        cache_dir=tmp_path / "c",
        client=_openai(seen, busy),
        sleep=waits.append,
    )
    assert llm.complete_json("x") == {"ok": True} and len(seen) == 4
    assert waits[0] == 7.0
    assert 8.0 <= waits[1] <= 12.0 and 16.0 <= waits[2] <= 24.0
    assert all(48.0 <= backoff(a, None) <= 60.0 for a in range(4, 10))
    assert backoff(0, "soon") <= 6.0  # unparsable retry-after falls back


def test_transport_errors_are_retried_then_raise_llm_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    def make(h, sub):
        return LLM(
            tmp_path,
            provider="openai",
            model="gpt-4o-mini",
            cache_dir=tmp_path / sub,
            client=httpx.Client(transport=httpx.MockTransport(h)),
            sleep=lambda s: None,
            retries=2,
        )

    assert make(handler, "a").complete_json("x") == {"ok": True} and len(calls) == 2

    def down(req):
        raise httpx.ConnectError("down", request=req)

    with pytest.raises(LLMError, match="ConnectError"):
        make(down, "b").complete_json("x")


def test_auditor_is_always_another_vendor(monkeypatch):
    from nmt_engine.llm import auditor_model, model_family

    monkeypatch.delenv("NMT_LLM_AUDITOR_MODEL", raising=False)
    assert model_family("z-ai/glm-5.3-flash") == model_family("z-ai/glm-5.3") == "z-ai"
    assert model_family("claude-haiku-4-5") == "anthropic"
    assert auditor_model("z-ai/glm-5.3") == "moonshotai/kimi-k3.1-pro"
    assert auditor_model("deepseek/deepseek-v4.1-flash") == "z-ai/glm-5.3"
    assert auditor_model("z-ai/glm-5.3", "qwen/qwen3.8-2.4t-a95b") == "qwen/qwen3.8-2.4t-a95b"
    with pytest.raises(ValueError):
        auditor_model("z-ai/glm-5.3", "z-ai/glm-5.3-flash")
    monkeypatch.setenv("NMT_LLM_AUDITOR_MODEL", "z-ai/glm-5.3-flash")
    with pytest.raises(ValueError):
        auditor_model("z-ai/glm-5.3")
