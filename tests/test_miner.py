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
from nmt_engine.llm import LLM, LLMDisabled
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

    def complete(self, prompt: str, system: str = "", purpose: str = "") -> str:
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
        }
        (d / "mine_summary.json").write_text(json.dumps(s))
        return d

    table, verdict = killline([run("a", 0.2), run("b", 0.1), run("c", 0.5)])
    assert "| a | 500 | 10 | 2 | 20.0% |" in table and verdict.startswith("KILL LINE HIT")
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


def test_llm_disabled_without_key_or_with_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMDisabled):
        LLM(tmp_path, cache_dir=tmp_path / "c").complete("x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    with pytest.raises(LLMDisabled):
        LLM(tmp_path, no_llm=True, cache_dir=tmp_path / "c").complete("x")


def test_graph_json_cannot_break_out_of_script(tmp_path: Path) -> None:
    from nmt_engine.graph.viewer import _script_json, write_graph_html

    evil = "</SCRIPT><script>alert(1)</script><!--<script>"
    assert "<" not in _script_json({"label": evil})
    assert json.loads(_script_json({"label": evil}))["label"] == evil
    html = write_graph_html(
        {"nodes": [{"data": {"id": "j", "label": evil}}], "edges": []}, tmp_path / "g.html"
    ).read_text()
    assert "alert(1)</script>" not in html and "<!--<script>" not in html
