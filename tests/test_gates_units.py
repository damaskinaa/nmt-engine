import copy
import json

import pytest
from pydantic import ValidationError

from nmt_engine.gates import GateConfig, run_gates
from nmt_engine.schema import Claim, Source
from nmt_engine.store import Store
from nmt_engine.util import author_hash
from tests.fixtures.make_fixtures import CORPUS, _by_id, clean, write

CFG = GateConfig(forbidden_corpus=CORPUS)


def failed(tmp_path, mutate, post=None):
    fx = copy.deepcopy(clean())
    mutate(fx)
    run = write(fx, tmp_path / "run", "t")
    if post:
        post(run)
    return run_gates(run, CFG)


def test_calc_without_receipt_and_literal(tmp_path):
    def m(fx):
        k1 = _by_id(fx["calcs"], "K1")
        k1["inputs"][0]["claim_id"] = None
        k3 = _by_id(fx["calcs"], "K3")
        k3["formula"] = "cost_per_return * returns * 2"
        _by_id(fx["calcs"], "K2")["interval_80"] = [1.0, 2.0]

    r = failed(tmp_path, m)
    g4 = next(x for x in r.results if x.gate.number == 4)
    msgs = " ".join(f.message for f in g4.findings)
    assert "no claim_id" in msgs and "literal" in msgs and "outside interval" in msgs


def test_calc_wrong_median_and_bad_unit(tmp_path):
    def m(fx):
        _by_id(fx["calcs"], "K1")["median"] = 1.0
        _by_id(fx["calcs"], "K3")["inputs"][0]["unit"] = "florins"

    msgs = [f.message for x in failed(tmp_path, m).results for f in x.findings]
    assert any("recomputed" in s for s in msgs) and any("mismatch" in s for s in msgs)


def test_segment_size_reuse_and_declared_overlap(tmp_path):
    def m(fx):
        s2 = _by_id(fx["segments"], "SEG2")
        s2["size"] = "Y1"
        s2["population"]["share"] = [0.6, 0.7]
        s2["population"]["declared_overlaps"] = [{"segment_id": "SEG1", "share": 0.2}]

    r = failed(tmp_path, m)
    g6 = next(x for x in r.results if x.gate.number == 6)
    assert len(g6.findings) == 1 and "reused" in g6.findings[0].message


def test_source_sha_mismatch_and_unknown_refs(tmp_path):
    def m(fx):
        _by_id(fx["calcs"], "K1")["inputs"][0]["claim_id"] = "C404"
        _by_id(fx["calcs"], "K1")["inputs"][1]["source_id"] = "S404"
        _by_id(fx["claims"], "C3")["source_refs"].append({"source_id": "S404", "verbatim": "x"})

    def post(run):
        (run / "sources" / "S-w1.txt").write_text(
            "tampered " + (run / "sources" / "S-w1.txt").read_text()
        )

    r = failed(tmp_path, m, post)
    msgs = [f.message for f in next(x for x in r.results if x.gate.number == 7).findings]
    assert any("sha256" in s for s in msgs)
    assert any("unknown claim" in s for s in msgs) and any("unknown source S404" in s for s in msgs)


def test_missing_source_text_and_manifest(tmp_path):
    def post(run):
        (run / "sources" / "S-f1.txt").unlink()
        (run / "run_manifest.json").unlink()

    r = failed(tmp_path, lambda fx: None, post)
    assert {1, 9} <= set(r.failed_gates())


def test_manifest_hash_tamper_and_missing_frozen(tmp_path):
    def post(run):
        m = json.loads((run / "run_manifest.json").read_text())
        m["manifest_sha256"] = "0" * 64
        (run / "run_manifest.json").write_text(json.dumps(m))
        (run / "inputs/brief.md").unlink()

    g9 = next(x for x in failed(tmp_path, lambda fx: None, post).results if x.gate.number == 9)
    assert len(g9.findings) == 2


def test_firewall_variants(tmp_path):
    def m(fx):
        _by_id(fx["calcs"], "K1")["inputs"][0]["claim_id"] = "C8"
        fx["sim_runs"][0]["inputs"] = ["C8"]
        y = _by_id(fx["synthetics"], "Y1")
        y["grade"] = "S4"
        y["methods"] = y["methods"][:2]
        y["calibration_ids"] = []
        y["forecast_id"] = None
        _by_id(fx["claims"], "C7")["grade"] = "S4"
        fx["strategies"][0]["go_no_go_claim_ids"] = ["C8"]

    g13 = next(x for x in failed(tmp_path, m).results if x.gate.number == 13)
    msgs = " ".join(f.message for f in g13.findings)
    for needle in (
        "is S0",
        "MC input",
        "fewer than 3",
        "no passed Calibration",
        "no registered Forecast",
        "S4 without MarketTouch",
        "S3+ required",
    ):
        assert needle in msgs


def test_lint_html_and_market_touch(tmp_path):
    def m(fx):
        fx["files"]["report.html"] = (
            "<p>Demand <b>proven</b> by MT-1 fake door.</p><p>It is proven.</p>"
        )

    g8 = next(x for x in failed(tmp_path, m).results if x.gate.number == 8)
    assert len(g8.findings) == 2  # no MarketTouch MT-1 stored -> both flagged


