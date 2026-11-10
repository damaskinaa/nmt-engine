"""L5 grades and L7 decision (ARCHITECTURE_v3 L7; PREREG_v3 amendment 7 rules 5-6)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from nmt_engine.schema import grade_rank
from nmt_engine.synth.grade import GradeInputs, grade
from nmt_engine.synth.label import QUANTITY_NAMES
from nmt_engine.synth.logform import Z80, to_log

RUNS = 10_000
SEED = 0
CHAIN = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9")
NEED_S3 = ("Q1", "Q2", "Q3", "Q4", "Q7")
P_MIN = 0.6
Q8_P_MIN = 0.8


@dataclass(frozen=True)
class Quantity:
    """One L5 quantity as the ledger holds it. `estimate` is (median, lo80, hi80) or None."""

    q: str
    inputs: GradeInputs
    estimate: tuple[float, float, float] | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def grade(self) -> str:
        return grade(self.inputs)

    def row(self) -> dict:
        return {
            "q": self.q,
            "name": QUANTITY_NAMES[self.q],
            "grade": self.grade,
            "families": sorted(self.inputs.families),
            "estimate": self.estimate,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Targets:
    margin: float = 0.7  # gross margin share
    payback_months: float = 12.0
    annual_revenue: float = 1_000_000.0


def monte_carlo(qs: dict[str, Quantity], t: Targets, n: int = RUNS, seed: int = SEED) -> dict:
    """Fixed-seed draws along the chain: Q1 x Q7 customers paying Q4 a month, serving cost Q5,
    acquisition cost Q6. Q8 (value gap vs the best alternative) is normal, the rest log-normal."""
    rng = np.random.default_rng(seed)

    def draw(q: str) -> np.ndarray:
        med, lo, hi = qs[q].estimate  # type: ignore[misc]
        if q == "Q8":
            return rng.normal(med, (hi - lo) / (2 * Z80), n)
        mu, sd = to_log(med, lo, hi)
        return rng.lognormal(mu, sd, n)

    d = {q: draw(q) for q in ("Q1", "Q4", "Q5", "Q6", "Q7", "Q8")}
    unit = d["Q4"] - d["Q5"]
    margin = unit / d["Q4"]
    payback = np.where(unit > 0, d["Q6"] / np.maximum(unit, 1e-12), np.inf)
    revenue = d["Q1"] * d["Q7"] * d["Q4"] * 12
    return {
        "runs": n,
        "seed": seed,
        "p_margin": float(np.mean(margin >= t.margin)),
        "p_payback": float(np.mean(payback <= t.payback_months)),
        "p_volume": float(np.mean(revenue >= t.annual_revenue)),
        "p_q8_positive": float(np.mean(d["Q8"] > 0)),
    }


def can_run(qs: dict[str, Quantity]) -> list[str]:
    """Quantities that block the Monte Carlo: below S1 or without an estimate (rule 6)."""
    return [q for q in CHAIN if grade_rank(qs[q].grade) < 1 or qs[q].estimate is None]


def validate(qs: dict[str, Quantity], mc: dict | None, red_team_flip: bool | None) -> dict:
    """Synthetic validation, ARCHITECTURE_v3 L7, item by item. Unknown counts as failed."""
    checks = {
        "Q1-Q4 and Q7 at least S3": all(grade_rank(qs[q].grade) >= 3 for q in NEED_S3),
        "the rest at least S2": all(
            grade_rank(qs[q].grade) >= 2 for q in CHAIN if q not in NEED_S3
        ),
        "three probabilities at least 0.6": bool(
            mc and min(mc["p_margin"], mc["p_payback"], mc["p_volume"]) >= P_MIN
        ),
        "Q8 > 0 with p at least 0.8": bool(mc and mc["p_q8_positive"] >= Q8_P_MIN),
        "red team finds no single input that flips the result": red_team_flip is False,
    }
    return {"checks": checks, "validated": all(checks.values())}


def decision(validated: bool, top_evpi: float | None, touch_cost: float) -> str:
    """GO to build only when validated and the top EVPI is below the cheapest market touch."""
    if validated and top_evpi is not None and top_evpi < touch_cost:
        return "GO to build"
    return "NO GO to build: run the cheapest market touch first"
