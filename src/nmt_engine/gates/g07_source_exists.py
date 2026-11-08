"""Gate 7: every referenced source exists, is in the retrieval log, and its stored text
matches the recorded sha256."""

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.store import RunData
from nmt_engine.util import sha256_text


@gate(7, "source_exists", "Source exists in retrieval log")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    logged = {(e.source_id, e.url) for e in run.retrieval_log}
    for src in run.sources.values():
        if (src.id, src.url) not in logged:
            findings.append(Finding("source", src.id, f"{src.url} not in retrieval log", "drop"))
            continue
        text = run.source_text(src)
        if text is None:
            findings.append(
                Finding("source", src.id, f"stored text {src.text_path} missing", "drop")
            )
        elif sha256_text(text) != src.sha256:
            findings.append(Finding("source", src.id, "stored text sha256 mismatch", "drop"))
    for claim in run.claims.values():
        for ref in claim.source_refs:
            if ref.source_id not in run.sources:
                findings.append(
                    Finding("claim", claim.id, f"unknown source {ref.source_id}", "drop")
                )
    for calc in run.calcs.values():
        for inp in calc.inputs:
            if inp.source_id and inp.source_id not in run.sources:
                findings.append(Finding("calc", calc.id, f"unknown source {inp.source_id}"))
            if inp.claim_id and inp.claim_id not in run.claims:
                findings.append(Finding("calc", calc.id, f"unknown claim {inp.claim_id}"))
    return findings
