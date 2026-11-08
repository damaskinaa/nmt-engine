"""EVPI of a go/no-go decision when methods disagree (PROTOCOL §3, §8).

value_if_go(x) = value_per_unit * (x - threshold). The quantity x follows an equal-weight mixture
of the per-method lognormals. EVPI = E[max(0, v)] - max(0, E[v]), computed in closed form.
"""

import math
from collections.abc import Sequence

from scipy.stats import norm


def _partial_mean(mu: float, sigma: float, threshold: float) -> tuple[float, float]:
    """For X ~ LogNormal(mu, sigma): (E[max(0, X - t)], E[X - t])."""
    mean = math.exp(mu + sigma**2 / 2)
    if threshold <= 0:
        return mean - threshold, mean - threshold
    d2 = (mu - math.log(threshold)) / sigma
    return mean * norm.cdf(d2 + sigma) - threshold * norm.cdf(d2), mean - threshold


def evpi_go_no_go(
    components: Sequence[tuple[float, float]], threshold: float, value_per_unit: float = 1.0
) -> float:
    """EVPI in units of value_per_unit * quantity. `components` are (mu, sigma) in log units."""
    if not components:
        raise ValueError("no components")
    if any(s <= 0 for _, s in components):
        raise ValueError("every component needs sigma > 0")
    if value_per_unit <= 0:
        raise ValueError("value_per_unit must be positive (go pays off above the threshold)")
    parts = [_partial_mean(mu, s, threshold) for mu, s in components]
    e_pos = sum(p for p, _ in parts) / len(parts)
    e_val = sum(v for _, v in parts) / len(parts)
    return value_per_unit * (e_pos - max(0.0, e_val))
