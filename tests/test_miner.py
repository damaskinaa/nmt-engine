"""PR 4: Job-Graph Miner, graph scoring, viewer, kill line. A scripted fake LLM stands in for
the model; nothing here touches the network."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest

from nmt_engine.collect.base import Collector
from nmt_engine.gates import GateConfig, run_gates
from nmt_engine.graph import score
from nmt_engine.llm import LLM, LLMDisabled, LLMError
from nmt_engine.miner.graph_build import criteria_similarity, search_queries, wilson
from nmt_engine.miner.killline import killline
from nmt_engine.miner.pipeline import mine
from nmt_engine.schema import Edge, EdgeCosts
from nmt_engine.store import load_run
from nmt_engine.util import normalize_ws

POSTS = [
    (
        "review",
        "ann",
        "I run a small design studio. Every month I need to send invoices to clients. First I "
        "export hours from my timer, then I send invoices to clients from FreshBooks. It is so "
        "frustrating when the PDF layout breaks. I just want to get paid faster. I ended up "
        "keeping a spreadsheet as a workaround.",
    ),
    (
        "forum",
        "bob",
        "As a freelancer, at the end of every month I have to send invoices to clients. I "
        "switched from Excel to Invoice Ninja because speed matters most to me. Annoying that "
        "payment reminders fail silently. The point is to get paid faster.",
    ),
    (
        "qa",
        "cat",
        "Running a two-person agency, when a project ends I must send invoices to clients. I "
        "tried FreshBooks but it was slow, speed matters to me. I hate chasing late payments. "
        "I want to get paid faster. Loved that recurring invoices just worked.",
    ),
    (
        "forum",
        "dan",
        "Unrelated: what keyboard do you use for coding? Mine is fine, thanks for asking all.",
    ),
]
ALTS = ("FreshBooks", "Invoice Ninja", "Excel", "spreadsheet")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _find(text: str, *words: str) -> list[str]:
    return [s for s in _sentences(text) if any(w.lower() in s.lower() for w in words)][:1]


class FakeLLM(LLM):
    """Deterministic stand-in: proposes spans by keyword from each post, plus one invented
    span per job that the verbatim check must reject."""

    def complete(self, prompt: str, system: str = "", purpose: str = "", json_mode=False) -> str:
        if self.no_llm:
            raise LLMDisabled("--no-llm")
        self.calls += 1
        if purpose == "miner.merge":
            return json.dumps({"groups": []})
        posts = re.findall(r'<post i="(\d+)" kind="\w+">\n(.*?)\n</post>', prompt, re.S)
        out = []
        for i, text in posts:
            jobs = []
            if "send invoices to clients" in text:
                jobs.append(
                    {
                        "statement": "I want to send invoices to clients",
                        "level": "core",
                        "type": "regular",
                        "order": 2 if "First I" in text else None,
                        "search_query": "send invoices to clients",
                        "context": _sentences(text)[:1] + ["this sentence is invented"],
                        "trigger": _find(text, "every month", "project ends"),
                        "job": ["send invoices to clients"],
                        "negative_emotions": _find(text, "frustrating", "Annoying", "hate"),
                        "positive_emotions": _find(text, "Loved"),
                        "higher_goal": ["get paid faster"],
                        "problem": _find(text, "breaks", "fail", "slow"),
                        "aha": _find(text, "just worked"),
                        "workaround": _find(text, "workaround"),
                        "success_criteria": [
                            {"label": "speed", "span": s} for s in _find(text, "speed", "faster")
                        ],
                        "alternatives": [{"name": a, "span": a} for a in ALTS if a in text],
                    }
                )
            if "export hours" in text:
                jobs.append(
                    {
                        "statement": "I want to export hours from my timer",
                        "level": "small",
                        "type": "regular",
                        "order": 1,
                        "search_query": None,
                        "job": ["export hours from my timer"],
                        "success_criteria": [],
                        "alternatives": [],
                    }
                )
            out.append({"i": int(i), "context_type": "review", "jobs": jobs})
        return json.dumps({"posts": out})


def make_run(tmp_path: Path) -> Path:
    c = Collector(tmp_path / "run", as_of=date(2026, 11, 7), min_interval_s=0, salt="t")
    for n, (kind, author, text) in enumerate(POSTS):
        c.add_source(
            adapter="test",
            kind=kind,
            platform="test",
            url=f"https://example.org/{n}",
            text=text,
            access_basis="public_api_terms_ok",
            terms_url="https://example.org/terms",
            author=author,
        )
    return c.run_dir


@pytest.fixture
def mined(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    run_dir = make_run(tmp_path)
    llm = FakeLLM(run_dir, cache_dir=tmp_path / "llmcache")
    summary = mine(run_dir, "invoicing", llm, cfg=GateConfig(forbidden_corpus=None))
    return run_dir, summary


def test_mine_end_to_end(mined):
    run_dir, s = mined
    assert s["status"] == "ok"
    assert s["traces"] == 4 and s["instances"] == 4
    assert s["spans_rejected"] >= 3  # the invented context span, once per post
    run = load_run(run_dir)
    jobs = {j.statement: j for j in run.jobs.values()}
    inv = jobs["I want to send invoices to clients"]
    assert not inv.thin and set(inv.consideration_set) >= {"FreshBooks", "Invoice Ninja"}
    assert s["jobs"] == 2 and s["jobs_passing"] == 1 and s["share_passing"] == 0.5
    assert s["thin_jobs"] == 1
    # sequence edge from the narrated order, product-layer edges from the consideration set
    kinds = {(e.kind, e.layer) for e in run.edges.values()}
    assert ("sequence", "customer") in kinds and ("performs", "product") in kinds
    for name in ("graph.html", "report.html"):
        assert (run_dir / "reports" / name).is_file()
    assert (run_dir / "run_manifest.json").is_file()


def test_every_receipt_is_verbatim(mined):
    run_dir, _ = mined
    run = load_run(run_dir)
    for c in run.claims.values():
        if c.status != "PUBLIC_VOICE" or c.retracted:
            continue
        for r in c.source_refs:
            text = normalize_ws(run.source_text(run.sources[r.source_id]))
            assert normalize_ws(r.verbatim) in text
    assert "this sentence is invented" not in (run_dir / "reports" / "report.html").read_text()


def test_outputs_pass_gates(mined):
    run_dir, s = mined
    report = run_gates(run_dir, GateConfig(forbidden_corpus=None))
    assert report.passed, report.to_markdown()
    assert s["gates_passed"]


def test_graph_html_is_self_contained(mined):
    run_dir, _ = mined
    html = (run_dir / "reports" / "graph.html").read_text()
    assert "Cytoscape.js 3.30.2" in html and "cytoscape" in html
    assert not re.search(r"<script[^>]+src=", html) and "<link" not in html
    data = json.loads((run_dir / "graph.json").read_text())
    assert data["status"] == "DERIVED" and data["nodes"]


def test_mine_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    outs = []
    for k in ("a", "b"):
        run_dir = make_run(tmp_path / k)
        mine(run_dir, "invoicing", FakeLLM(run_dir, cache_dir=tmp_path / k / "c"))
        outs.append(
            [
                (run_dir / f).read_text()
                for f in ("graph.json", "extraction.json", "reports/report.html")
            ]
        )
    assert outs[0] == outs[1]


def test_no_llm_skips(tmp_path):
    run_dir = make_run(tmp_path)
    s = mine(run_dir, "invoicing", LLM(run_dir, no_llm=True, cache_dir=tmp_path / "c"))
    assert s["status"] == "skipped" and not (run_dir / "reports" / "graph.html").exists()


def test_sources_failing_gates_are_dropped_before_mining(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    run_dir = make_run(tmp_path)
    run = load_run(run_dir)
    bad = sorted(run.sources.values(), key=lambda x: x.id)[0]
    text = run_dir / bad.text_path
    text.write_text(text.read_text("utf-8") + " tampered", "utf-8")  # gate 7: sha mismatch
    s = mine(run_dir, "invoicing", FakeLLM(run_dir, cache_dir=tmp_path / "c"))
    assert s["traces"] == len(POSTS) - 1
    run = load_run(run_dir)
    assert bad.id not in run.sources
    assert all(r.source_id != bad.id for c in run.claims.values() for r in c.source_refs)


class InvoicesOnlyLLM(FakeLLM):
    def complete(self, prompt: str, system: str = "", purpose: str = "", json_mode=False) -> str:
        out = json.loads(super().complete(prompt, system, purpose))
        for p in out.get("posts", []):
            p["jobs"] = [j for j in p["jobs"] if "invoices" in j["statement"]]
        return json.dumps(out)


def test_rerun_replaces_previous_mine(mined, tmp_path):
    run_dir, first = mined
    from nmt_engine.schema import Job
    from nmt_engine.store import Store

    Store(run_dir / "store").append(
        Job(id="job_manual", statement="I want a manual job", level="core")
    )
    before = load_run(run_dir)
    cfg = GateConfig(forbidden_corpus=None)
    s = mine(run_dir, "invoicing", InvoicesOnlyLLM(run_dir, cache_dir=tmp_path / "c2"), cfg=cfg)
    run = load_run(run_dir)
    assert "job_manual" in run.jobs  # not written by mine, so never retracted by it
    mined_jobs = set(run.jobs) - {"job_manual"}
    assert s["status"] == "ok" and s["jobs"] == len(mined_jobs) == 1 < first["jobs"]
    assert mined_jobs < set(before.jobs)
    assert all(e.to_job in run.jobs for e in run.edges.values())
    assert all(e.from_job in run.jobs or e.kind == "performs" for e in run.edges.values())
    jids = {j.removeprefix("job_") for j in mined_jobs}
    assert all(c.split("_")[2] in jids for c in run.claims if c.startswith("c_job_"))
    # a full mine again brings the dropped job back as a newer revision
    again = mine(run_dir, "invoicing", FakeLLM(run_dir, cache_dir=tmp_path / "c3"), cfg=cfg)
    assert again["jobs"] == first["jobs"] and again["share_passing"] == first["share_passing"]


class BrokenLLM(LLM):
    def complete(self, prompt: str, system: str = "", purpose: str = "", json_mode=False) -> str:
        from nmt_engine.llm import LLMError

        raise LLMError("HTTP 500")


def test_failed_extraction_is_not_a_kill_line_result(tmp_path):
    run_dir = make_run(tmp_path)
    s = mine(run_dir, "invoicing", BrokenLLM(run_dir, cache_dir=tmp_path / "c"))
    assert s["status"] == "failed" and s["failed_batches"] == 1
    _, verdict = killline([run_dir, run_dir, run_dir])
    assert "not decidable" in verdict


# --- scoring -----------------------------------------------------------------------------


def _edge(i, a, b, p=None, costs=None, layer="customer", kind="sequence"):
    return Edge(id=i, from_job=a, to_job=b, kind=kind, layer=layer, p_success=p, costs=costs)


def test_route_value_interval_arithmetic():
    e1 = _edge("e1", "a", "b", (0.5, 0.8), EdgeCosts(time=(0.1, 0.2)))
    e2 = _edge("e2", "b", "c", (0.5, 1.0), EdgeCosts(negative_emotion=(0.0, 0.1)))
    lo, hi = score.route_value([e1, e2], outcome=(10.0, 20.0))
    assert (lo, hi) == pytest.approx((0.25 * 10 - 0.3, 0.8 * 20 - 0.1))
    assert score.route_value([]) == (1.0, 1.0)


def test_added_value_uses_best_alternative():
    assert score.added_value((5, 6), [(1, 2), (3, 4)]) == (1, 3)
    assert score.added_value((5, 6), []) == (5, 6)


def test_importance_weighted_and_deterministic():
    edges = [_edge("e1", "a", "b"), _edge("e2", "c", "b"), _edge("e3", "b", "d")]
    freq = {"a": 1, "b": 10, "c": 1, "d": 1}
    r1 = score.importance("abcd", edges, freq, {})
    r2 = score.importance("dcba", list(reversed(edges)), freq, {})
    assert r1 == r2 and max(r1, key=r1.get) == "b"
    assert sum(r1.values()) == pytest.approx(1.0)


def test_critical_breaks_and_layers():
    edges = [
        _edge("e1", "a", "b", (0.1, 0.4)),
        _edge("e2", "b", "c", (0.3, 0.7)),
        _edge("e3", "s", "c", (0.6, 0.9), layer="product", kind="performs"),
    ]
    breaks = score.critical_breaks(edges)
    assert [(b.edge_id, b.certain) for b in breaks] == [("e1", True), ("e2", False)]
    views = score.layer_views(edges)
    assert views["product"] == {"edges": ["e3"], "nodes": ["c", "s"]}
    assert views["business"] == {"edges": [], "nodes": []}


def test_wilson_and_criteria_similarity():
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0 < hi < 0.3
    assert wilson(0, 0) == (0.0, 1.0)
    assert criteria_similarity(["speed", "price"], ["speed", "price"]) == 1.0
    assert criteria_similarity(["speed", "price"], ["price", "speed"]) == 0.5
    assert criteria_similarity([], ["x"]) is None


def test_search_queries_parses_dataforseo_payloads():
    auto = json.dumps([{"items": [{"suggestion": "invoice app"}, {"suggestion": "invoice pdf"}]}])
    serp = json.dumps({"paa": ["how to invoice?"], "related": ["free invoice"]})
    assert search_queries(auto) == ["invoice app", "invoice pdf"]
    assert search_queries(serp) == ["how to invoice?", "free invoice"]
    assert search_queries("not json") == []


def test_killline_table(tmp_path):
    def run(name, share):
        d = tmp_path / name
        d.mkdir()
        s = {
            "status": "ok",
            "category": name,
            "traces": 500,
            "jobs": 10,
            "cost_usd": 1.0,
            "jobs_passing": int(share * 10),
            "share_passing": share,
            "runtime_s": 60,
            "thin_jobs": 3,
        }
        (d / "mine_summary.json").write_text(json.dumps(s))
        return d

    table, verdict = killline([run("a", 0.2), run("b", 0.1), run("c", 0.5)])
    assert "| a | 500 | 10 | 3 | 2 | 20.0% |" in table and verdict.startswith("KILL LINE HIT")
    _, verdict = killline([run("d", 0.4), run("e", 0.1), run("f", 0.5)])
    assert verdict.startswith("Kill line passed")
    _, verdict = killline([tmp_path / "missing"])
    assert "not decidable" in verdict


# --- LLM client ----------------------------------------------------------------------------


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


def test_graph_json_cannot_break_out_of_script(tmp_path: Path) -> None:
    from nmt_engine.graph.viewer import _script_json, write_graph_html

    evil = "</SCRIPT><script>alert(1)</script><!--<script>"
    assert "<" not in _script_json({"label": evil})
    assert "\u2028" not in _script_json({"q": "a\u2028b\u2029c"})
    assert json.loads(_script_json({"q": "a\u2028b"}))["q"] == "a\u2028b"
    assert json.loads(_script_json({"label": evil}))["label"] == evil
    html = write_graph_html(
        {"nodes": [{"data": {"id": "j", "label": evil}}], "edges": []}, tmp_path / "g.html"
    ).read_text()
    assert "alert(1)</script>" not in html and "<!--<script>" not in html


def test_receipt_cap_keeps_every_source_kind() -> None:
    from types import SimpleNamespace

    from nmt_engine.miner.jobs import MAX_REFS, _refs

    sources = {f"r{i}": SimpleNamespace(kind="review") for i in range(60)}
    sources["f0"] = SimpleNamespace(kind="forum")
    pairs = [(f"r{i}", f"span {i}") for i in range(60)] + [("f0", "forum span")]
    refs = _refs(pairs, "job", sources)
    assert len(refs) == MAX_REFS
    assert {sources[r.source_id].kind for r in refs} == {"review", "forum"}


def test_search_proxies_fall_back_without_full_credentials(tmp_path: Path, monkeypatch) -> None:
    from nmt_engine.collect import dataforseo
    from nmt_engine.miner.pipeline import search_proxies

    monkeypatch.setenv("NMT_AUTHOR_SALT", "s")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "login")
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    assert search_proxies(tmp_path, [], "IE") == []

    monkeypatch.setenv("DATAFORSEO_PASSWORD", "pw")

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(dataforseo, "search_volume", boom)
    with pytest.warns(UserWarning, match="search proxies skipped"):
        assert search_proxies(tmp_path, [], "IE") == []


def test_graph_payload_skips_performs_edges_without_solution(mined):
    from nmt_engine.miner.pipeline import graph_payload

    run_dir, _ = mined
    run = load_run(run_dir)
    shown = {c for e in run.edges.values() for c in e.claim_ids}
    g = graph_payload(run, shown, {}, {}, solutions={})
    assert g["consideration_sets"] == {}


def test_higher_job_links_cannot_cycle():
    from types import SimpleNamespace

    from nmt_engine.miner.graph_build import _reaches

    def bj(higher=None):
        return SimpleNamespace(job=SimpleNamespace(higher_job_id=higher))

    by_id = {"a": bj("b"), "b": bj("c"), "c": bj()}
    assert _reaches("b", "a", by_id) is False  # b -> c never returns to a
    assert _reaches("a", "c", by_id) is True  # so c.higher = a would close a cycle
