"""S0-S4 grading (PROTOCOL §2). Pure function of the evidence facts; never hand-set."""

from dataclasses import dataclass, field

from nmt_engine.schema import Grade


@dataclass(frozen=True)
class GradeInputs:
    """Facts the grade depends on."""

    anchored: bool  # every Calc input has a source/claim receipt and the formula recomputes
    families: frozenset[str] = field(default_factory=frozenset)
    methods_disagree: bool = False
    calibrated_families: frozenset[str] = field(default_factory=frozenset)  # passed Calibration
    forecast_registered: bool = False
    market_touch_in_interval: bool = False


def grade(g: GradeInputs) -> Grade:
    """S0 unanchored; S1 anchored; S2 + >=3 families agreeing; S3 + every family calibrated and a
    forecast registered; S4 + a market touch inside the interval. Disagreement caps at S1."""
    if not g.anchored:
        return "S0"
    if g.methods_disagree or len(g.families) < 3:
        return "S1"
    if not (g.families <= g.calibrated_families and g.forecast_registered):
        return "S2"
    if not g.market_touch_in_interval:
        return "S3"
    return "S4"
