"""Build a graded Synthetic record from per-method estimates and per-family calibrations."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from nmt_engine.schema import (
    Calc,
    Calibration,
    Combined,
    Forecast,
    JointCalibration,
    MarketTouch,
    Quantity,
    Synthetic,
    SyntheticMethod,
)
from nmt_engine.synth.calibrate import calibrated_interval, combined_stats
from nmt_engine.synth.grade import GradeInputs, grade
from nmt_engine.synth.logform import Z80, from_log, to_log
from nmt_engine.synth.triangulate import (
    DEFAULT_RHO,
    MethodEstimate,
    Triangulation,
    merge_same_family,
    triangulate,
)


@dataclass(frozen=True)
class MethodInput:
    """One method's raw (uncalibrated) estimate in the quantity's unit."""

    family: str
    calc_id: str
    median: float
    lo: float
    hi: float


def calibrated_estimate(m: MethodInput, cal: Calibration | None) -> MethodEstimate:
    """Apply the family's calibration (bias, conformal q80) if any; else use as stated.

    `estimate` leaves families whose calibration did not pass out of the combination."""
    mu, sigma = to_log(m.median, m.lo, m.hi)
    if cal is not None and cal.conformal_q80 is not None:
        mu, h = calibrated_interval(mu, sigma, cal.bias_log_ratio or 0.0, cal.conformal_q80)
    else:
        h = Z80 * sigma
    return MethodEstimate(m.family, mu, h / Z80, (m.calc_id,))


def is_anchored(
    methods: Sequence[MethodInput], calcs: Mapping[str, Calc], quantity: Quantity
) -> bool:
    """Every method cites a stored Calc for this quantity, family and median whose inputs all
    carry a source or claim receipt."""
    for m in methods:
        calc = calcs.get(m.calc_id)
        if calc is None or not calc.inputs:
            return False
        if calc.quantity != quantity or calc.method_family != m.family:
            return False
        if not math.isclose(calc.median, m.median, rel_tol=1e-9):
            return False
        if any(not (i.source_id or i.claim_id) for i in calc.inputs):
            return False
    return bool(methods)


def _same_prediction(fc: Forecast, median: float, lo: float, hi: float) -> bool:
    if fc.median is None or fc.interval_80 is None:
        return False
    pairs = ((fc.median, median), (fc.interval_80[0], lo), (fc.interval_80[1], hi))
    return all(math.isclose(a, b, rel_tol=1e-9) for a, b in pairs)


def _intervals_overlap(fams: Sequence[MethodEstimate]) -> bool:
    return all(
        abs(a.mu - b.mu) <= Z80 * (a.sigma + b.sigma)
        for i, a in enumerate(fams)
        for b in fams[i + 1 :]
    )


def _usable_joint(
    joint: JointCalibration | None,
    quantity: Quantity,
    calibrations: Mapping[str, Calibration],
    families: set[str],
) -> JointCalibration | None:
    if joint is None or joint.quantity != quantity:
        return None
    ok = all(
        f in calibrations and joint.calibration_ids.get(f) == calibrations[f].id for f in families
    )
    return joint if ok else None


def estimate(
    id: str,
    quantity: Quantity,
    geography: str,
    methods: Sequence[MethodInput],
    calibrations: Mapping[str, Calibration] | None = None,
    *,
    calcs: Mapping[str, Calc] | None = None,
    forecast: Forecast | None = None,
    market_touch: MarketTouch | None = None,
    segment_id: str | None = None,
    unit: str | None = None,
    rho: float | None = None,
    joint: JointCalibration | None = None,
) -> tuple[Synthetic, Triangulation]:
    """Calibrate each method, triangulate across families, grade, and return the Synthetic.

    Only families with a passed calibration are pooled; the rest stay listed with
    `in_combined=False`. If none passed, every family is pooled with rho = 1 so combining earns
    no narrowing. With a matching `joint` calibration, rho is estimated from its residuals
    (floored at DEFAULT_RHO) and the combined half-width is max(analytic, LOO conformal q80);
    without one rho = DEFAULT_RHO. An explicit `rho` overrides either.

    Grade inputs are checked, not trusted: methods are anchored only if each `calc_id` is in
    `calcs` with receipts on every input; a Calibration counts only for its own family and
    `quantity`; `forecast` and `market_touch` count only if their `synthetic_id` is `id`, and the
    forecast only if its frozen median and interval equal this estimate's.
    `market_touch.value` must be in the quantity's unit and land inside the 80% interval.
    """
    calibrations = {
        f: c
        for f, c in (calibrations or {}).items()
        if c.method_family == f and c.quantity == quantity
    }
    if forecast is not None and forecast.synthetic_id != id:
        forecast = None
    if market_touch is not None and market_touch.synthetic_id != id:
        market_touch = None
    ests = [calibrated_estimate(m, calibrations.get(m.family)) for m in methods]
    passed = {f for f, c in calibrations.items() if c.passed}
    pooled = [e for e in ests if e.family in passed]
    if not pooled:
        pooled, rho_default = ests, 1.0
    else:
        rho_default = DEFAULT_RHO
    fams = {e.family for e in pooled}
    joint = _usable_joint(joint, quantity, calibrations, fams)
    q80: float | None = None
    if joint is not None and rho is None and sorted(fams) == sorted(joint.families):
        rho_used, q80 = joint.rho, joint.combined_q80
    elif joint is not None:
        override = rho if rho is not None else (1.0 if rho_default == 1.0 else None)
        stats = combined_stats(joint.cases, sorted(fams), DEFAULT_RHO, override)
        rho_used, q80 = stats.rho, stats.q80
    else:
        rho_used = rho if rho is not None else rho_default
    tri = triangulate(pooled, rho_used)
    median, lo, hi = from_log(tri.mu, max(tri.half_width, q80 or 0.0))
    disagree = tri.methods_disagree or not _intervals_overlap(tri.families)
    if forecast is not None and not _same_prediction(forecast, median, lo, hi):
        forecast = None  # registered for an earlier revision of this estimate
    calibrated = frozenset(passed & fams)
    touched = market_touch is not None and lo <= market_touch.value <= hi
    g = grade(
        GradeInputs(
            anchored=is_anchored(methods, calcs or {}, quantity),
            families=frozenset(fams),
            methods_disagree=disagree,
            calibrated_families=calibrated,
            forecast_registered=forecast is not None,
            market_touch_in_interval=touched,
        )
    )
    dropped = merge_same_family([e for e in ests if e.family not in fams])
    syn = Synthetic(
        id=id,
        quantity=quantity,
        segment_id=segment_id,
        geography=geography,
        grade=g,
        methods=[
            SyntheticMethod(
                family=e.family,
                calc_id=",".join(e.calc_ids),
                interval_80=(math.exp(e.mu - Z80 * e.sigma), math.exp(e.mu + Z80 * e.sigma)),
                in_combined=e.family in fams,
            )
            for e in sorted((*tri.families, *dropped), key=lambda e: e.family)
        ],
        combined=Combined(median=median, interval_80=(lo, hi)),
        unit=unit,
        calibration_ids=[c.id for f, c in sorted(calibrations.items()) if f in fams],
        joint_calibration_id=joint.id if joint else None,
        rho=rho_used,
        combined_conformal_q80=q80,
        forecast_id=forecast.id if forecast else None,
        market_touch_id=market_touch.id if touched and market_touch else None,
        methods_disagree=disagree,
    )
    return syn, tri
