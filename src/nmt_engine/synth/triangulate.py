"""Precision-weighted triangulation across different method families (PROTOCOL §3 principle 2).

Same-family estimates are merged first (mean mu', mean sigma') so that repeating a family adds
no information. Then w = 1/sigma'^2, mu_c = sum(w mu')/sum(w),
sigma_c = sqrt(1/sum(w)) * sqrt(1 + (k-1) rho). Any pairwise z > 1.645 -> methods_disagree.
"""

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from nmt_engine.synth.logform import Z80

DEFAULT_RHO = 0.3
Z_DISAGREE = 1.645


@dataclass(frozen=True)
class MethodEstimate:
    """One calibrated method estimate in log units: mu' and sigma' = h / 1.2816."""

    family: str
    mu: float
    sigma: float
    calc_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Triangulation:
    """Combined estimate in log units; `half_width` is the 80% half-width (1.2816 sigma_c)."""

    mu: float
    sigma: float
    families: tuple[MethodEstimate, ...]
    methods_disagree: bool
    max_z: float
    pair_z: dict[tuple[str, str], float] = field(default_factory=dict)

    @property
    def half_width(self) -> float:
        return Z80 * self.sigma

    @property
    def k(self) -> int:
        return len(self.families)


def merge_same_family(estimates: Sequence[MethodEstimate]) -> list[MethodEstimate]:
    """Collapse estimates of one family into a single estimate (mean mu, mean sigma)."""
    groups: dict[str, list[MethodEstimate]] = {}
    for e in estimates:
        groups.setdefault(e.family, []).append(e)
    out = []
    for fam in sorted(groups):
        g = groups[fam]
        out.append(
            MethodEstimate(
                fam,
                sum(e.mu for e in g) / len(g),
                sum(e.sigma for e in g) / len(g),
                tuple(c for e in g for c in e.calc_ids),
            )
        )
    return out


def triangulate(estimates: Sequence[MethodEstimate], rho: float = DEFAULT_RHO) -> Triangulation:
    """Combine method estimates (log units) across families."""
    fams = merge_same_family(estimates)
    if not fams:
        raise ValueError("no estimates to triangulate")
    w = [1.0 / e.sigma**2 for e in fams]
    sw = sum(w)
    mu = sum(wi * e.mu for wi, e in zip(w, fams, strict=True)) / sw
    k = len(fams)
    sigma = math.sqrt(1.0 / sw) * math.sqrt(1.0 + (k - 1) * rho)
    pair_z = {
        (a.family, b.family): abs(a.mu - b.mu) / math.sqrt(a.sigma**2 + b.sigma**2)
        for a, b in itertools.combinations(fams, 2)
    }
    max_z = max(pair_z.values(), default=0.0)
    return Triangulation(mu, sigma, tuple(fams), max_z > Z_DISAGREE, max_z, pair_z)
