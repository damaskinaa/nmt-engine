"""Steps 1-2: classify each trace's context and extract job elements with verbatim spans.

The LLM proposes spans; code keeps only those that occur in the stored source text under the
same whitespace normalisation gate 1 uses. Labels (criterion, alternative names, statements)
are kept as labels, never as evidence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from nmt_engine.llm import LLM, LLMError
from nmt_engine.miner.prompts import (
    CONTEXT_TYPES,
    ELEMENTS,
    EXTRACT_PROMPT,
    EXTRACT_SYSTEM,
    JOB_TYPES,
    LEVELS,
    VALUE_MARKERS,
)
from nmt_engine.schema import Source
from nmt_engine.util import normalize_ws

TRACE_KINDS = ("review", "forum", "qa", "issue")
SPAN_FIELDS = (
    "context",
    "trigger",
    "job",
    "negative_emotions",
    "positive_emotions",
    "higher_goal",
) + VALUE_MARKERS
MAX_CHARS = 3000
MIN_CHARS = 40


@dataclass
class Trace:
    source: Source
    text: str

    @property
    def prompt_text(self) -> str:
        return self.text[:MAX_CHARS]


@dataclass
class JobInstance:
    """One job as evidenced by one trace."""

    source_id: str
    context_type: str
    statement: str
    level: str
    type: str
    order: int | None
    search_query: str | None
    spans: dict[str, list[str]] = field(default_factory=dict)
    criteria: list[tuple[str, str]] = field(default_factory=list)  # (label, verbatim)
    alternatives: list[tuple[str, str]] = field(default_factory=list)  # (name, verbatim)

    def evidenced(self) -> set[str]:
        """Which of the 8 job elements have at least one verified span."""
        out = {k for k in ELEMENTS if self.spans.get(k)}
        if self.criteria:
            out.add("success_criteria")
        if self.alternatives:
            out.add("alternatives")
        return out


@dataclass
class Extraction:
    instances: list[JobInstance]
    context_types: dict[str, str]  # source_id -> context type
    proposed_spans: int = 0
    rejected_spans: int = 0
    failed_batches: int = 0


def verbatim_in(span: str, norm_text: str) -> bool:
    s = normalize_ws(span or "")
    return len(s) >= 3 and s in norm_text


def _choice(value: object, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _order(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _list(v: object) -> list:
    return v if isinstance(v, list) else []


def parse_post(raw: dict, trace: Trace, ex: Extraction) -> None:
    norm = normalize_ws(trace.prompt_text)

    def keep(span: object) -> str | None:
        if not isinstance(span, str) or not span.strip():
            return None
        ex.proposed_spans += 1
        if verbatim_in(span, norm):
            return normalize_ws(span)
        ex.rejected_spans += 1
        return None

    sid = trace.source.id
    ex.context_types[sid] = _choice(raw.get("context_type"), CONTEXT_TYPES, "other")
    for job in _list(raw.get("jobs")):
        if not isinstance(job, dict) or not isinstance(job.get("statement"), str):
            continue
        spans = {}
        for f in SPAN_FIELDS:
            vals = job.get(f) or []
            kept = [k for k in (keep(v) for v in (vals if isinstance(vals, list) else [])) if k]
            if kept:
                spans[f] = list(dict.fromkeys(kept))
        criteria = []
        for item in _list(job.get("success_criteria")):
            if isinstance(item, dict) and isinstance(item.get("label"), str):
                span = keep(item.get("span"))
                if span:
                    criteria.append((item["label"].strip().lower(), span))
        alternatives = []
        for item in _list(job.get("alternatives")):
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                span = keep(item.get("span"))
                if span and item["name"].strip().lower() in span.lower():
                    alternatives.append((item["name"].strip(), span))
        if not (spans or criteria or alternatives):
            continue  # a job with no verified evidence is a hypothesis, not a trace
        q = job.get("search_query")
        ex.instances.append(
            JobInstance(
                source_id=sid,
                context_type=ex.context_types[sid],
                statement=normalize_ws(job["statement"])[:200],
                level=_choice(job.get("level"), LEVELS, "core"),
                type=_choice(job.get("type"), JOB_TYPES, "regular"),
                order=_order(job.get("order")),
                search_query=normalize_ws(q)[:80] if isinstance(q, str) and q.strip() else None,
                spans=spans,
                criteria=criteria,
                alternatives=alternatives,
            )
        )


def batches(traces: list[Trace], size: int) -> Iterable[list[Trace]]:
    for i in range(0, len(traces), size):
        yield traces[i : i + size]


def extract(llm: LLM, traces: list[Trace], category: str, batch_size: int = 8) -> Extraction:
    """Classify + extract for every trace (LLMDisabled propagates so the caller can skip)."""
    ex = Extraction([], {})
    for batch in batches(traces, batch_size):
        posts = "\n\n".join(
            f'<post i="{i}" kind="{t.source.kind}">\n{t.prompt_text}\n</post>'
            for i, t in enumerate(batch)
        )
        prompt = EXTRACT_PROMPT.format(
            category=category,
            context_types=", ".join(CONTEXT_TYPES),
            levels=", ".join(LEVELS),
            job_types=", ".join(JOB_TYPES),
            posts=posts,
        )
        try:
            data = llm.complete_json(prompt, EXTRACT_SYSTEM, purpose="miner.extract")
        except LLMError:
            ex.failed_batches += 1
            continue
        posts_out = data.get("posts") if isinstance(data, dict) else None
        if not isinstance(posts_out, list):
            ex.failed_batches += 1
            continue
        for raw in posts_out:
            i = raw.get("i") if isinstance(raw, dict) else None
            if isinstance(i, int) and 0 <= i < len(batch):
                parse_post(raw, batch[i], ex)
    return ex


def load_traces(run, kinds: tuple[str, ...] = TRACE_KINDS, limit: int | None = None) -> list[Trace]:
    out = []
    for src in sorted(run.sources.values(), key=lambda s: s.id):
        if src.kind not in kinds:
            continue
        text = run.source_text(src)
        if text and len(text.strip()) >= MIN_CHARS:
            out.append(Trace(src, text))
    return out[:limit] if limit else out
