import math
from datetime import date

import numpy as np
import pytest

from nmt_engine.schema import BacktestCase, CalcInput, Forecast, MarketTouch, Source
from nmt_engine.store import Store
from nmt_engine.synth import (
    ForecastRegistry,
    GradeInputs,
    LeakageError,
    MethodEstimate,
    MethodInput,
    assert_no_leakage,
    calibrate,
    calibrated_interval,
    citation_label,
    estimate,
    evpi_go_no_go,
    from_log,
    grade,
    to_log,
    triangulate,
)
from nmt_engine.synth.calibrate import calibration_record
from nmt_engine.synth.estimate import calibrated_estimate
from nmt_engine.synth.world import (
    AS_OF,
    WorldConfig,
    calibrations_for,
    coverage,
    generate_world,
)

F3 = frozenset({"statistical", "supply", "revealed_price"})


# --- log form, calibration maths ---------------------------------------------------------


def test_log_form_roundtrip():
    mu, sigma = to_log(27, 20, 36)
    assert mu == pytest.approx(math.log(27))
    assert sigma == pytest.approx((math.log(36) - math.log(20)) / (2 * 1.2816))
    med, lo, hi = from_log(mu, 1.2816 * sigma)
    assert med == pytest.approx(27) and lo * hi == pytest.approx(27**2)
    with pytest.raises(ValueError):
        to_log(0, 1, 2)
    with pytest.raises(ValueError):
        to_log(5, 1, 2)


def test_calibrate_conformal_rank_and_pass_rule():
    pairs = [(math.exp(0.01 * i), 1.0) for i in range(1, 21)]  # log ratios 0.01..0.20
    s = calibrate(pairs)
    assert s.bias_log == pytest.approx(0.105)  # median of 0.01..0.20
    r = sorted(abs(0.01 * i - 0.105) for i in range(1, 21))
    assert s.conformal_q80 == pytest.approx(r[math.ceil(21 * 0.8) - 1])
    assert s.n == 20 and s.passed == (0.75 <= s.coverage_loo <= 0.90)
    small = calibrate(pairs[:10])
    assert not small.passed and math.isinf(calibrate(pairs[:3]).conformal_q80)
    with pytest.raises(ValueError):
        calibrate(pairs[:1])


def test_calibrated_interval_uses_wider_of_q80_and_stated():
    assert calibrated_interval(1.0, 0.1, 0.2, 0.5) == pytest.approx((0.8, 0.5))
    assert calibrated_interval(1.0, 0.5, 0.0, 0.1) == pytest.approx((1.0, 1.2816 * 0.5))
    assert calibrated_interval(1.0, 0.5) == pytest.approx((1.0, 1.2816 * 0.5))


# --- (a) coverage over 200 worlds ----------------------------------------------------------


def test_a_coverage_200_worlds_within_75_85():
    cov = np.mean([coverage(generate_world(WorldConfig(seed=s))) for s in range(200)])
    assert 0.75 <= cov <= 0.85


# --- (b) seeded family bias detected and corrected -----------------------------------------


def test_b_family_bias_detected_and_corrected():
    detected, log_err = [], []
    for seed in range(200):
        w = generate_world(WorldConfig(seed=seed, bias={"supply": 1.5}))
        cals = calibrations_for(w)
        for q in cals:
            detected.append(abs(cals[q]["supply"].bias_log_ratio) > math.log(1.2))
        for (seg, q), ms in w.methods.items():
            m = next(x for x in ms if x.family == "supply")
            e = calibrated_estimate(m, cals[q]["supply"])
            log_err.append(e.mu - math.log(w.truth[(seg, q)]))
    assert np.mean(detected) > 0.95
    assert abs(math.exp(np.median(log_err)) - 1) < 0.10


# --- (c) same-family padding ----------------------------------------------------------------


def _three():
    return [
        MethodInput("statistical", "K1", 27, 20, 36),
        MethodInput("supply", "K2", 30, 21, 42),
        MethodInput("revealed_price", "K3", 25, 19, 33),
    ]


def test_c_same_family_calcs_do_not_raise_grade_or_shrink_interval():
    base, tb = estimate("Y", "Q4", "IE", _three())
    padded = _three() + [
        MethodInput("statistical", f"P{i}", 26 + i, 20 + i, 35 + i) for i in range(5)
    ]
    more, tm = estimate("Y", "Q4", "IE", padded)
    assert more.grade == base.grade
    assert tm.k == tb.k == 3
    tightest = min((m for m in padded if m.family == "statistical"), key=lambda m: m.hi / m.lo)
    single = [m for m in _three() if m.family != "statistical"] + [tightest]
    _, ts = estimate("Y", "Q4", "IE", single)
    assert tm.half_width >= ts.half_width - 1e-12


