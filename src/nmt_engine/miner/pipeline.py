"""`nmt mine`: traces -> jobs -> segments -> economic job graph -> gates -> graph.html/report.html.

Numbers in the outputs are counts and formulas computed here from stored data, or proxy metrics
copied from a source payload; the LLM only proposes spans and labels.
"""

from __future__ import annotations

import json
import time
import warnings
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from nmt_engine.gates import GateConfig, demote, run_gates, write_reports
from nmt_engine.gates.g09_manifest import manifest_hash
from nmt_engine.graph import score
from nmt_engine.graph.viewer import write_graph_html, write_report_html
from nmt_engine.llm import LLM, LLMDisabled, model_family
from nmt_engine.miner import prompts
from nmt_engine.miner.extract import extract, load_traces
from nmt_engine.miner.graph_build import build_edges, segments
from nmt_engine.miner.jobs import BuiltJob, build_job, group_instances, llm_merge
from nmt_engine.schema import Claim, FrozenFile, Record, RunManifest, SourceRef
from nmt_engine.store import RunData, Store, load_run, type_name
from nmt_engine.util import sha256_file, sha256_text

KILL_ELEMENTS = 4
KILL_KINDS = 2
KILL_LINE = 0.30


def write_prompts(run_dir: Path) -> list[Path]:
    d = run_dir / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for name in ("EXTRACT_SYSTEM", "EXTRACT_PROMPT", "MERGE_SYSTEM", "MERGE_PROMPT"):
        p = d / f"{name.lower()}.txt"
        p.write_text(getattr(prompts, name), "utf-8")
        out.append(p)
    return out


def write_manifest(run_dir: Path, frozen: list[Path], seed: int, vendor: str | None) -> None:
    files = [
        FrozenFile(path=str(p.relative_to(run_dir)), sha256=sha256_file(p)) for p in sorted(frozen)
    ]
    path = run_dir / "run_manifest.json"
    mine_owned = {
        "stage": "S4",
        "seed": seed,
        "created_at": datetime.now(UTC),
        "frozen": files,
        "manifest_sha256": manifest_hash(files),
        "model_vendor": vendor,
    }
    if path.is_file():
        m = RunManifest.model_validate_json(path.read_text("utf-8")).model_copy(update=mine_owned)
    else:
        m = RunManifest(run_id=run_dir.name, **mine_owned)
    path.write_text(m.model_dump_json(indent=2), "utf-8")


MINED_TYPES = ("claim", "job", "edge", "segment")


def replace_mined(store: Store, records: list[Record], ledger: Path) -> None:
    """Write this mine's records as the newest revisions and retract records that an earlier
    mine of the same run wrote (listed in `ledger`) but this one no longer produces. Records
    from anything other than `mine` are never touched."""
    previous = json.loads(ledger.read_text("utf-8")) if ledger.is_file() else {}
    new: dict[str, list[Record]] = {t: [] for t in MINED_TYPES}
    for r in records:
        new[type_name(r)].append(r)
    for t in MINED_TYPES:
        top: dict[str, int] = {}
        for r in store.history(t):
            top[r.id] = max(top.get(r.id, -1), r.rev)
        ids = {r.id for r in new[t]}
        out = [r.model_copy(update={"rev": top[r.id] + 1}) if r.id in top else r for r in new[t]]
        current = store.current(t)
        for i in sorted(set(previous.get(t, [])) - ids):
            if i in current:
                out.append(current[i].model_copy(update={"rev": top[i] + 1, "retracted": True}))
        store.append_many(out)
    ledger.write_text(
        json.dumps({t: sorted(r.id for r in new[t]) for t in MINED_TYPES}, indent=1), "utf-8"
    )


def search_proxies(run_dir: Path, built: list[BuiltJob], geo: str) -> list[Claim]:
    """Search volume (frequency proxy) and CPC (commercial-value proxy) per job, from DataForSEO
    when credentials are set. Returns PROXY_METRIC claims; sets weights on the BuiltJobs."""
    from nmt_engine.collect import dataforseo
    from nmt_engine.collect.base import Collector, MissingKeyError, env

    if not all(env(k) for k in ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "NMT_AUTHOR_SALT")):
        return []
    queries: dict[str, str] = {}
    for b in built:
        qs = [i.search_query for i in b.group.instances if i.search_query]
        queries[b.job.id] = (max(sorted(set(qs)), key=qs.count) if qs else b.job.statement)[
            :80
        ].lower()
    c = Collector(run_dir, geo=geo, salt=env("NMT_AUTHOR_SALT"))
    try:
        df = dataforseo.search_volume(c, sorted(set(queries.values())), geo)
    except (MissingKeyError, httpx.HTTPError, KeyError, ValueError) as exc:
        warnings.warn(f"search proxies skipped, using voice weights: {exc!r}", stacklevel=2)
        return []
    claims = []
    if df.empty:
        return claims
    first = df.drop_duplicates("keyword").set_index("keyword")
    for b in built:
        q = queries[b.job.id]
        if q not in first.index:
            continue
        row = first.loc[q]
        for metric in ("search_volume", "cpc"):
            v = row[metric]
            if v is None or v != v:
                continue
            if metric == "search_volume":
                b.freq = float(v)
            else:
                b.value = float(v)
            claims.append(
                Claim(
                    id=f"c_{b.job.id}_{metric}",
                    text=f"{metric} for '{q}' ({geo}): proxy for job '{b.job.statement}'",
                    status="PROXY_METRIC",
                    source_types=["search"],
                    source_refs=[SourceRef(source_id=row["source_id"], verbatim=q)],
                    geography=geo,
                )
            )
    return claims


