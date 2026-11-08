"""Mandatory citation label (PROTOCOL §2). Always generated from records, never hand-written."""

import math
from collections.abc import Mapping

from nmt_engine.schema import Calibration, Forecast, Synthetic, grade_rank

QUANTITY_NAMES = {
    "Q1": "reachable segment count",
    "Q2": "job frequency",
    "Q3": "job budget",
    "Q4": "WTP",
    "Q5": "cost-to-serve",
    "Q6": "CAC",
    "Q7": "adoption",
    "Q8": "value gap",
    "Q9": "retention",
}


def _num(x: float) -> str:
    if x == 0:
        return "0"
    digits = max(0, 2 - int(math.floor(math.log10(abs(x)))))
    return f"{round(x, digits):,.{digits}f}" if digits else f"{round(x, digits):,.0f}"


def citation_label(
    syn: Synthetic,
    calibrations: Mapping[str, Calibration] | None = None,
    forecasts: Mapping[str, Forecast] | None = None,
) -> str:
    """e.g. `Q4 WTP, segment SEG1: 20–35 EUR/month (80% conformal interval), median 27 ·
    SYNTHETIC S3 · methods: revealed_price, statistical, supply · backtest n=24, coverage 79%,
    bias ×0.95 corrected · forecast F1 resolves 2027-06-30`."""
    # `estimate` always fills combined.interval_80; hand-built records may not
    if syn.combined is None or syn.combined.interval_80 is None:
        raise ValueError(f"synthetic {syn.id} has no combined estimate")
    lo, hi = syn.combined.interval_80
    unit = f" {syn.unit}" if syn.unit else ""
    seg = f", segment {syn.segment_id}" if syn.segment_id else ""
    kind = "80% conformal interval" if grade_rank(syn.grade) >= 3 else "80% interval"
    parts = [
        f"{syn.quantity} {QUANTITY_NAMES[syn.quantity]}{seg}: {_num(lo)}–{_num(hi)}{unit} "
        f"({kind}), median {_num(syn.combined.median)}",
        f"SYNTHETIC {syn.grade}" + (" (not citable)" if grade_rank(syn.grade) < 3 else ""),
        "methods: " + ", ".join(sorted({m.family for m in syn.methods if m.in_combined})),
    ]
    if left_out := sorted({m.family for m in syn.methods if not m.in_combined}):
        parts.append("not pooled (calibration failed): " + ", ".join(left_out))
    cals = [c for i in syn.calibration_ids if (c := (calibrations or {}).get(i))]
    if cals:
        n = min(c.n for c in cals)
        cov = min(c.coverage_80 or 0.0 for c in cals)
        bias = ", ".join(
            f"{c.method_family} ×{math.exp(c.bias_log_ratio or 0.0):.2f}" for c in cals
        )
        parts.append(f"backtest n≥{n}, coverage≥{cov:.0%}, bias {bias} corrected")
    if syn.methods_disagree:
        parts.append("methods disagree")
    fc = (forecasts or {}).get(syn.forecast_id or "")
    if fc is not None:
        parts.append(
            f"forecast {fc.id} resolves {fc.resolve_by.isoformat()} ({fc.resolution_rule})"
        )
    return " · ".join(parts)
