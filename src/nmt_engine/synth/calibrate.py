"""Per-method-family calibration on a reference class (PROTOCOL §3 principle 3).

bias b = median ln(pred/truth); residuals r = |ln(pred/truth) - b|;
split-conformal q80 = the ceil((n+1)*0.8)-th smallest r;
coverage_loo = share of cases whose truth falls in exp(ln pred - b_-k +/- q80_-k);
passed = n >= 20 and 0.75 <= coverage_loo <= 0.90.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from nmt_engine.schema import BacktestCase, Calibration
from nmt_engine.synth.leakage import LeakageError
from nmt_engine.synth.logform import Z80

MIN_CASES = 20
COVERAGE_BAND = (0.75, 0.90)


@dataclass(frozen=True)
class CalibrationStats:
    """Calibration result; bias and q80 are in natural-log units (dimensionless)."""

    n: int
    bias_log: float
    conformal_q80: float
    coverage_loo: float
    passed: bool


def _bias_q80(log_ratios: np.ndarray) -> tuple[float, float]:
    b = float(np.median(log_ratios))
    r = np.sort(np.abs(log_ratios - b))
    k = math.ceil((len(r) + 1) * 0.8)
    q80 = float(r[k - 1]) if k <= len(r) else math.inf
    return b, q80


def calibrate(pairs: Sequence[tuple[float, float]]) -> CalibrationStats:
    """Calibrate from (predicted, truth) pairs, both positive and in the same unit/period."""
    lr = np.array([math.log(p / t) for p, t in pairs], dtype=float)
    n = len(lr)
    if n < 2:
        raise ValueError("need at least 2 backtest cases")
    b, q80 = _bias_q80(lr)
    hits = 0
    for k in range(n):
        b_k, q_k = _bias_q80(np.delete(lr, k))
        hits += abs(lr[k] - b_k) <= q_k
    coverage = hits / n
    passed = n >= MIN_CASES and COVERAGE_BAND[0] <= coverage <= COVERAGE_BAND[1]
    return CalibrationStats(n, b, q80, coverage, passed)


def calibrated_interval(
    mu: float, sigma: float, bias_log: float = 0.0, q80: float | None = None
) -> tuple[float, float]:
    """Bias-correct a log-form estimate: mu' = mu - b, h = max(q80, 1.2816 sigma). Log units."""
    h = Z80 * sigma if q80 is None else max(q80, Z80 * sigma)
    return mu - bias_log, h


def calibration_record(
    id: str,
    method_family: str,
    reference_class: str,
    as_of_rule: str,
    cases: Sequence[BacktestCase],
    method_id: str | None = None,
    quantity: str | None = None,
    as_of: date | None = None,
) -> Calibration:
    """Build a Calibration record. If `as_of` is given, every case must be dated <= as_of."""
    if as_of is not None:
        late = [c.case for c in cases if c.as_of > as_of]
        if late:
            raise LeakageError(f"backtest cases dated after {as_of}: {late}")
    stats = calibrate([(c.predicted, c.known_outcome) for c in cases])
    return Calibration(
        id=id,
        method_family=method_family,
        method_id=method_id,
        quantity=quantity,
        reference_class=reference_class,
        as_of_rule=as_of_rule,
        backtest_cases=list(cases),
        bias_log_ratio=stats.bias_log,
        conformal_q80=stats.conformal_q80,
        coverage_80=stats.coverage_loo,
        n=stats.n,
        passed=stats.passed,
    )
