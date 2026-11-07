"""Gate 2: voices = distinct author_hash; <2 voices cannot back a Segment or why_we_win."""

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.store import RunData


def distinct_authors(run: RunData, claim) -> set[str]:
    return {s.author_hash for s in run.claim_sources(claim) if s.author_hash}


def segment_level_claim_ids(run: RunData) -> dict[str, str]:
    """claim_id -> first referencing object (Segment or Strategy.why_we_win)."""
    refs: dict[str, str] = {}
    for seg in run.segments.values():
        for cid in seg.claim_ids:
            refs.setdefault(cid, f"segment {seg.id}")
    for st in run.strategies.values():
        for cid in st.why_we_win.claim_ids:
            refs.setdefault(cid, f"strategy {st.id}.why_we_win")
    return refs


@gate(2, "voices", "Voice count recomputed from distinct authors")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    seg_refs = segment_level_claim_ids(run)
    for claim in run.claims.values():
        if claim.status != "PUBLIC_VOICE":
            continue
        voices = len(distinct_authors(run, claim))
        if claim.voices != voices:
            findings.append(
                Finding(
                    "claim",
                    claim.id,
                    f"declared voices={claim.voices} but distinct authors={voices}",
                    "single_signal" if voices < 2 else "flag",
                )
            )
        if voices < 2 and claim.id in seg_refs:
            findings.append(
                Finding(
                    "claim",
                    claim.id,
                    f"{voices} voice(s) but referenced by {seg_refs[claim.id]}",
                    "single_signal",
                )
            )
    return findings
