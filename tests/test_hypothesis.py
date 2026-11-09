import json

import pytest
from pydantic import ValidationError

from nmt_engine.brief import Brief
from nmt_engine.brief import load_brief as _load
from nmt_engine.config import repo_root
from nmt_engine.hypothesis import consistency, generate, gold
from nmt_engine.hypothesis.schema import HypothesisGraph

RAT = {"p_wrong": "high", "cost_if_wrong": "high", "cost_to_check": "low", "reason": "a guess"}
LOW = {"p_wrong": "low", "cost_if_wrong": "low", "cost_to_check": "high", "reason": "obvious"}


def load_brief(name):
    return _load(repo_root() / "briefs" / f"{name}.json")


def n(id, type, text, rat=LOW, **kw):
    return {"id": id, "type": type, "text": text, "rationale": "because so", "rat": rat, **kw}


def nodes():
    return [
        n("J1", "job", "I want to get paid for my work", level="big"),
        n("J2", "job", "I want to send a clear invoice", level="core", parent="J1"),
        n("J3", "job", "I want to chase late payers", level="core", parent="J1", rat=RAT),
        n("J4", "job", "I want to fill in client details", level="small", parent="J2"),
        n("J5", "job", "I want to copy last month's lines", level="micro", parent="J4"),
        n("S1", "solution", "Spreadsheet template", kind="spreadsheet", serves=["J2"]),
        n("S2", "solution", "Manual reminder emails", kind="manual", serves=["J3"]),
        n("C1", "criterion", "The invoice looks professional", job="J2"),
        n("C2", "criterion", "Clients pay without a reminder", job="J3"),
        n("C3", "criterion", "Little time spent per invoice", job="J2"),
        n("C4", "criterion", "I know who is late without checking", job="J3"),
        n("P1", "problem", "Reminders feel awkward", job="J3", solution="S2", criteria=["C2"]),
        n("G1", "segment", "Solo designers", core_jobs=["J2"], criteria_order=["C1", "C3"]),
        n("G2", "segment", "Busy consultants", core_jobs=["J2"], criteria_order=["C3", "C1"]),
        n("G3", "segment", "Agencies", core_jobs=["J2", "J3"], criteria_order=["C2", "C1"]),
        n("J6", "job", "I want to keep a record of what I billed", level="core", parent="J1"),
        n("S3", "solution", "Accountant's ledger", kind="service", serves=["J6"]),
        n("C5", "criterion", "I can find any old invoice fast", job="J6"),
        n("C6", "criterion", "My accountant accepts the records as they are", job="J6"),
    ]


def graph(ns=None):
    return HypothesisGraph.model_validate({"brief": "t", "nodes": ns or nodes()})


def test_valid_graph_priority_importance_and_riskiest():
    g = graph()
    assert g.node("J3").rat.priority == pytest.approx(0.8 * 9 / 1)
    assert g.node("J2").rat.priority == pytest.approx(0.2 * 1 / 9, abs=1e-4)
    imp = g.importance()
    assert set(imp) == {x["id"] for x in nodes()} and abs(sum(imp.values()) - 1) < 1e-3
    top = g.riskiest(3)
    assert top[0]["id"] == "J3"
    assert all(r["id"] != "J1" and not r["id"].startswith("G") for r in g.riskiest(50))


@pytest.mark.parametrize(
    "patch, msg",
    [
        ({"id": "J4", "text": "I want the invoice to look nice"}, "I want to"),
        ({"id": "J4", "parent": "J1"}, "core job"),
        ({"id": "C1", "rationale": "about 3 times a month"}, "no numbers"),
        ({"id": "C1", "text": "Paid within £20 of the quote"}, "no numbers"),
        ({"id": "J5", "id_new": "X5"}, "id must be"),
        ({"id": "G2", "criteria_order": ["C1", "C3"]}, "same criteria order"),
        ({"id": "G1", "core_jobs": ["J4"]}, "core job"),
        ({"id": "P1", "solution": "C1"}, "not a solution"),
    ],
)
def test_schema_rejects(patch, msg):
    ns = nodes()
    tgt = next(x for x in ns if x["id"] == patch["id"])
    for k, v in patch.items():
        if k == "id_new":
            tgt["id"] = v
        elif k != "id":
            tgt[k] = v
    with pytest.raises(ValidationError, match=msg):
        graph(ns)


def test_core_job_needs_criterion_and_solution_and_segment_count():
    ns = [x for x in nodes() if x["id"] != "C4"]
    with pytest.raises(ValidationError, match="J3: a Core Job needs at least 2 success criteria"):
        graph(ns)
    ns = [x for x in nodes() if x["id"] != "S3"]
    with pytest.raises(ValidationError, match="J6: a Core Job needs at least one Solution"):
        graph(ns)
    with pytest.raises(ValidationError, match="segments"):
        graph([x for x in nodes() if x["id"] not in ("G2", "G3")])
    with pytest.raises(ValidationError, match="2 Core Jobs; need 3-5"):
        graph([x for x in nodes() if x["id"] not in ("J6", "S3", "C5", "C6")])