def test_forbidden_host_and_module_a(tmp_path):
    def m(fx):
        _by_id(fx["sources"], "S-p1")["url"] = "https://www.trustpilot.com/review/x"

    def post(run):
        (run / "report.md").write_text(
            "the lighthouse keeper counted seventeen grey gulls on the northern rail before dawn"
        )
        m = json.loads((run / "run_manifest.json").read_text())
        m["method_module"] = "A"
        (run / "run_manifest.json").write_text(json.dumps(m))

    r = failed(tmp_path, m, post)
    assert 14 in r.failed_gates() and 10 not in r.failed_gates()


def test_schema_errors_reported(tmp_path):
    def post(run):
        with (run / "store" / "claim.jsonl").open("a") as fh:
            fh.write(
                json.dumps(
                    {"id": "CX", "text": "x", "status": "SYNTHETIC_ESTIMATE", "geography": "IE"}
                )
                + "\n"
            )

    r = failed(tmp_path, lambda fx: None, post)
    assert not r.passed and r.schema_errors and "Schema errors" in r.to_markdown()


def test_claim_requires_grade_for_synthetic():
    with pytest.raises(ValidationError):
        Claim(id="c", text="t", status="SYNTHETIC_ESTIMATE", geography="IE")


def test_store_revisions_and_supersedes(tmp_path):
    st = Store(tmp_path)
    base = dict(text="t", status="HYPOTHESIS", geography="IE")
    st.append(Claim(id="a", **base))
    st.append(Claim(id="a", rev=1, **{**base, "text": "t2"}))
    st.append(Claim(id="b", supersedes="c", **base))
    st.append(Claim(id="c", **base))
    st.append(Claim(id="d", retracted=True, **base))
    cur = st.current("claim")
    assert set(cur) == {"a", "b"} and cur["a"].text == "t2"
    assert len(st.history("claim")) == 5 and st.current("source") == {}


def test_author_hash_requires_salt(monkeypatch):
    monkeypatch.delenv("NMT_AUTHOR_SALT", raising=False)
    with pytest.raises(RuntimeError):
        author_hash("reddit", "bob")
    assert author_hash("reddit", "bob", salt="s") == author_hash("reddit", "bob", salt="s")
    assert author_hash("reddit", "bob", salt="s") != author_hash("reddit", "bob", salt="t")


def test_source_access_basis_is_free_text_for_gate14():
    s = Source(
        id="s",
        kind="web",
        platform="p",
        url="https://x",
        retrieved_at="2026-01-01T00:00:00Z",
        as_of_date="2026-01-01",
        geography="IE",
        text_path="sources/s.txt",
        sha256="0",
    )
    assert s.access_basis is None


def test_frozen_path_outside_run_is_rejected(tmp_path):
    def post(run):
        m = json.loads((run / "run_manifest.json").read_text())
        m["frozen"].append({"path": "../outside.txt", "sha256": "0" * 64})
        (tmp_path / "outside.txt").write_text("private")
        (run / "run_manifest.json").write_text(json.dumps(m))

    g9 = next(x for x in failed(tmp_path, lambda fx: None, post).results if x.gate.number == 9)
    assert any("outside the run" in f.message for f in g9.findings)


def test_missing_source_text_fails_gate7(tmp_path):
    r = failed(tmp_path, lambda fx: None, lambda run: (run / "sources" / "S-p1.txt").unlink())
    g7 = next(x for x in r.results if x.gate.number == 7)
    assert any("missing" in f.message for f in g7.findings)


def test_prompts_are_licence_scanned(tmp_path):
    def post(run):
        (run / "prompts").mkdir()
        (run / "prompts" / "p.txt").write_text((CORPUS / "sample.txt").read_text())

    assert 10 in failed(tmp_path, lambda fx: None, post).failed_gates()


def test_firewall_overlap_and_unlinked_claim(tmp_path):
    def m(fx):
        y = _by_id(fx["synthetics"], "Y1")
        y["grade"] = "S2"
        y["methods"][0]["interval_80"] = [1, 2]
        _by_id(fx["claims"], "C7")["grade"] = "S2"
        _by_id(fx["claims"], "C7")["synthetic_id"] = None
        fx["strategies"][0]["why_we_win"]["claim_ids"] = ["C1"]

    g13 = next(x for x in failed(tmp_path, m).results if x.gate.number == 13)
    msgs = " ".join(f.message for f in g13.findings)
    assert "do not overlap" in msgs and "exceeds its Synthetic" in msgs


def test_demote_recount_to_one_voice_thins_job(tmp_path):
    from nmt_engine.gates import demote
    from nmt_engine.store import load_run

    fx = copy.deepcopy(clean())
    c9 = copy.deepcopy(_by_id(fx["claims"], "C1"))
    c9.update(id="C9", voices=2, source_refs=c9["source_refs"][:1])
    fx["claims"].append(c9)
    _by_id(fx["jobs"], "J2")["claim_ids"].append("C9")
    run = write(fx, tmp_path / "run", "t")
    assert 2 in run_gates(run, CFG).failed_gates()
    demote(run, CFG)
    data = load_run(run)
    assert data.claims["C9"].voices == 1 and data.claims["C9"].single_signal
    assert data.jobs["J2"].thin
