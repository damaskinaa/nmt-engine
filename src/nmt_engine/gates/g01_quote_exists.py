"""Gate 1: every verbatim span exists in the stored source text (whitespace-normalised)."""

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.store import RunData
from nmt_engine.util import normalize_ws


@gate(1, "quote_exists", "Quote exists in stored source text")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    cache: dict[str, str | None] = {}
    for claim in run.claims.values():
        if claim.status != "PUBLIC_VOICE" and "g01_quote_exists" in claim.flags:
            continue  # already demoted and flagged by a previous `nmt gates demote`
        for ref in claim.source_refs:
            src = run.sources.get(ref.source_id)
            if src is None:
                continue  # unknown source ids are gate 7's finding
            if src.id not in cache:
                text = run.source_text(src)
                cache[src.id] = normalize_ws(text) if text is not None else None
            text = cache[src.id]
            if text is None:
                msg = f"source text {src.text_path} missing; span unverifiable"
            elif not ref.verbatim.strip() or normalize_ws(ref.verbatim) not in text:
                msg = f"verbatim not found in {src.id}: {ref.verbatim[:80]!r}"
            else:
                continue
            findings.append(Finding("claim", claim.id, msg, "demote"))
    return findings
