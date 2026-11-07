"""Forecast registry (PROTOCOL §3 principle 5): register S2+ synthetics, score on resolution."""

import math
from datetime import date

from nmt_engine.schema import Forecast, ForecastScore, Synthetic, grade_rank
from nmt_engine.store import Store

NOMINAL = 0.8


class ForecastRegistry:
    """Append-only registry backed by the run store (`forecast.jsonl`)."""

    def __init__(self, store: Store):
        self.store = store

    def all(self) -> dict[str, Forecast]:
        return self.store.current("forecast")  # type: ignore[return-value]

    def add(self, syn: Synthetic, resolution_rule: str, resolve_by: date) -> Forecast:
        if grade_rank(syn.grade) < 2:
            raise ValueError(f"only S2+ synthetics are registered; {syn.id} is {syn.grade}")
        if syn.combined is None:
            raise ValueError(f"synthetic {syn.id} has no combined interval")
        fid = f"F-{len(self.store.history('forecast')) + 1:04d}"
        fc = Forecast(
            id=fid, synthetic_id=syn.id, resolution_rule=resolution_rule, resolve_by=resolve_by
        )
        self.store.append(fc)
        return fc

    def score(
        self, forecast_id: str, syn: Synthetic, outcome: float, probability: float | None = None
    ) -> Forecast:
        """Score against the realised outcome; append the scored revision.

        hit: outcome inside the 80% interval. log_error: ln(outcome / median).
        brier: (p - y)^2 where p is `probability` for a binary forecast (outcome 0/1), else the
        nominal 0.8 interval-coverage probability with y = hit.
        """
        fc = self.all()[forecast_id]
        if fc.synthetic_id != syn.id or syn.combined is None:
            raise ValueError(f"forecast {forecast_id} is not for synthetic {syn.id}")
        lo, hi = syn.combined.interval_80
        hit = lo <= outcome <= hi
        log_error = math.log(outcome / syn.combined.median) if outcome > 0 else None
        if probability is not None:
            if outcome not in (0, 1):
                raise ValueError("binary forecast outcome must be 0 or 1")
            brier = (probability - outcome) ** 2
        else:
            brier = (NOMINAL - hit) ** 2
        scored = fc.model_copy(
            update={
                "rev": fc.rev + 1,
                "outcome": outcome,
                "score": ForecastScore(hit=hit, log_error=log_error, brier=brier),
            }
        )
        self.store.append(scored)
        return scored
