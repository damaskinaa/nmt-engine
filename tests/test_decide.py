from nmt_engine.decide import chain
from nmt_engine.synth.grade import GradeInputs

FAM = frozenset({"a", "b", "c"})


def _q(q, est, g="S3"):
    inputs = {
        "S0": GradeInputs(anchored=False),
        "S1": GradeInputs(anchored=True),
        "S3": GradeInputs(
            anchored=True, families=FAM, calibrated_families=FAM, forecast_registered=True
        ),
    }[g]
    return chain.Quantity(q, inputs, est)


def _all(g="S3"):
    est = {
        "Q1": (10_000, 5_000, 20_000),
        "Q2": (4, 2, 8),
        "Q3": (100, 50, 200),
        "Q4": (40, 30, 55),
        "Q5": (5, 3, 8),
        "Q6": (150, 80, 300),
        "Q7": (0.1, 0.05, 0.2),
        "Q8": (10, 2, 18),
        "Q9": (0.8, 0.6, 0.9),
    }
    return {q: _q(q, e, g) for q, e in est.items()}


def test_monte_carlo_fixed_seed_and_runs():
    qs = _all()
    a = chain.monte_carlo(qs, chain.Targets(annual_revenue=300_000))
    b = chain.monte_carlo(qs, chain.Targets(annual_revenue=300_000))
    assert a == b and a["runs"] >= 10_000
    assert a["p_margin"] > 0.6 and a["p_q8_positive"] > 0.9
    assert 0 < a["p_volume"] < 1


def test_unanchored_blocks_monte_carlo_and_validation():
    qs = _all("S0")
    assert chain.can_run(qs) == list(chain.CHAIN)
    v = chain.validate(qs, None, None)
    assert not v["validated"] and not any(v["checks"].values())
    assert chain.decision(v["validated"], None, 50).startswith("NO GO")


def test_validation_needs_every_item():
    qs = _all()
    mc = {"p_margin": 0.9, "p_payback": 0.9, "p_volume": 0.9, "p_q8_positive": 0.9}
    assert chain.validate(qs, mc, False)["validated"]
    assert not chain.validate(qs, mc, True)["validated"]
    assert not chain.validate(qs, mc, None)["validated"]
    qs["Q4"] = _q("Q4", (40, 30, 55), "S1")
    assert not chain.validate(qs, mc, False)["validated"]
    assert chain.decision(True, 10, 50) == "GO to build"
    assert chain.decision(True, 100, 50).startswith("NO GO")
