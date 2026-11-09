"""B3: L2 query planner, L3 node check, node gold growth, L4 node status and T2."""

from __future__ import annotations

import json

from nmt_engine import harvest, ledger
from nmt_engine.config import repo_root
from nmt_engine.verify import node, node_gold
from nmt_engine.verify.author import Post
from tests.test_verify_gold import Scripted

GRAPH, RISKY = node_gold.candidates()


def test_statements_cover_every_candidate_and_quote_the_graph():
    st = node.statements(GRAPH, RISKY)
    assert list(st) == RISKY
    by_id = {n.id: n for n in GRAPH.nodes}
    for nid, s in st.items():
        assert by_id[nid].text in s


def test_solution_names_and_template_queries():
    assert harvest.solution_names("Accounting suites such as QuickBooks or Xero") == [
        "QuickBooks",
        "Xero",
    ]
    qs = harvest.template_queries(GRAPH, RISKY)
    texts = {q.text for q in qs}
    assert {"alternative to Wave", "switched from Bonsai", "Wave too expensive"} <= texts
    assert all(set(q.nodes) <= set(RISKY) for q in qs)


def test_producer_queries_are_cleaned_and_merged(tmp_path):
    llm = Scripted(
        tmp_path,
        [
            {
                "queries": [
                    {"node": "J3", "searches": ["Track unpaid invoices", "x", "paid 30 days late"]},
                    {"node": "J4", "searches": ["track unpaid invoices"]},
                    {"node": "ZZ", "searches": ["ignored node here"]},
                ]
            }
        ],
    )
    qs = harvest.merge(harvest.producer_queries(llm, GRAPH, RISKY, node.statements(GRAPH, RISKY)))
    assert [(q.text, q.nodes) for q in qs] == [("track unpaid invoices", ("J3", "J4"))]


def test_committed_plan_hash_matches():
    path = repo_root() / "briefs" / "invoicing.l2.json"
    d = json.loads(path.read_text("utf-8"))
    assert harvest.HarvestPlan.from_dict(d).hash == d["hash"]
    assert d["riskiest"] == RISKY
    assert d["app_countries"] == ["us", "gb", "ie"] and d["since"] == "2023-01-01"


def test_node_check_needs_every_node_and_verbatim_quotes(tmp_path):
    st = {"J3": "s1", "C4": "s2"}
    post = Post("p", "invoicing", "I lost track of two unpaid invoices last year.")
    bad = {"id": 0, "answers": [{"node": "J3", "verdict": "supports", "quote": "I forgot"}]}
    good = {
        "id": 0,
        "answers": [
            {"node": "J3", "verdict": "supports", "quote": "lost track of two unpaid invoices"},
            {"node": "C4", "verdict": "unrelated", "quote": None},
        ],
    }
    llm = Scripted(tmp_path, [{"posts": [bad]}, {"posts": [good]}])
    [a] = node.node_check(llm, [post], st)
    assert a["J3"]["verdict"] == "supports" and a["C4"] == {"verdict": "unrelated", "quote": None}


def _rec(i, fam, verdict, author=None, role="USER", names=True):
    return {
        "source_id": f"S{i}",
        "url": f"u{i}",
        "family": fam,
        "author_hash": author or f"a{i}",
        "role": role,
        "names_solution": names,
        "nodes": {"J3": {"verdict": verdict, "quote": "q"}},
    }


def test_node_status_thresholds_families_and_authors():
    sup = [_rec(1, "discussion", "supports"), _rec(2, "qa", "supports")]
    [s] = ledger.node_status(sup + [_rec(3, "qa", "supports", author="a1")], ["J3"])
    assert s.status == "unknown"  # same author twice is one voice
    [s] = ledger.node_status(sup + [_rec(3, "qa", "supports")], ["J3"])
    assert s.status == "supported" and not s.contested
    one_family = [_rec(i, "discussion", "supports") for i in range(5)]
    assert ledger.node_status(one_family, ["J3"])[0].status == "unknown"
    context = [_rec(i, "vendor_page", "supports") for i in range(5)]
    assert ledger.node_status(sup + context, ["J3"])[0].status == "unknown"
    builders = [_rec(i, "review", "supports", role="BUILDER") for i in range(5, 9)]
    no_sol = [_rec(i, "review", "supports", names=False) for i in range(9, 12)]
    assert ledger.node_status(sup + builders + no_sol, ["J3"])[0].status == "unknown"
    sim = [{**_rec(i, "review", "supports"), "simulated": True} for i in range(12, 15)]
    assert ledger.node_status(sup + sim, ["J3"])[0].status == "unknown"


def test_both_sides_meeting_the_bar_is_contested_unknown():
    recs = [_rec(i, f, "supports") for i, f in enumerate(["discussion", "qa", "review"])]
    recs += [
        _rec(i, f, "contradicts")
        for i, f in zip(range(3, 6), ["discussion", "qa", "qa"], strict=True)
    ]
    [s] = ledger.node_status(recs, ["J3"])
    assert s.status == "unknown" and s.contested
    con = [r for r in recs if r["nodes"]["J3"]["verdict"] == "contradicts"]
    assert ledger.node_status(con, ["J3"])[0].status == "contradicted"


def test_t2_needs_five_decisive():
    mk = lambda st: ledger.NodeStatus("x", st)  # noqa: E731
    assert not ledger.t2([mk("supported")] * 4 + [mk("unknown")] * 6)["passed"]
    assert ledger.t2([mk("supported")] * 3 + [mk("contradicted")] * 2 + [mk("unknown")] * 5)[
        "passed"
    ]