def test_c_padding_cannot_reach_s2_from_two_families():
    two = [MethodInput("statistical", f"K{i}", 27, 20, 36) for i in range(6)]
    two.append(MethodInput("supply", "K9", 30, 21, 42))
    syn, _ = estimate("Y", "Q4", "IE", two)
    assert syn.grade == "S1"


# --- (d) disagreement -----------------------------------------------------------------------


def test_d_families_3x_apart_disagree_cap_s1_evpi_positive():
    ms = [
        MethodInput("statistical", "K1", 10, 8, 12.5),
        MethodInput("supply", "K2", 30, 24, 37.5),
        MethodInput("revealed_price", "K3", 11, 9, 13.5),
    ]
    reg_fc = Forecast(id="F1", synthetic_id="Y", resolution_rule="r", resolve_by=date(2027, 1, 1))
    syn, tri = estimate("Y", "Q4", "IE", ms, forecast=reg_fc)
    assert tri.methods_disagree and syn.methods_disagree and syn.grade == "S1"
    comps = [(e.mu, e.sigma) for e in tri.families]
    assert evpi_go_no_go(comps, threshold=18) > 0


def test_evpi_zero_when_all_mass_on_one_side_and_input_checks():
    assert evpi_go_no_go([(math.log(100), 0.05)], threshold=10) == pytest.approx(0, abs=1e-9)
    assert evpi_go_no_go([(math.log(1), 0.05)], threshold=10) == pytest.approx(0, abs=1e-9)
    assert evpi_go_no_go([(0.0, 0.1)], threshold=0) == pytest.approx(0)
    with pytest.raises(ValueError):
        evpi_go_no_go([], 1)
    with pytest.raises(ValueError):
        evpi_go_no_go([(0, 1)], 1, value_per_unit=-1)


def test_triangulate_formula():
    e = [MethodEstimate("a", 0.0, 0.1), MethodEstimate("b", 0.1, 0.2)]
    t = triangulate(e, rho=0.3)
    w = [100, 25]
    assert t.mu == pytest.approx((0 * 100 + 0.1 * 25) / 125)
    assert t.sigma == pytest.approx(math.sqrt(1 / sum(w)) * math.sqrt(1.3))
    assert t.max_z == pytest.approx(0.1 / math.sqrt(0.05))
    with pytest.raises(ValueError):
        triangulate([])


# --- (e) leakage ----------------------------------------------------------------------------


def test_e_leakage_raises():
    ok = CalcInput(name="x", value=1, as_of_date=date(2023, 1, 1))
    late = CalcInput(name="y", value=1, as_of_date=date(2025, 1, 1))
    assert_no_leakage([ok], date(2024, 1, 1))
    with pytest.raises(LeakageError):
        assert_no_leakage([ok, late], date(2024, 1, 1))
    src = Source(
        id="S1",
        kind="stats",
        platform="cso",
        url="https://example.org",
        retrieved_at="2025-03-01T00:00:00Z",
        as_of_date=date(2023, 6, 1),
        geography="IE",
        access_basis="open_licence",
        text_path="sources/S1.txt",
        sha256="0" * 64,
    )
    via_src = CalcInput(name="z", value=1, source_id="S1")
    with pytest.raises(LeakageError):
        assert_no_leakage([via_src], date(2024, 1, 1), {"S1": src})
    cases = [BacktestCase(case="c", as_of=date(2026, 6, 1), known_outcome=1, predicted=1)] * 3
    with pytest.raises(LeakageError):
        calibration_record("C", "statistical", "r", "<=T", cases, as_of=AS_OF)


# --- (f) grade boundaries -------------------------------------------------------------------


@pytest.mark.parametrize(
    "inputs, expected",
    [
        (GradeInputs(anchored=False, families=F3), "S0"),
        (GradeInputs(anchored=True), "S1"),
        (GradeInputs(anchored=True, families=frozenset({"statistical", "supply"})), "S1"),
        (GradeInputs(anchored=True, families=F3, methods_disagree=True), "S1"),
        (GradeInputs(anchored=True, families=F3), "S2"),
        (GradeInputs(anchored=True, families=F3, calibrated_families=F3), "S2"),
        (
            GradeInputs(
                anchored=True,
                families=F3,
                calibrated_families=F3 - {"supply"},
                forecast_registered=True,
            ),
            "S2",
        ),
        (
            GradeInputs(
                anchored=True, families=F3, calibrated_families=F3, forecast_registered=True
            ),
            "S3",
        ),
        (
            GradeInputs(
                anchored=True,
                families=F3,
                calibrated_families=F3,
                forecast_registered=True,
                market_touch_in_interval=True,
            ),
            "S4",
        ),
        (
            GradeInputs(
                anchored=True,
                families=F3,
                methods_disagree=True,
                calibrated_families=F3,
                forecast_registered=True,
                market_touch_in_interval=True,
            ),
            "S1",
        ),
    ],
)
def test_f_grade_boundaries(inputs, expected):
    assert grade(inputs) == expected


