"""B4: segment agents, switching world, SSR + its gold gate, cross-model stability."""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pytest

from nmt_engine.sim import agents as ag
from nmt_engine.sim import ssr, ssr_gold, stability, world
from nmt_engine.verify import node_gold


class HashEmb:
    """Deterministic bag-of-words vectors: shared words mean higher cosine."""

    def embed(self, texts, purpose="x"):
        out = []
        for t in texts:
            v = np.zeros(64)
            for w in t.lower().split():
                v[hash(w.strip(".,;")) % 64] += 1
            out.append(v / (np.linalg.norm(v) or 1))
        return np.array(out)


class EchoLLM:
    model = "fake/echo"

    def __init__(self):
        self.prompts = []

    def complete(self, prompt, system=None, purpose="", check=None, **kw):
        self.prompts.append(prompt)
        return "I am leaving my current tool and moving to the spreadsheet."


@pytest.fixture(scope="module")
def graph():
    return node_gold.candidates()[0]


def test_pmf_floor_and_normalisation():
    p = ssr.pmf({"a": 0.2, "b": 0.5, "c": 0.8})
    assert sum(p.values()) == pytest.approx(1)
    assert p["a"] == pytest.approx(0.01 / (0.01 + 0.31 + 0.61))


def test_probs_not_inflated_by_offer_count():
    """Amendment 5: many weak switch outcomes do not outvote one strong stay."""
    sims = {"stay": 0.8, "consider": 0.5} | {f"switch:{i}": 0.6 for i in range(9)}
    p = ssr.probs(sims)
    assert sum(p.values()) == pytest.approx(1)
    assert ssr.top_class(p) == "stay"
    assert ssr.collapse(ssr.pmf(sims))["switch"] > p["stay"]  # the amendment-4 sum would not


def test_ssr_picks_matching_anchor():
    s = ssr.SSR(HashEmb())
    p = s.score(
        ["I will carry on with Wave exactly as I do now."],
        [["Xero", "a spreadsheet"]],
        ["Wave"],
        "t",
    )[0]
    assert ssr.top_class(p) == "stay"
    assert set(p) == {"stay", "consider", "switch:Xero", "switch:a spreadsheet"}


def test_incumbents_overlap_core_jobs(graph):
    segs = {n.id: n for n in graph.nodes if n.type == "segment"}
    for s in segs.values():
        a = ag.Agent(s.id, s.text, [], [], set(s.core_jobs))
        for sid in ag.incumbents(graph, a):
            sol = next(n for n in graph.nodes if n.id == sid)
            assert set(sol.serves) & set(s.core_jobs)


def test_agents_quotes_masked_truncated_and_dated(graph):
    pool = [
        {
            "id": "a",
            "text": ag._mask("mail x@y.com see https://e.com " + "w " * 400),
            "published": None,
        },
        {"id": "b", "text": "old post", "published": datetime(2020, 1, 1)},
        {"id": "c", "text": "new post", "published": datetime(2024, 1, 1)},
    ]
    assert "@" not in pool[0]["text"] and "https" not in pool[0]["text"]
    assert len(pool[0]["text"]) <= ag.QUOTE_CHARS
    full = ag.build(graph, HashEmb(), pool)
    assert len(full) == 5 and all(len(a.quote_ids) == 3 for a in full)
    replay = ag.build(graph, HashEmb(), pool, before=datetime(2022, 1, 1))
    assert all(a.quote_ids == ["b"] for a in replay)


def test_world_rows_are_labelled_simulated(graph, tmp_path):
    agents = ag.build(graph, HashEmb(), [])
    cells = world.main_cells(graph, agents)[:7]
    assert {c.condition for c in cells} == set(world.CONDITIONS)
    llm = EchoLLM()
    rows = world.run(llm, ssr.SSR(HashEmb()), graph, agents, cells, tmp_path / "w.jsonl", 2)
    assert all(r["label"] == "SIMULATED" and r["prompt_hash"] == world.prompt_hash() for r in rows)
    assert all(abs(r["p_stay"] + r["p_consider"] + r["p_switch"] - 1) < 1e-9 for r in rows)
    assert "10%" in next(p for p in llm.prompts if "10%" in p)
    inc_text = world.solutions(graph)[cells[0].incumbent]
    assert all(f"- {inc_text}\n" not in p.split("Other options")[1] for p in llm.prompts)


def test_simulated_rows_never_reach_l4(graph, tmp_path):
    """Gate 13: even dressed as USER voices with a quote, simulated rows give no receipts."""
    from nmt_engine import ledger

    agents = ag.build(graph, HashEmb(), [])
    cells = world.main_cells(graph, agents)[:3]
    rows = world.run(EchoLLM(), ssr.SSR(HashEmb()), graph, agents, cells, tmp_path / "w.jsonl")
    recs = [
        r
        | {
            "source_id": f"sim{i}",
            "url": "x",
            "author_hash": f"h{i}",
            "role": "USER",
            "names_solution": True,
            "nodes": {"J2": {"verdict": "supports", "quote": "q"}},
        }
        for i, r in enumerate(rows * 3)
    ]
    (st,) = ledger.node_status(recs, ["J2"])
    assert st.status == "unknown" and not st.supports


def test_cross_model_thresholds():
    def rows(vals):
        return [
            {"agent": "G1", "incumbent": "S1", "condition": str(i), "p_switch": v}
            for i, v in enumerate(vals)
        ]

    base = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert (
        stability.cross_model({"a": rows(base), "b": rows(base), "c": rows(base)})["verdict"]
        == "no cap"
    )
    rev = stability.cross_model({"a": rows(base), "b": rows(base[::-1])})
    assert rev["rho"] == pytest.approx(-1) and rev["verdict"] == "unusable"
    mid = stability.cross_model({"a": rows(base), "b": rows([0.3, 0.1, 0.2, 0.5, 0.4])})
    assert mid["verdict"] == "capped at S1"


def test_internal_validity_price_order():
    rows = [
        {"agent": "G1", "incumbent": "S1", "condition": c, "repeat": r, "p_switch": p + r * 0.02}
        for c, p in (("none", 0.1), ("price10", 0.2), ("price50", 0.4))
        for r in range(3)
    ]
    iv = stability.internal_validity(rows)
    assert iv["price_order_preserved"] == "1/1"
    assert iv["repeat_mad"] == pytest.approx(0.0267, abs=1e-3)


def test_ssr_gold_split_and_not_measured(tmp_path):
    rows, sims = [], {}
    for i in range(10):
        rid = f"SG-stay-{i:03d}"
        rows.append({"id": rid, "class": "stay", "split": ssr_gold.split_of(rid)})
        sims[rid] = {"stay": 0.9, "consider": 0.1, "switch:x": 0.1}
    (tmp_path / ssr_gold.FILE).write_text("".join(json.dumps(r) + "\n" for r in rows))
    rec = tmp_path / ssr_gold.REC_DIR / f"{ssr.anchor_hash()}.json"
    rec.parent.mkdir()
    rec.write_text(json.dumps({"sims": sims}))
    res = ssr_gold.check(tmp_path)
    assert res["classes"]["stay"]["test"]["status"] == "NOT MEASURED"
    assert res["passed"] and not res["t3_may_run"]


def test_ssr_gold_committed_recording():
    """CI: the committed SSR gold is recorded under the current anchor hash. The result is a
    pre-registered FAIL (amendment 5); this test pins it so it cannot silently change."""
    res = ssr_gold.check()
    assert "error" not in res
    assert res["t3_may_run"] is False