def test_t1_reports_model_label_basis_and_t2_gate():
    res = node_gold.t1()
    assert res["basis"].startswith("precision against model labels")
    for k in node_gold.T1_GATING:
        assert k in res["classes"]
    gating = {k: res["classes"][k]["test"]["status"] for k in node_gold.T1_GATING}
    assert res["t2_may_run"] == all(v == "PASS" for v in gating.values())
    for c in res["classes"].values():
        if c["test"]["called"] < 20:
            assert c["test"]["status"] == "NOT MEASURED"


def test_harvest_skips_an_adapter_after_repeated_errors(tmp_path, monkeypatch):
    import httpx

    calls = []

    def boom(c, *a, **k):
        calls.append(a[0] if a else None)
        raise httpx.HTTPStatusError("quota", request=None, response=None)

    monkeypatch.setattr(harvest.hackernews, "collect", boom)
    monkeypatch.setattr(harvest.stackexchange, "collect", lambda *a, **k: [])
    monkeypatch.setattr(harvest.github, "issues", lambda *a, **k: [])
    monkeypatch.setattr(harvest.appstore, "named_app", lambda *a, **k: [])
    qs = [harvest.Query(f"q{i}", ("J2",), "template") for i in range(6)]
    p = harvest.HarvestPlan("h", RISKY, qs, apps=[])

    class FakeStore:
        def current(self, kind):
            return {}

    class FakeCollector:
        store = FakeStore()

    out = harvest.run(p, tmp_path, collector=FakeCollector())
    hn = {k: v["status"] for k, v in out["steps"].items() if k.startswith("hackernews:")}
    assert len(calls) == harvest.BREAKER
    assert list(hn.values()).count("skipped") == len(qs) - harvest.BREAKER


def test_canary_passed_and_never_counts_toward_t1():
    res = json.loads((node_gold.GOLD_DIR / "node_canary.json").read_text("utf-8"))
    assert res["ok"] and len(res["canaries"]) == 6
    exp = [c["expected"] for c in res["canaries"]]
    assert exp.count("supports") == exp.count("contradicts") == exp.count("unrelated") == 2
    ids = {r["id"] for r in node_gold._items(node_gold.GOLD_DIR).values()}
    assert not ids & {c["id"] for c in res["canaries"]}


def test_node_split_is_fixed_by_post_id():
    sids = [f"S-{i:016x}" for i in range(200)]
    splits = [node_gold.split_of(s) for s in sids]
    assert splits == [node_gold.split_of(s) for s in sids]
    assert 70 < splits.count("test") < 130


def test_ranks_and_designated_pairs(tmp_path, monkeypatch):
    run = tmp_path / "l2"
    run.mkdir()
    qs = [{"text": "late invoices", "nodes": ["J3"], "origin": "template"}]
    (run / "harvest_plan.json").write_text(json.dumps({"queries": qs}))
    hits = [
        {"source_id": "S-b", "ranks": {"hackernews:late invoices": 0}},
        {"source_id": "S-a", "ranks": {"stackexchange:money:late invoices": 3}},
        {"source_id": "S-c", "ranks": {"hackernews:other": 0}},
    ]
    (run / "harvest_hits.jsonl").write_text("".join(json.dumps(h) + "\n" for h in hits))

    class S:
        def __init__(self, i):
            self.id, self.retracted, self.customer_voice, self.platform = i, False, True, "hn"

    class Run:
        sources = {i: S(i) for i in ("S-a", "S-b", "S-c")}

    monkeypatch.setattr(node_gold, "load_run", lambda d: Run())
    monkeypatch.setattr(node_gold, "collector_on", lambda p, e: True)
    assert node_gold.ranks(run, ["J3", "J4"]) == {"J3": ["S-b", "S-a"], "J4": []}

    out = tmp_path / "gold"
    out.mkdir()
    items = [{"id": "N001", "split": "test", "amendment": 3, "pairs": {"J3": "top"}}]
    (out / "node_items.jsonl").write_text(json.dumps(items[0]) + "\n")
    g = {"id": "N001", "split": "test", "verdicts": {n: "unrelated" for n in RISKY}}
    g["verdicts"]["J3"] = "supports"
    (out / "node_gold.jsonl").write_text(json.dumps(g) + "\n")
    assert node_gold._designated(out) == [("N001", "J3", "test", "supports")]
    pn = node_gold.per_node(out)
    assert pn["J3"]["supports"] == 1 and "finding" not in pn["J3"]
    assert pn["J4"]["finding"] == "no public evidence in this harvest"


def test_stackexchange_keeps_earlier_pages_when_a_deep_page_is_refused():
    from datetime import date

    import httpx

    from nmt_engine.collect import stackexchange

    class C:
        def fetch_json(self, url, name, params):
            if params["page"] == 1:
                return {"items": [{"link": "u1", "title": "t", "body": "b"}], "has_more": True}
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError(
                "400", request=req, response=httpx.Response(400, request=req)
            )

        def add_source(self, **kw):
            return kw["url"]

    assert stackexchange.collect(C(), "q", date(2023, 1, 1), similar=True) == ["u1"]


def test_l2_collector_returns_already_stored_sources(tmp_path):
    from nmt_engine.collect.base import Collector

    c = Collector(tmp_path, salt="s")
    kw = dict(adapter="hn", kind="forum", platform="hn", url="https://x/1", text="hi")
    kw |= dict(access_basis="api", terms_url="https://x/terms")
    first = c.add_source(**kw)
    assert c.add_source(**kw) is None
    c.return_existing = True
    assert c.add_source(**kw).id == first.id
