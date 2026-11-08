"""Gate 6: segment populations in one geography must not overlap (declared overlap is
subtracted); one size object may not back two segments."""

from collections import defaultdict

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.store import RunData


@gate(6, "double_count", "Segment population double-count guard")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    findings: list[Finding] = []
    by_size: dict[str, list[str]] = defaultdict(list)
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for seg in run.segments.values():
        if seg.size:
            by_size[seg.size].append(seg.id)
        if seg.population:
            groups[(seg.population.geography, seg.population.base_claim_id)].append(seg)
    for size_id, seg_ids in sorted(by_size.items()):
        if len(seg_ids) > 1:
            findings.append(
                Finding("segment", seg_ids[1], f"size {size_id} reused by segments {seg_ids}")
            )
    for (geo, base), segs in sorted(groups.items()):
        ids = {s.id for s in segs}
        # possible double count: shares are ranges, so their upper bounds must fit the base
        total = sum(s.population.share[1] for s in segs)
        # pairwise declared overlaps only: sum - pairwise overlaps is a lower bound on the union
        # (Bonferroni), so triple overlaps can only make the gate miss, never false-fail
        overlap = 0.0
        seen: set[frozenset[str]] = set()
        for s in segs:
            for ov in s.population.declared_overlaps:
                pair = frozenset({s.id, ov.segment_id})
                if ov.segment_id in ids and pair not in seen:
                    seen.add(pair)
                    overlap += ov.share
        if total - overlap > 1.0 + 1e-9:
            findings.append(
                Finding(
                    "segment",
                    sorted(ids)[-1],
                    f"segments {sorted(ids)} in {geo} cover {total - overlap:.2f} of base "
                    f"{base} (>1.0 after subtracting declared overlaps {overlap:.2f})",
                )
            )
    return findings
