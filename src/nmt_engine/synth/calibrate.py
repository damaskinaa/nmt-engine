"""Per-method-family calibration on a reference class (PROTOCOL §3 principle 3).

bias b = median ln(pred/truth); residuals r = |ln(pred/truth) - b|;
split-conformal q80 = the ceil((n+1)*0.8)-th smallest r;
coverage_loo = share of cases whose truth falls in exp(ln pred - b_-k +/- q80_-k);
passed = n >= 20 and 0.75 <= coverage_loo <= 0.90.

Joint reference classes (every family estimates the same cases) also give the error
correlation rho between families and a conformal half-width for the COMBINED estimate:
rho = max(floor, clip(mean pairwise corr of calibrated log errors, 0, 0.95));
combined q80 = the ceil((n+1)*0.8)-th smallest |combined log error| over leave-one-out
triangulations of the reference cases (each held-out case re-fits bias, q80 and rho without it).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from nmt_engine.schema import BacktestCase, Calibration, JointCalibration, JointCase
from nmt_engine.synth.leakage import LeakageError
from nmt_engine.synth.logform import Z80
from nmt_engine.synth.triangulate import DEFAULT_RHO

MIN_CASES = 20
COVERAGE_BAND = (0.75, 0.90)
RHO_MAX = 0.95


@dataclass(frozen=True)
class CalibrationStats:
    """Calibration result; bias and q80 are in natural-log units (dimensionless)."""

    n: int
    bias_log: float
    conformal_q80: float
    coverage_loo: float
    passed: bool


def _conformal_rank(r: np.ndarray) -> float:
    """The ceil((n+1)*0.8)-th smallest of r (inf when n is too small)."""
    k = math.ceil((len(r) + 1) * 0.8)
    return float(np.sort(r)[k - 1]) if k <= len(r) else math.inf


def _bias_q80(log_ratios: np.ndarray) -> tuple[float, float]:
    b = float(np.median(log_ratios))
    return b, _conformal_rank(np.abs(log_ratios - b))


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
    *,
    quantity: str,
    method_id: str | None = None,
    as_of: date | None = None,
) -> Calibration:
    """Build a Calibration record for one family and `quantity` (required: `estimate` ignores
    calibrations for any other quantity). If `as_of` is given, cases must be dated <= as_of."""
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


@dataclass(frozen=True)
class CombinedStats:
    """Joint-reference statistics for a set of families; q80 in natural-log units."""

    families: tuple[str, ...]
    n: int
    rho: float
    rho_estimated: float | None
    q80: float | None
    coverage_loo: float | None


def estimate_rho(residuals: np.ndarray) -> float | None:
    """Mean pairwise correlation of (n, k) calibrated log errors, clipped to [0, RHO_MAX]."""
    n, k = residuals.shape
    if k < 2 or n < 3 or np.any(residuals.std(axis=0) == 0):
        return None
    c = np.corrcoef(residuals, rowvar=False)
    return float(np.clip(c[~np.eye(k, dtype=bool)].mean(), 0.0, RHO_MAX))


def _floored(est: float | None, floor: float) -> float:
    return floor if est is None else max(floor, est)


def combined_stats(
    cases: Sequence[JointCase],
    families: Sequence[str],
    rho_floor: float = DEFAULT_RHO,
    rho_override: float | None = None,
) -> CombinedStats:
    """rho and LOO conformal q80 of the precision-weighted combination of `families`, using
    the reference cases that every one of them estimated."""
    fams = tuple(sorted(set(families)))
    rows = [c for c in cases if all(f in c.predicted for f in fams)]
    n = len(rows)
    if not fams or n < 3:
        return CombinedStats(fams, n, _floored(None, rho_floor), None, None, None)
    lr = np.array([[math.log(c.predicted[f] / c.known_outcome) for f in fams] for c in rows])
    stated = np.zeros_like(lr)
    for i, c in enumerate(rows):
        for j, f in enumerate(fams):
            if f in c.stated_interval_80:
                lo, hi = c.stated_interval_80[f]
                stated[i, j] = (math.log(hi) - math.log(lo)) / (2 * Z80)

    def fit(m: np.ndarray) -> tuple[np.ndarray, np.ndarray, float | None]:
        bq = [_bias_q80(m[:, j]) for j in range(len(fams))]
        b = np.array([x[0] for x in bq])
        q = np.array([x[1] for x in bq])
        return b, q, estimate_rho(m - b)

    _, _, rho_est = fit(lr)
    rho = rho_override if rho_override is not None else _floored(rho_est, rho_floor)
    errs = np.empty(n)
    for i in range(n):
        b, q, r_i = fit(np.delete(lr, i, axis=0))
        sigma = np.maximum(q, Z80 * stated[i]) / Z80
        if not np.all(np.isfinite(sigma)) or np.any(sigma <= 0):
            return CombinedStats(fams, n, rho, rho_est, None, None)
        w = 1.0 / sigma**2
        errs[i] = abs(float(np.sum(w * (lr[i] - b)) / np.sum(w)))
    q80 = _conformal_rank(errs)
    hits = sum(errs[i] <= _conformal_rank(np.delete(errs, i)) for i in range(n))
    return CombinedStats(fams, n, rho, rho_est, q80 if math.isfinite(q80) else None, hits / n)


def joint_calibration(
    id: str,
    quantity: str,
    reference_class: str,
    as_of_rule: str,
    cases: Sequence[JointCase],
    *,
    as_of: date | None = None,
    rho_floor: float = DEFAULT_RHO,
) -> tuple[JointCalibration, dict[str, Calibration]]:
    """Fit every family on the same reference cases, then the combined statistics.

    Families whose calibration did not pass are left out of the pooled set. If none passed,
    all families are pooled with rho = 1, i.e. combining earns no narrowing."""
    ids = [c.case for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("joint reference cases need unique case ids")
    families = sorted({f for c in cases for f in c.predicted})
    cals = {
        f: calibration_record(
            f"{id}-{f}",
            f,
            reference_class,
            as_of_rule,
            [
                BacktestCase(case=c.case, as_of=c.as_of, known_outcome=c.known_outcome, predicted=p)
                for c in cases
                if (p := c.predicted.get(f)) is not None
            ],
            quantity=quantity,
            as_of=as_of,
        )
        for f in families
    }
    passed = [f for f in families if cals[f].passed]
    stats = combined_stats(cases, passed or families, rho_floor, None if passed else 1.0)
    joint = JointCalibration(
        id=id,
        quantity=quantity,
        reference_class=reference_class,
        as_of_rule=as_of_rule,
        cases=list(cases),
        calibration_ids={f: c.id for f, c in cals.items()},
        families=list(stats.families),
        rho=stats.rho,
        rho_estimated=stats.rho_estimated,
        combined_q80=stats.q80,
        combined_coverage_80=stats.coverage_loo,
        n=stats.n,
    )
    return joint, cals