def test_link_errors_are_reported_together():
    ns = nodes()
    ns[3]["parent"] = "J1"
    ns[7]["job"] = "J99"
    with pytest.raises(ValidationError) as e:
        graph(ns)
    assert "J4: J1 is not a core job" in str(e.value) and "C1: J99 is not a job" in str(e.value)


def test_problem_may_name_a_job_its_solution_is_not_listed_for():
    ns = nodes()
    next(x for x in ns if x["id"] == "P1").update(job="J4", solution="S1", criteria=["C1"])
    graph(ns)


def test_letter_digit_words_are_not_numbers():
    ns = nodes()
    ns[7]["rationale"] = "B2B buyers report this every Q1"
    graph(ns)


def test_brief_job_terms(tmp_path):
    b = load_brief("invoicing")
    assert b.market_job.startswith("I want to") and len(b.hash) == 16
    with pytest.raises(ValidationError):
        Brief(**{**b.model_dump(), "market_job": "Invoicing software"})


class FakeLLM:
    model, host = "fake/kimi", "fake"

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def complete_json(self, prompt, system, purpose):
        self.prompts.append(prompt)
        r = self.replies.pop(0)
        return r(prompt) if callable(r) else r


def all_yes(prompt):
    k = sum(1 for line in prompt.splitlines() if line[:1].isdigit() and ". " in line[:5])
    return {"answers": [{"n": i + 1, "consistent": "yes", "reason": ""} for i in range(k)]}


def test_build_regenerates_with_feedback_then_passes():
    brief = load_brief("invoicing")
    bad = {"nodes": nodes()[:3]}
    producer = FakeLLM([bad, {"nodes": nodes()}])
    k = len(consistency.statements(graph()))
    auditor = FakeLLM([all_yes] * (k // consistency.BATCH + 1))
    res = generate.build(producer, auditor, brief)
    assert res["status"] == "passed" and len(res["attempts"]) == 2
    assert "segments" in producer.prompts[1] or "Core Job" in producer.prompts[1]
    out = generate.to_json(res["graph"], brief, res["status"])
    assert out["riskiest"][0]["id"] == "J3" and out["nodes"][2]["rat_priority"] == 7.2


def test_build_flags_after_two_regenerations():
    brief = load_brief("invoicing")
    k = len(consistency.statements(graph()))

    def one_no(prompt):
        r = all_yes(prompt)
        r["answers"][0] = {"n": 1, "consistent": "no", "reason": "off"}
        return r

    batches = k // consistency.BATCH + 1
    producer = FakeLLM([{"nodes": nodes()}] * 3)
    auditor = FakeLLM([one_no] * (3 * batches))
    res = generate.build(producer, auditor, brief)
    assert res["status"] == "flagged" and len(res["attempts"]) == 3
    assert "inconsistent link" in producer.prompts[2]


def test_load_roundtrip(tmp_path):
    brief = load_brief("invoicing")
    p = tmp_path / "g.json"
    p.write_text(json.dumps(generate.to_json(graph(), brief, "passed")))
    assert generate.load(p).model_dump() == graph().model_dump() | {"brief": "invoicing"}


def test_gold_build_split_by_origin_and_check(tmp_path):
    g = graph()
    stats = gold.build(g, seed=1, out=tmp_path)
    items = [json.loads(x) for x in (tmp_path / "items.jsonl").read_text().splitlines()]
    assert stats["consistent"] > 0 and stats["inconsistent"] > 0
    for o in {it["origin"] for it in items}:
        assert len({it["split"] for it in items if it["origin"] == o}) == 1
    miss = gold.check(tmp_path, phash="none")
    assert miss["passed"] is False and miss["classes"] == {} and miss["passed_for"] == []
    rec = tmp_path / "recorded" / "h.json"
    rec.parent.mkdir()
    answers = {it["id"]: {"consistent": it["truth"]} for it in items}
    rec.write_text(json.dumps({"answers": answers}))
    res = gold.check(tmp_path, phash="h")
    assert res["passed"] is True  # perfect but few calls: NOT MEASURED, never PASS
    assert all(c["test"]["status"] == "NOT MEASURED" for c in res["classes"].values())
    assert res["passed_for"] == []


def test_l1_ci_consistency_gate_on_current_prompt():
    """Committed Kimi answers for the current check prompt; CI fails on a measured class < 85%."""
    res = gold.check()
    assert "error" not in res, res.get("error")
    assert res["passed"], res
    assert all(c["test"]["status"] == "PASS" for c in res["classes"].values()), res
    path = repo_root() / "briefs" / "invoicing.l1.json"
    frozen = json.loads(path.read_text("utf-8"))
    assert frozen["l1_status"] == "passed"
    assert frozen["brief_hash"] == load_brief("invoicing").hash  # brief edits must not drift
    generate.load(path)
