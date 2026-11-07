"""Build a graded Synthetic record from per-method estimates and per-family calibrations."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from nmt_engine.schema import (
    Calc,
    Calibration,
    Combined,
    Forecast,
    MarketTouch,
    Quantity,
    Synthetic,
    SyntheticMethod,
)
from nmt_engine.synth.calibrate import calibrated_interval
from nmt_engine.synth.grade import GradeInputs, grade
from nmt_engine.synth.logform import Z80, from_log, to_log
from nmt_engine.synth.triangulate import DEFAULT_RHO, MethodEstimate, Triangulation, triangulate


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

    The correction applies even when the calibration did not pass (it is still the best
    available error model); `passed` only gates the S3 grade."""
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


def _intervals_overlap(fams: Sequence[MethodEstimate]) -> bool:
    return all(
        abs(a.mu - b.mu) <= Z80 * (a.sigma + b.sigma)
        for i, a in enumerate(fams)
        for b in fams[i + 1 :]
    )


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
    rho: float = DEFAULT_RHO,
) -> tuple[Synthetic, Triangulation]:
    """Calibrate each method, triangulate across families, grade, and return the Synthetic.

    Grade inputs are checked, not trusted: methods are anchored only if each `calc_id` is in
    `calcs` with receipts on every input; a Calibration counts only for its own family and
    `quantity`; `forecast` and `market_touch` count only if their `synthetic_id` is `id`.
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
    tri = triangulate(ests, rho)
    median, lo, hi = from_log(tri.mu, tri.half_width)
    disagree = tri.methods_disagree or not _intervals_overlap(tri.families)
    calibrated = frozenset(f for f, c in calibrations.items() if c.passed)
    touched = market_touch is not None and lo <= market_touch.value <= hi
    g = grade(
        GradeInputs(
            anchored=is_anchored(methods, calcs or {}, quantity),
            families=frozenset(e.family for e in tri.families),
            methods_disagree=disagree,
            calibrated_families=calibrated,
            forecast_registered=forecast is not None,
            market_touch_in_interval=touched,
        )
    )
    used = {e.family for e in tri.families}
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
            )
            for e in tri.families
        ],
        combined=Combined(median=median, interval_80=(lo, hi)),
        unit=unit,
        calibration_ids=[c.id for f, c in sorted(calibrations.items()) if f in used],
        forecast_id=forecast.id if forecast else None,
        market_touch_id=market_touch.id if touched and market_touch else None,
        methods_disagree=disagree,
    )
    return syn, tri
