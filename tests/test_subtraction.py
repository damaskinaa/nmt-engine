"""ARCHITECTURE_v3 §4.9 + §8 C2: gates 3, 5, 6, 9, 12 and non-L2 collectors are off by default."""

from __future__ import annotations

import pytest

from nmt_engine.collect.run import _steps
from nmt_engine.gates import REGISTRY, GateConfig, run_gates
from nmt_engine.subtraction import GATES_OFF, active_gates, collector_on
from tests.fixtures.make_fixtures import CORPUS, RUNS


def test_nine_gates_are_active_and_gate_8_stays_on():
    on = active_gates(list(REGISTRY), {})
    assert sorted(GATES_OFF) == [3, 5, 6, 9, 12]
    assert on == [1, 2, 4, 7, 8, 10, 11, 13, 14]


def test_off_gate_is_reported_not_run():
    report = run_gates(RUNS / "broken_g03", GateConfig(forbidden_corpus=CORPUS))
    assert report.passed and 3 in report.off
    assert "| 3 |" in report.to_markdown() and "off" in report.to_markdown()


def test_reenable_needs_a_reason():
    cfg = GateConfig(forbidden_corpus=CORPUS, reenable={3: "checking author numbers"})
    assert run_gates(RUNS / "broken_g03", cfg).failed_gates() == [3]
    with pytest.raises(ValueError, match="needs a reason"):
        run_gates(RUNS / "clean", GateConfig(forbidden_corpus=CORPUS, reenable={3: " "}))


def test_only_the_six_l2_collectors_are_on():
    from datetime import date

    from nmt_engine.collect.run import CollectPlan

    plan = CollectPlan("invoicing", date(2024, 1, 1), competitors=["freshbooks.com"])
    on = {n.split(":")[0] for n, _ in _steps(plan) if collector_on(n, {})}
    assert on == {"hackernews", "stackexchange", "appstore", "github", "web", "wayback"}
    assert not collector_on("reddit", {}) and collector_on("reddit", {"reddit": "key added"})
    with pytest.raises(ValueError):
        collector_on("reddit", {"reddit": ""})
