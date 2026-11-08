"""Step 0 diagnostics for kill line v2: read finished `nmt collect` + `nmt mine` runs (no LLM).

usage: python scripts/diagnose_v2.py RUN_DIR [RUN_DIR ...] > diagnosis.md
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from nmt_engine.miner import prompts
from nmt_engine.miner.extract import TRACE_KINDS, load_traces
from nmt_engine.miner.pipeline import KILL_ELEMENTS, KILL_KINDS, evidence_table
from nmt_engine.schema import Job
from nmt_engine.store import load_run

BINS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 10**9))


def job_posts(run, job: Job) -> set[str]:
    """Customer posts behind a job's receipts (search proxies and other non-trace sources
    excluded)."""
    return {
        r.source_id
        for cid in job.claim_ids
        + [f"c_{job.id}_{el}" for el in (*prompts.ELEMENTS, *prompts.VALUE_MARKERS)]
        if (c := run.claims.get(cid)) is not None and not c.retracted
        for r in c.source_refs
        if (s := run.sources.get(r.source_id)) is not None and s.kind in TRACE_KINDS
    }


def diagnose(run_dir: Path) -> dict:
    run = load_run(run_dir)
    summ = json.loads((run_dir / "collect_summary.json").read_text("utf-8"))
    traces = load_traces(run)
    table = evidence_table(run, {j.id for j in run.jobs.values() if not j.retracted})
    jobs = {j.id: j for j in run.jobs.values() if not j.retracted}
    posts = {jid: len(job_posts(run, j)) for jid, j in jobs.items()}
    inst = json.loads((run_dir / "extraction.json").read_text("utf-8"))
    fail = Counter()
    for r in table:
        if r["passes"]:
            continue
        k, e = len(r["source_kinds"]) < KILL_KINDS, len(r["elements"]) < KILL_ELEMENTS
        fail["both" if k and e else "kinds_only" if k else "elements_only"] += 1
    return {
        "category": summ["category"],
        "adapters": summ["adapters"],
        "sources_by_kind": Counter(s.kind for s in run.sources.values() if not s.retracted),
        "traces_by_kind": Counter(t.source.kind for t in traces),
        "traces_by_platform": Counter(t.source.platform.split(":")[0] for t in traces),
        "posts": posts,
        "job_levels": Counter(j.level for j in jobs.values()),
        "instance_levels": Counter(i["level"] for i in inst),
        "passing": sum(r["passes"] for r in table),
        "jobs": len(table),
        "fail": fail,
    }


def md(ds: list[dict]) -> str:
    cats = [d["category"] for d in ds]
    out = ["### a) Collect adapters per category (count, or status: reason)", ""]
    out += ["| adapter | " + " | ".join(cats) + " |", "|---|" + "---:|" * len(cats)]
    names = list(dict.fromkeys(a for d in ds for a in d["adapters"]))
    for a in names:
        cells = []
        for d in ds:
            v = d["adapters"].get(a)
            if v is None:
                cells.append("—")
            elif v["status"] == "ok":
                cells.append(str(v["sources"]))
            else:
                cells.append(f"{v['status']}: {v.get('reason', '')[:60]}")
        out.append(f"| {a} | " + " | ".join(cells) + " |")
    out += ["", "### b) Sources and traces per kind", ""]
    kinds = sorted({k for d in ds for k in d["sources_by_kind"]})
    out += ["| kind | " + " | ".join(f"{c} sources / traces" for c in cats) + " |"]
    out += ["|---|" + "---:|" * len(cats)]
    for k in kinds:
        cells = [
            f"{d['sources_by_kind'].get(k, 0)} / "
            + (str(d["traces_by_kind"].get(k, 0)) if k in TRACE_KINDS else "not a trace kind")
            for d in ds
        ]
        out.append(f"| {k} | " + " | ".join(cells) + " |")
    out += [
        "",
        "Traces by platform: "
        + "; ".join(
            f"{d['category']}: "
            + ", ".join(f"{p} {n}" for p, n in d["traces_by_platform"].most_common())
            for d in ds
        ),
    ]
    out += ["", "### c) Posts per job (distinct sources behind a job's receipts)", ""]
    out += ["| posts | " + " | ".join(cats) + " |", "|---|" + "---:|" * len(cats)]
    for lo, hi in BINS:
        label = str(lo) if lo == hi else (f"{lo}+" if hi > 10**8 else f"{lo}–{hi}")
        cells = []
        for d in ds:
            n = sum(lo <= v <= hi for v in d["posts"].values())
            cells.append(f"{n} ({100 * n / max(len(d['posts']), 1):.0f}%)")
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    out.append(
        "| mean / max | "
        + " | ".join(
            f"{sum(d['posts'].values()) / max(len(d['posts']), 1):.2f} / "
            f"{max(d['posts'].values(), default=0)}"
            for d in ds
        )
        + " |"
    )
    out += ["", "### d) Level distribution (jobs by majority level; instances in brackets)", ""]
    out += ["| level | " + " | ".join(cats) + " |", "|---|" + "---:|" * len(cats)]
    for lv in ("big", "core", "small", "micro"):
        cells = [f"{d['job_levels'].get(lv, 0)} [{d['instance_levels'].get(lv, 0)}]" for d in ds]
        out.append(f"| {lv} | " + " | ".join(cells) + " |")
    out += [
        "",
        f"### e) Why jobs fail (bar: >= {KILL_ELEMENTS} of 8 elements AND >= {KILL_KINDS} kinds)",
        "",
    ]
    out += ["| | " + " | ".join(cats) + " |", "|---|" + "---:|" * len(cats)]
    out.append(
        "| jobs / passing | " + " | ".join(f"{d['jobs']} / {d['passing']}" for d in ds) + " |"
    )
    for k, label in (
        ("kinds_only", "fail ONLY on kinds < 2"),
        ("elements_only", "fail ONLY on elements < 4"),
        ("both", "fail on both"),
    ):
        out.append(f"| {label} | " + " | ".join(str(d["fail"].get(k, 0)) for d in ds) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    done, failed = [], []
    for p in sys.argv[1:]:
        try:
            done.append(diagnose(Path(p)))
        except (OSError, ValueError, KeyError) as e:
            failed.append(p)
            print(f"ERROR: skipped {p}: {type(e).__name__}: {e}", file=sys.stderr)
    if done:
        print(md(done))
    if failed:  # a missing category must never pass unnoticed into the tables
        sys.exit(f"{len(failed)} of {len(sys.argv) - 1} run(s) unreadable: {', '.join(failed)}")