def evidence_table(run: RunData, job_ids: set[str] | None = None) -> list[dict]:
    """Per job, after gates: which of the 8 elements keep a live PUBLIC_VOICE receipt."""
    rows = []
    for job in sorted(run.jobs.values(), key=lambda j: j.id):
        if job.retracted or (job_ids is not None and job.id not in job_ids):
            continue
        elements, kinds = [], set()
        for el in prompts.ELEMENTS:
            c = run.claims.get(f"c_{job.id}_{el}")
            if c is None or c.retracted or c.status != "PUBLIC_VOICE" or not c.source_refs:
                continue
            srcs = [s for s in run.claim_sources(c) if not s.retracted]
            if srcs:
                elements.append(el)
                kinds |= {s.kind for s in srcs}
        rows.append(
            {
                "job_id": job.id,
                "statement": job.statement,
                "elements": elements,
                "source_kinds": sorted(kinds),
                "passes": len(elements) >= KILL_ELEMENTS and len(kinds) >= KILL_KINDS,
                "thin": job.thin,
            }
        )
    return rows


def displayable(run: RunData, report) -> set[str]:
    """Claims that may be shown: live, evidential status, no gate flag, no open finding."""
    open_ids = {f.object_id for r in report.results for f in r.findings if f.object_type == "claim"}
    return {
        c.id
        for c in run.claims.values()
        if not c.retracted
        and not c.flags
        and c.status in ("PUBLIC_VOICE", "DERIVED", "PROXY_METRIC")
        and c.id not in open_ids
    }


