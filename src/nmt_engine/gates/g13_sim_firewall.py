"""Gate 13: graded simulation firewall.

- S0 (SIMULATED, or SYNTHETIC_ESTIMATE grade S0) never referenced by Segment, why_we_win,
  go/no-go or a Calc input.
- Monte Carlo inputs that are synthetic must be >= S2.
- Segment / why_we_win / go/no-go synthetic references must be >= S3.
- A Synthetic graded >= S3 needs >= 3 method families, a passed Calibration (n >= 20,
  coverage >= 0.75) and a registered Forecast; S4 also needs a MarketTouch.
"""

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.schema import grade_rank
from nmt_engine.store import RunData


def _grade(run: RunData, claim_id: str) -> int | None:
    """Simulation grade of a claim (0..4) or None when it is not simulated/synthetic."""
    c = run.claims.get(claim_id)
    if c is None:
        return None
    if c.status == "SIMULATED":
        return 0
    if c.status == "SYNTHETIC_ESTIMATE":
        return grade_rank(c.grade)
    return None


@gate(13, "sim_firewall", "Graded simulation firewall")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    strong_refs: list[tuple[str, str, str]] = []
    for seg in run.segments.values():
        strong_refs += [("segment", seg.id, cid) for cid in seg.claim_ids]
    for st in run.strategies.values():
        strong_refs += [("strategy", st.id, cid) for cid in st.why_we_win.claim_ids]
        strong_refs += [("strategy", st.id, cid) for cid in st.go_no_go_claim_ids]
    for typ, oid, cid in strong_refs:
        g = _grade(run, cid)
        if g is not None and g < 3:
            findings.append(Finding(typ, oid, f"references {cid} at S{g}; S3+ required"))
    for calc in run.calcs.values():
        for inp in calc.inputs:
            g = _grade(run, inp.claim_id or "")
            if g == 0:
                findings.append(Finding("calc", calc.id, f"input {inp.name!r} is S0"))
    for sim in run.sim_runs.values():
        if sim.model != "montecarlo":
            continue
        for cid in sim.inputs:
            g = _grade(run, cid)
            if g is not None and g < 2:
                findings.append(Finding("sim_run", sim.id, f"MC input {cid} at S{g}; S2+ needed"))
    for syn in run.synthetics.values():
        rank = grade_rank(syn.grade)
        if rank < 3:
            continue
        problems = []
        if len({m.family for m in syn.methods}) < 3:
            problems.append("fewer than 3 method families")
        cals = [run.calibrations.get(c) for c in syn.calibration_ids]
        ok = [c for c in cals if c and c.passed and c.n >= 20 and (c.coverage_80 or 0) >= 0.75]
        if not ok:
            problems.append("no passed Calibration (n>=20, coverage>=0.75)")
        if not syn.forecast_id or syn.forecast_id not in run.forecasts:
            problems.append("no registered Forecast")
        if rank >= 4 and (not syn.market_touch_id or syn.market_touch_id not in run.market_touches):
            problems.append("S4 without MarketTouch")
        findings += [Finding("synthetic", syn.id, f"grade {syn.grade}: {p}") for p in problems]
    for claim in run.claims.values():
        if claim.status == "SYNTHETIC_ESTIMATE" and claim.synthetic_id:
            syn = run.synthetics.get(claim.synthetic_id)
            if syn is None or grade_rank(syn.grade) < grade_rank(claim.grade):
                findings.append(
                    Finding("claim", claim.id, f"grade {claim.grade} exceeds its Synthetic")
                )
    return findings
