"""Gate 11: Segment and Job-graph-node claims need >=2 customer-voice evidence families AND >=2
authors; declared source_types and single_signal must match the sources.

Families, not platform kinds: Hacker News and Reddit are both `discussion`, while vendor pages,
change history, search demand and market records are not customer voice and add nothing."""

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.gates.g02_voices import distinct_authors
from nmt_engine.schema import voice_families
from nmt_engine.store import RunData


def node_claim_ids(run: RunData) -> dict[str, str]:
    refs: dict[str, str] = {}
    for seg in run.segments.values():
        if not seg.thin:
            for cid in seg.claim_ids:
                refs.setdefault(cid, f"segment {seg.id}")
    for job in run.jobs.values():
        if not job.thin:
            for cid in job.claim_ids:
                refs.setdefault(cid, f"job {job.id}")
    return refs


@gate(11, "diversity", "Source-type diversity for segment/graph-node claims")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    refs = node_claim_ids(run)
    for claim in run.claims.values():
        if claim.status != "PUBLIC_VOICE":
            continue
        kinds = {s.kind for s in run.claim_sources(claim)}
        families = voice_families(run.claim_sources(claim))
        authors = distinct_authors(run, claim)
        if set(claim.source_types) - kinds:
            findings.append(
                Finding(
                    "claim",
                    claim.id,
                    f"declared source_types {sorted(claim.source_types)} not backed by "
                    f"sources {sorted(kinds)}",
                )
            )
        single = len(authors) < 2 or len(families) < 2
        if single and not claim.single_signal:
            findings.append(
                Finding("claim", claim.id, "single signal not flagged", "single_signal")
            )
        if claim.id in refs and single:
            findings.append(
                Finding(
                    "claim",
                    claim.id,
                    f"{len(families)} customer-voice famil(ies), {len(authors)} author(s) but "
                    f"used by "
                    f"{refs[claim.id]}",
                    "single_signal",
                )
            )
    return findings
