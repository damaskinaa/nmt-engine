"""Cross-model stability and internal validity of the main world (PREREG_v3 amendment 4)."""

from __future__ import annotations

import itertools
import statistics

from scipy.stats import spearmanr

UNUSABLE = 0.5
UNCAPPED = 0.8
PRICE_ORDER = ("none", "price10", "price50")


def _key(r: dict) -> tuple:
    return (r["agent"], r["incumbent"], r["condition"])


def cross_model(rows_by_model: dict[str, list[dict]]) -> dict:
    """ρ = the lowest pairwise Spearman of P(switch) over cells (repeat 0) present for every
    model. ρ < 0.5: unusable (no Q4/Q7 input); 0.5–0.8: capped at S1; ≥ 0.8: no cap."""
    vals = {
        m: {_key(r): r["p_switch"] for r in rows if r.get("repeat", 0) == 0}
        for m, rows in rows_by_model.items()
    }
    cells = sorted(set.intersection(*(set(v) for v in vals.values())))
    pairs = {}
    for a, b in itertools.combinations(sorted(vals), 2):
        rho = spearmanr([vals[a][c] for c in cells], [vals[b][c] for c in cells]).statistic
        pairs[f"{a} vs {b}"] = round(float(rho), 4)
    rho = min(pairs.values())
    verdict = "unusable" if rho < UNUSABLE else ("capped at S1" if rho < UNCAPPED else "no cap")
    return {"cells": len(cells), "pairs": pairs, "rho": rho, "verdict": verdict}


def internal_validity(rows: list[dict]) -> dict:
    """Reported, not a gate: repeat consistency, scale compression, preserved price order."""
    by_cell: dict[tuple, dict[int, float]] = {}
    for r in rows:
        by_cell.setdefault(_key(r), {})[r.get("repeat", 0)] = r["p_switch"]
    diffs = [
        abs(a - b) for reps in by_cell.values() for a, b in itertools.combinations(reps.values(), 2)
    ]
    first = [reps[0] for reps in by_cell.values() if 0 in reps]
    mean_p = {k: statistics.fmean(reps.values()) for k, reps in by_cell.items()}
    pairs = {(a, i) for a, i, _ in mean_p}
    ordered = [
        (a, i)
        for a, i in pairs
        if all((a, i, c) in mean_p for c in PRICE_ORDER)
        and mean_p[(a, i, "none")] <= mean_p[(a, i, "price10")] <= mean_p[(a, i, "price50")]
    ]
    complete = [p for p in pairs if all((*p, c) in mean_p for c in PRICE_ORDER)]
    return {
        "repeat_mad": round(statistics.fmean(diffs), 4) if diffs else None,
        "sd_p_switch": round(statistics.pstdev(first), 4) if len(first) > 1 else None,
        "price_order_preserved": f"{len(ordered)}/{len(complete)}",
    }


def by_condition(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Mean P(stay / consider / switch) per condition, repeat 0."""
    out: dict[str, dict[str, float]] = {}
    for cond in dict.fromkeys(r["condition"] for r in rows):
        rs = [r for r in rows if r["condition"] == cond and r.get("repeat", 0) == 0]
        out[cond] = {
            k: round(statistics.fmean(r[f"p_{k}"] for r in rs), 4)
            for k in ("stay", "consider", "switch")
        }
    return out
