"""Merge job instances into Jobs and write Claims/Jobs with receipts.

A Job is one goal evidenced across traces. Instances are grouped deterministically by statement
token overlap, then (optionally) the LLM groups the remaining near-duplicates by meaning. Each of
the 8 elements becomes one PUBLIC_VOICE claim whose receipts are every verified span for it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from nmt_engine.llm import LLM, LLMDisabled, LLMError
from nmt_engine.miner.extract import JobInstance
from nmt_engine.miner.prompts import ELEMENTS, MERGE_PROMPT, MERGE_SYSTEM, VALUE_MARKERS
from nmt_engine.schema import Claim, Job, Source, SourceRef, SuccessCriterion
from nmt_engine.util import sha256_text

_STOP_WORDS = (
    "i a an the to of for and or my our me we with in on at by from into about as it is be "
    "that this want wants need needs some any all can so"
)
_STOP = frozenset(_STOP_WORDS.split())
MAX_REFS = 50


def tokens(statement: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", statement.lower())
    out = set()
    for w in words:
        if w in _STOP or len(w) < 2:
            continue
        for suf in ("ing", "es", "ed", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)]
                break
        out.add(w)
    return frozenset(out)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


@dataclass
class JobGroup:
    statement: str
    instances: list[JobInstance] = field(default_factory=list)

    @property
    def toks(self) -> frozenset[str]:
        return tokens(self.statement)


def group_instances(instances: list[JobInstance], threshold: float = 0.5) -> list[JobGroup]:
    groups: list[JobGroup] = []
    for inst in sorted(instances, key=lambda i: (i.statement.lower(), i.source_id)):
        t = tokens(inst.statement)
        best, score = None, threshold
        for g in groups:
            s = jaccard(t, g.toks)
            if s >= score:
                best, score = g, s
        if best is None:
            groups.append(JobGroup(inst.statement, [inst]))
        else:
            best.instances.append(inst)
    for g in groups:
        g.statement = Counter(i.statement for i in g.instances).most_common(1)[0][0]
    return groups


def llm_merge(llm: LLM, groups: list[JobGroup], category: str, chunk: int = 150) -> list[JobGroup]:
    """Let the LLM merge groups that are the same job in different words (labels only)."""
    parent = list(range(len(groups)))
    names: dict[int, str] = {}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(
        range(len(groups)), key=lambda i: (-len(groups[i].instances), groups[i].statement)
    )
    for start in range(0, len(order), chunk):
        ids = order[start : start + chunk]
        items = "\n".join(f"{i}: {groups[i].statement}" for i in ids)
        try:
            data = llm.complete_json(
                MERGE_PROMPT.format(category=category, items=items),
                MERGE_SYSTEM,
                purpose="miner.merge",
            )
        except (LLMDisabled, LLMError):
            continue
        found = data.get("groups") if isinstance(data, dict) else None
        for g in found if isinstance(found, list) else []:
            raw_ids = g.get("ids") if isinstance(g, dict) else None
            members = [
                i
                for i in (raw_ids if isinstance(raw_ids, list) else [])
                if isinstance(i, int) and i in ids
            ]
            if len(members) < 2:
                continue
            root = find(members[0])
            for m in members[1:]:
                parent[find(m)] = root
            if isinstance(g.get("statement"), str):
                names[root] = g["statement"].strip()
    merged: dict[int, JobGroup] = {}
    for i in order:
        r = find(i)
        if r not in merged:
            merged[r] = JobGroup(names.get(r, groups[r].statement))
        merged[r].instances += groups[i].instances
    for r, g in merged.items():
        if r not in names:
            g.statement = Counter(i.statement for i in g.instances).most_common(1)[0][0]
    return sorted(merged.values(), key=lambda g: (-len(g.instances), g.statement))


@dataclass
class BuiltJob:
    job: Job
    claims: dict[str, Claim]  # element -> claim (8 elements + value markers + statement)
    group: JobGroup
    kinds: set[str]
    voices: int
    freq: float | None = None  # search volume (proxy), when available
    value: float | None = None  # CPC (proxy), when available

    def evidenced(self) -> set[str]:
        return {e for e in ELEMENTS if e in self.claims}


def _claim(
    cid: str,
    label: str,
    statement: str,
    refs: list[SourceRef],
    sources: dict[str, Source],
    geo: str,
) -> Claim:
    srcs = [sources[r.source_id] for r in refs]
    kinds = sorted({s.kind for s in srcs})
    voices = len({s.author_hash for s in srcs if s.author_hash})
    return Claim(
        id=cid,
        text=f"{label} for job '{statement}': \"{refs[0].verbatim[:160]}\"",
        status="PUBLIC_VOICE",
        voices=voices,
        source_types=kinds,
        source_refs=refs,
        geography=geo,
        single_signal=voices < 2 or len(kinds) < 2,
        stage="S4",
    )


def _refs(
    pairs: list[tuple[str, str]], locator: str, sources: dict[str, Source]
) -> list[SourceRef]:
    """Unique receipts, round-robin across source kinds so the cap keeps every kind."""
    seen: set[tuple[str, str]] = set()
    by_kind: dict[str, list[SourceRef]] = defaultdict(list)
    for sid, span in pairs:
        if (sid, span) in seen:
            continue
        seen.add((sid, span))
        by_kind[sources[sid].kind].append(SourceRef(source_id=sid, verbatim=span, locator=locator))
    queues = [by_kind[k] for k in sorted(by_kind)]
    out: list[SourceRef] = []
    for i in range(max((len(q) for q in queues), default=0)):
        out += [q[i] for q in queues if i < len(q)]
    return out[:MAX_REFS]


def build_job(group: JobGroup, sources: dict[str, Source], geo: str) -> BuiltJob:
    jid = "job_" + sha256_text(group.statement.lower())[:12]
    insts = group.instances
    per_field: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for inst in insts:
        for f, spans in inst.spans.items():
            per_field[f] += [(inst.source_id, s) for s in spans]
        per_field["success_criteria"] += [(inst.source_id, s) for _, s in inst.criteria]
        per_field["alternatives"] += [(inst.source_id, s) for _, s in inst.alternatives]
    claims: dict[str, Claim] = {}
    for f in (*ELEMENTS, *VALUE_MARKERS):
        refs = _refs(per_field.get(f, []), f, sources)
        if refs:
            label = f.replace("_", " ")
            claims[f] = _claim(f"c_{jid}_{f}", label, group.statement, refs, sources, geo)
    srcs = [sources[i.source_id] for i in insts]
    kinds = {s.kind for s in srcs}
    voices = len({s.author_hash for s in srcs if s.author_hash})
    crit = Counter(label for i in insts for label, _ in i.criteria)
    alts = Counter(name for i in insts for name, _ in i.alternatives)
    first = {f: (per_field[f][0][1] if per_field.get(f) else None) for f in ELEMENTS}
    thin = voices < 2 or len(kinds) < 2
    job = Job(
        id=jid,
        statement=group.statement,
        level=Counter(i.level for i in insts).most_common(1)[0][0],
        context=first["context"],
        trigger=first["trigger"],
        negative_emotions=[s for _, s in per_field.get("negative_emotions", [])][:5],
        consideration_set=[n for n, _ in sorted(alts.items(), key=lambda kv: (-kv[1], kv[0]))],
        expected_outcome=first["success_criteria"],
        success_criteria=[
            SuccessCriterion(criterion=label, priority_rank=rank)
            for rank, (label, _) in enumerate(
                sorted(crit.items(), key=lambda kv: (-kv[1], kv[0])), start=1
            )
        ],
        positive_emotions=[s for _, s in per_field.get("positive_emotions", [])][:5],
        type=Counter(i.type for i in insts).most_common(1)[0][0],
        claim_ids=[c.id for c in claims.values() if thin or not c.single_signal],
        thin=thin,
    )
    return BuiltJob(job, claims, group, kinds, voices)
