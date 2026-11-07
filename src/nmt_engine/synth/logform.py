"""Log-space representation of a (median, 80% interval) estimate."""

import math

Z80 = 1.2816  # standard-normal quantile for a central 80% interval


def to_log(median: float, lo: float, hi: float) -> tuple[float, float]:
    """(median, lo, hi) in any positive unit -> (mu, sigma) in natural-log units.

    mu = ln(median); sigma = (ln hi - ln lo) / (2 * 1.2816).
    """
    if min(median, lo, hi) <= 0:
        raise ValueError("log form needs positive median and interval")
    if not lo <= median <= hi:
        raise ValueError(f"median {median} outside interval [{lo}, {hi}]")
    return math.log(median), (math.log(hi) - math.log(lo)) / (2 * Z80)


def from_log(mu: float, half_width: float) -> tuple[float, float, float]:
    """(mu, half-width h in log units) -> (median, lo, hi) in the original unit."""
    return math.exp(mu), math.exp(mu - half_width), math.exp(mu + half_width)
