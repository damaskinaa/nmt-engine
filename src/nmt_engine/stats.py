"""Small interval and agreement statistics shared by the auditor and the gold-set gate."""

from __future__ import annotations

import math
from collections.abc import Sequence

Z80 = 1.2815515655446004  # standard-normal quantile, 80% two-sided
Z95 = 1.959964  # standard-normal quantile, 95% two-sided


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(max(0.0, mid - half), 6), round(min(1.0, mid + half), 6))


def agreement(a: Sequence, b: Sequence) -> float:
    """Share of positions where two label lists agree (0.0 for empty lists)."""
    if not a:
        return 0.0
    return round(sum(x == y for x, y in zip(a, b, strict=True)) / len(a), 4)


def precision(pred: Sequence, gold: Sequence, positive) -> tuple[int, int]:
    """(true positives, predicted positives) for one class; pairs with a None side are skipped."""
    pairs = [(p, g) for p, g in zip(pred, gold, strict=True) if p is not None and g is not None]
    called = [g for p, g in pairs if p == positive]
    return sum(g == positive for g in called), len(called)


def cohen_kappa(a: Sequence, b: Sequence) -> float | None:
    """Cohen's kappa for two raters over the same items; None when chance agreement is 1."""
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((list(a).count(c) / n) * (list(b).count(c) / n) for c in set(a) | set(b))
    return None if pe == 1 else round((po - pe) / (1 - pe), 4)