# --- (g) determinism ------------------------------------------------------------------------


def test_g_determinism():
    a, b = generate_world(WorldConfig(seed=11)), generate_world(WorldConfig(seed=11))
    assert a.truth == b.truth and a.methods == b.methods and a.reference == b.reference
    assert coverage(a) == coverage(b)
    assert generate_world(WorldConfig(seed=12)).truth != a.truth


# --- end-to-end S3/S4, forecasts, labels -----------------------------------------------------


def _calibrated_world():
    w = generate_world(WorldConfig(seed=3))
    cals = calibrations_for(w)["Q4"]
    assert all(c.passed for c in cals.values())
    return w, cals


def test_estimate_reaches_s3_and_s4_and_label(tmp_path):
    w, cals = _calibrated_world()
    ms = w.methods[("SEG1", "Q4")]
    s2, _ = estimate("Y1", "Q4", "WORLD", ms, cals, unit="EUR/month", segment_id="SEG1")
    assert s2.grade == "S2"
    reg = ForecastRegistry(Store(tmp_path))
    fc = reg.add(s2, "median paid price at launch+90d", date(2027, 6, 30))
    s3, _ = estimate("Y1", "Q4", "WORLD", ms, cals, forecast=fc, unit="EUR/month")
    assert s3.grade == "S3" and s3.forecast_id == fc.id and len(s3.calibration_ids) == 3
    lo, hi = s3.combined.interval_80
    touch = MarketTouch(
        id="MT1",
        kind="fake_door",
        metric="paid",
        value=(lo * hi) ** 0.5,
        n=200,
        started=date(2026, 2, 1),
    )
    s4, _ = estimate("Y1", "Q4", "WORLD", ms, cals, forecast=fc, market_touch=touch)
    assert s4.grade == "S4" and s4.market_touch_id == "MT1"
    miss = touch.model_copy(update={"value": hi * 2})
    assert estimate("Y1", "Q4", "WORLD", ms, cals, forecast=fc, market_touch=miss)[0].grade == "S3"

    label = citation_label(s3, {c.id: c for c in cals.values()}, reg.all())
    assert label.startswith("Q4 WTP: ")
    assert "80% conformal interval" in label and "SYNTHETIC S3 ·" in label
    assert f"forecast {fc.id} resolves 2027-06-30" in label and "backtest n≥30" in label
    assert "(not citable)" in citation_label(s2) and "80% interval" in citation_label(s2)


def test_forecast_registry_scoring(tmp_path):
    w, cals = _calibrated_world()
    syn, _ = estimate("Y1", "Q4", "WORLD", w.methods[("SEG1", "Q4")], cals)
    reg = ForecastRegistry(Store(tmp_path))
    fc = reg.add(syn, "rule", date(2027, 1, 1))
    assert fc.id == "F-0001"
    truth = w.truth[("SEG1", "Q4")]
    scored = reg.score(fc.id, syn, truth)
    lo, hi = syn.combined.interval_80
    assert scored.score.hit == (lo <= truth <= hi)
    assert scored.score.log_error == pytest.approx(math.log(truth / syn.combined.median))
    assert scored.score.brier == pytest.approx((0.8 - scored.score.hit) ** 2)
    assert reg.all()[fc.id].rev == 1
    fc2 = reg.add(syn, "conversion > 2%", date(2027, 1, 1))
    assert reg.score(fc2.id, syn, 1, probability=0.7).score.brier == pytest.approx(0.09)
    with pytest.raises(ValueError):
        reg.score(fc2.id, syn, 0.5, probability=0.7)
    s1 = syn.model_copy(update={"grade": "S1"})
    with pytest.raises(ValueError):
        reg.add(s1, "r", date(2027, 1, 1))
    with pytest.raises(ValueError):
        reg.score(fc.id, syn.model_copy(update={"id": "other"}), 1.0)


def test_world_emits_calcs_with_receipts():
    w = generate_world(WorldConfig(seed=1, n_segments=2))
    assert len(w.calcs) == 2 * 4 * 3
    c = w.calcs[0]
    assert c.inputs[0].source_id and c.median == c.inputs[0].value
