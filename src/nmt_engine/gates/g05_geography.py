"""Gate 5: a Calc never mixes geographies unless it is an explicit conversion step."""

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.store import RunData


def input_geography(run: RunData, claim_id: str | None, source_id: str | None) -> str | None:
    if claim_id and claim_id in run.claims:
        return run.claims[claim_id].geography
    if source_id and source_id in run.sources:
        return run.sources[source_id].geography
    return None


@gate(5, "geography", "Geography separation in Calcs")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    for calc in run.calcs.values():
        if calc.geo_conversion:
            continue
        for inp in calc.inputs:
            geo = input_geography(run, inp.claim_id, inp.source_id)
            if geo is not None and geo != calc.geography:
                findings.append(
                    Finding(
                        "calc",
                        calc.id,
                        f"input {inp.name!r} geography {geo} != calc geography {calc.geography}",
                    )
                )
    return findings
