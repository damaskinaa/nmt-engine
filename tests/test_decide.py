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


def test_report_gate_flags_missing_page_one_and_banned_claims():
    from nmt_engine.report import groundwork

    pkt = {
        "status": {"supported": 0, "contradicted": 0},
        "simulation": {"conditions": []},
        "radar": {"groups": [{"name": "g", "quote": "q", "verbatim": False}]},
        "monte_carlo": {"ran": False},
    }
    html = '<section class="page">0 of 10</section><p>Customers want reminders.</p>'
    assert any("not found" in p for p in groundwork.check(html, pkt))
    problems = groundwork.check(html, pkt)
    assert any("7 of 10" in p for p in problems)
    assert any("customers want" in p for p in problems)
    assert any("verbatim" in p for p in problems)
    html = html.replace('class="page"', 'id="page1"') + '<section id="simulation"></section>'
    problems = groundwork.check(html, pkt)
    assert any("7 of 10" in p for p in problems) and not any("not found" in p for p in problems)
    ok = (
        '<section id="page1">'
        + " ".join(groundwork.PAGE_ONE)
        + '</section><section id="simulation"></section><p>not human-verified</p>'
    )
    assert groundwork.check(ok, pkt | {"radar": {"groups": []}}) == []


def test_retention_moves_volume_and_payback():
    t = chain.Targets(annual_revenue=300_000)
    hi, lo = _all(), _all()
    hi["Q9"] = _q("Q9", (0.97, 0.95, 0.99))
    lo["Q9"] = _q("Q9", (0.3, 0.2, 0.4))
    a, b = chain.monte_carlo(hi, t), chain.monte_carlo(lo, t)
    assert a["p_volume"] > b["p_volume"] and a["p_payback"] > b["p_payback"]


def test_payback_counts_only_retained_margin():
    # unit margin about 35, CAC about 150: 4.3 months with no churn, but at 90% monthly
    # retention the retained customers need about 5.3 months to repay it
    qs = _all()
    t = chain.Targets(annual_revenue=300_000, payback_months=5)
    qs["Q9"] = _q("Q9", (0.999, 0.998, 0.9995))
    no_churn = chain.monte_carlo(qs, t)["p_payback"]
    qs["Q9"] = _q("Q9", (0.9, 0.89, 0.91))
    churn = chain.monte_carlo(qs, t)["p_payback"]
    assert churn < no_churn - 0.1


def test_report_gate_flags_monte_carlo_figures_without_interval_even_if_ran_missing():
    from nmt_engine.report import groundwork

    pkt = {
        "status": {"supported": 0, "contradicted": 0},
        "simulation": {"conditions": []},
        "radar": {"groups": []},
    }
    ok = (
        '<section id="page1">'
        + " ".join(groundwork.PAGE_ONE)
        + '</section><section id="simulation"></section>'
    )
    for mc in ({"p_volume": 0.7}, {"ran": True}):
        assert any("interval" in p for p in groundwork.check(ok, pkt | {"monte_carlo": mc}))
    assert groundwork.check(ok, pkt | {"monte_carlo": {"ran": False, "blocked_by": ["Q1"]}}) == []


def test_list_prices_grade_q4_s1_and_skip_annual_billing():
    from nmt_engine.decide import prices

    text = "Pro $12 Per month. Pro $10 Per month with an annual plan! Team $190 per year"
    good = {"plan": "Pro", "price": 12, "quote": "$12 Per month"}
    assert prices._ok(good, text)
    assert not prices._ok(good | {"price": 13}, text)
    assert not prices._ok(good | {"quote": "$12 a month"}, text)
    rows = [
        {
            "app": "A",
            "price": 12.0,
            "currency": "USD",
            "period": "month",
            "plan": "Pro",
            "quote": "$12 Per month",
        },
        {
            "app": "A",
            "price": 10.0,
            "currency": "USD",
            "period": "month",
            "plan": "Pro",
            "quote": "$10 Per month with an annual plan!",
        },
        {
            "app": "B",
            "price": 120.0,
            "currency": "USD",
            "period": "year",
            "plan": "Team",
            "quote": "$120 per year",
        },
        {
            "app": "B",
            "price": 0.0,
            "currency": "USD",
            "period": "month",
            "plan": "Free",
            "quote": "$0",
        },
        {
            "app": "C",
            "price": 9.0,
            "currency": "CAD",
            "period": "month",
            "plan": "X",
            "quote": "$9CAD",
        },
    ]
    entry = prices.entry_monthly_usd(rows)
    assert entry == {"A": 12.0, "B": 10.0}
    q = prices.q4(entry)
    assert q.grade == "S1" and q.estimate[0] == 11.0
    assert any("not willingness to pay" in n for n in q.notes)
    assert prices.q4({}).grade == "S0"
    qs = _all() | {"Q4": q, "Q1": _q("Q1", None, "S0")}
    assert chain.can_run(qs) == ["Q1"]
