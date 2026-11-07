"""Gate 3: a number stated by one author cannot be the sole basis of a Calc input."""

import re

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.store import RunData

_NUM = re.compile(r"\d")


def _kinds_of(run: RunData, ref_id: str) -> set[str]:
    if ref_id in run.claims:
        return {s.kind for s in run.claim_sources(run.claims[ref_id])}
    if ref_id in run.sources:
        return {run.sources[ref_id].kind}
    return set()


@gate(3, "author_numbers", "Author-stated numbers are never sole Calc inputs")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    for calc in run.calcs.values():
        for inp in calc.inputs:
            claim = run.claims.get(inp.claim_id or "")
            if claim is None or claim.status != "PUBLIC_VOICE":
                continue
            authored = [s for s in run.claim_sources(claim) if s.author_hash]
            stated = any(_NUM.search(r.verbatim) for r in claim.source_refs)
            if not authored or not stated:
                continue
            own = {s.kind for s in authored}
            other = set().union(*(_kinds_of(run, c) for c in inp.corroborated_by)) - own
            if not other:
                findings.append(
                    Finding(
                        "calc",
                        calc.id,
                        f"input {inp.name!r} uses author-stated number from {claim.id} "
                        "without corroboration from a different source type",
                    )
                )
    return findings