def mine(
    run_dir: Path,
    category: str,
    llm: LLM,
    geo: str = "IE",
    limit: int | None = None,
    seed: int = 0,
    cfg: GateConfig | None = None,
    batch_size: int = 8,
) -> dict:
    t0 = time.monotonic()
    run_dir = Path(run_dir)
    cfg = cfg or GateConfig()
    demote(run_dir, cfg)  # drop failing sources (gates 7, 14) before they shape any score
    run = load_run(run_dir)
    traces = load_traces(run, limit=limit)
    summary: dict = {
        "category": category,
        "geo": geo,
        "traces": len(traces),
        "seed": seed,
        "llm_host": llm.host,
        "model": llm.model,
    }
    frozen = write_prompts(run_dir)
    try:
        ex = extract(llm, traces, category, batch_size)
    except LLMDisabled as exc:
        summary.update(status="skipped", reason=str(exc))
        (run_dir / "mine_summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
        return summary
    n_batches = -(-len(traces) // batch_size)
    if ex.failed_batches and 2 * ex.failed_batches >= n_batches:
        summary.update(
            status="failed",
            reason=f"LLM extraction failed for {ex.failed_batches} of {n_batches} batches",
            failed_batches=ex.failed_batches,
            cost_usd=round(llm.cost, 4),
            unpriced_llm_calls=llm.unpriced_calls,
        )
        (run_dir / "mine_summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
        return summary
    groups = llm_merge(llm, group_instances(ex.instances), category)
    built = [build_job(g, run.sources, geo) for g in groups]
    proxies = search_proxies(run_dir, built, geo)
    parts = build_edges(built, run.sources, geo, run.source_text)
    segs = segments(built, run.sources)

    extraction = run_dir / "extraction.json"
    extraction.write_text(
        json.dumps([asdict(i) for i in ex.instances], indent=1, sort_keys=True), "utf-8"
    )
    frozen.append(extraction)
    replace_mined(
        Store(run_dir / "store"),
        [
            *(c for b in built for c in b.claims.values()),
            *parts.claims,
            *proxies,
            *(b.job for b in built),
            *parts.edges,
            *segs,
        ],
        run_dir / "mined_ids.json",
    )
    write_manifest(run_dir, frozen, seed, model_family(llm.model or "") if llm.enabled else None)

    demotion = demote(run_dir, cfg)
    run = load_run(run_dir)
    shown = displayable(run, run_gates(run_dir, cfg))
    table = evidence_table(run, {b.job.id for b in built})
    freq = {b.job.id: b.freq if b.freq is not None else float(b.voices or 1) for b in built}
    value = {b.job.id: b.value if b.value is not None else 1.0 for b in built}
    graph = graph_payload(run, shown, freq, value, parts.solutions)
    passing = sum(r["passes"] for r in table)
    summary.update(
        status="ok",
        instances=len(ex.instances),
        jobs=len(table),
        jobs_passing=passing,
        # PRODUCT.md D1: denominator is every extracted job, thin ones included (a thin job has
        # < 2 voices or < 2 source kinds, so it can never pass); thin_jobs shows how many.
        share_passing=round(passing / len(table), 4) if table else 0.0,
        thin_jobs=sum(r["thin"] for r in table),
        segments=len(segs),
        thin_segments=sum(s.thin for s in segs),
        edges=len(parts.edges),
        spans_proposed=ex.proposed_spans,
        spans_rejected=ex.rejected_spans,
        rejected_span_rate=round(ex.rejected_spans / ex.proposed_spans, 4)
        if ex.proposed_spans
        else 0.0,
        failed_batches=ex.failed_batches,
        llm_calls=llm.calls,
        cost_usd=round(llm.cost, 4),
        unpriced_llm_calls=llm.unpriced_calls,  # cost_usd excludes these
        claims_displayed=len(shown),
        claims_total=len(run.claims),
        demotion=demotion,
    )
    reports = run_dir / "reports"
    write_graph_html(graph, reports / "graph.html")
    write_report_html(summary, table, graph, run, shown, reports / "report.html")
    report = run_gates(run_dir, cfg)  # final pass also lints the written HTML
    write_reports(report, run_dir / "gates")
    summary.update(
        gates_passed=report.passed,
        failed_gates=report.failed_gates(),
        runtime_s=round(time.monotonic() - t0, 1),
    )
    (run_dir / "graph.json").write_text(json.dumps(graph, indent=1, sort_keys=True), "utf-8")
    (run_dir / "mine_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), "utf-8"
    )
    return summary


def graph_payload(
    run: RunData,
    shown: set[str],
    freq: dict[str, float],
    value: dict[str, float],
    solutions: dict[str, str],
) -> dict:
    jobs = {j.id: j for j in run.jobs.values() if not j.retracted}
    edges = [
        e
        for e in run.edges.values()
        if not e.retracted
        and (e.from_job in jobs or e.from_job in solutions)
        and e.to_job in jobs
        and any(c in shown for c in e.claim_ids)
    ]
    imp = score.importance(list(jobs), [e for e in edges if e.kind != "performs"], freq, value)
    breaks = {b.edge_id: b for b in score.critical_breaks(edges)}
    nodes = []
    for j in sorted(jobs.values(), key=lambda j: j.id):
        nodes.append(
            {
                "id": j.id,
                "label": j.statement,
                "kind": "job",
                "level": j.level,
                "type": j.type,
                "thin": j.thin,
                "importance": imp.get(j.id, 0.0),
                "freq": freq.get(j.id),
                "value": value.get(j.id),
                "claims": sorted(c for c in shown if c.startswith(f"c_{j.id}_")),
            }
        )
    used = {e.from_job for e in edges}
    for sid, name in sorted(solutions.items()):
        if sid in used:
            nodes.append({"id": sid, "label": name, "kind": "solution", "importance": 0.0})
    out_edges = []
    for e in sorted(edges, key=lambda e: e.id):
        rv = score.route_value([e])
        out_edges.append(
            {
                "id": e.id,
                "source": e.from_job,
                "target": e.to_job,
                "kind": e.kind,
                "layer": e.layer,
                "p_success": e.p_success,
                "route_value": rv,
                "break": None
                if e.id not in breaks
                else ("certain" if breaks[e.id].certain else "possible"),
                "claims": [c for c in e.claim_ids if c in shown],
            }
        )
    consideration = {}
    for j in jobs.values():
        names = sorted(
            solutions[e.from_job]
            for e in edges
            if e.to_job == j.id and e.kind == "performs" and e.from_job in solutions
        )
        if names:
            consideration[j.id] = names
    return {
        "status": score.STATUS,
        "nodes": nodes,
        "edges": out_edges,
        "layers": score.layer_views(edges),
        "consideration_sets": consideration,
        "id": sha256_text(json.dumps([n["id"] for n in nodes]))[:12],
    }
