"""Gate 4: recompute every Calc with units and periods; every input needs a receipt."""

import math

import pint

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.store import RunData
from nmt_engine.units import FormulaError, evaluate, quantity, target_unit


@gate(4, "calc_recompute", "Calc recompute with units and periods")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    for calc in run.calcs.values():
        problems: list[str] = []
        for inp in calc.inputs:
            if not (inp.claim_id or inp.source_id):
                problems.append(f"input {inp.name!r} has no claim_id/source_id")
        try:
            names = {i.name: quantity(i.value, i.unit, i.period) for i in calc.inputs}
            result = evaluate(calc.formula, names)
            if not isinstance(result, pint.Quantity):
                result = quantity(float(result), None, None)
            got = result.to(target_unit(calc.unit, calc.period)).magnitude
            if not math.isclose(got, calc.median, rel_tol=cfg.calc_rel_tol, abs_tol=1e-12):
                problems.append(f"median {calc.median} != recomputed {got:.6g}")
        except (pint.DimensionalityError, pint.UndefinedUnitError) as exc:
            problems.append(f"unit/period mismatch: {exc}")
        except (FormulaError, ZeroDivisionError) as exc:
            problems.append(f"formula error: {exc}")
        if calc.interval_80 is not None:
            lo, hi = calc.interval_80
            if not lo <= calc.median <= hi:
                problems.append(f"median {calc.median} outside interval_80 {calc.interval_80}")
        findings.extend(Finding("calc", calc.id, p) for p in problems)
    return findings
