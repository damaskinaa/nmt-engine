"""Kill line v2 auditor stages (PREREG_killline_v2.md §5, §6). Usage:

  v2_label.py extract OUT R3_DIR:R0_DIR:CATEGORY ...   producer extraction of the R3 traces
  v2_label.py pairs OUT        embed, sample 200 pairs, auditor labels, t*, blind pair packet
  v2_label.py spans OUT        sample 400 spans, auditor audit, Wilson rates, blind span packet
  v2_label.py roles OUT        diagnostic only: share of audited spans whose author builds a product
  v2_label.py agree OUT        compare operator answers (human_*.answers.json) with the auditor

Producer settings come from NMT_LLM_* (as in Session A, so extraction replays from the cache);
the auditor is moonshotai/kimi-k3.1-pro on the same endpoint. Needs TENSORX_API_KEY."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from nmt_engine.config import forbidden_corpus_dir
from nmt_engine.embed import Embedder
from nmt_engine.gates import GateConfig, demote
from nmt_engine.llm import LLM
from nmt_engine.miner import audit
from nmt_engine.miner import cluster as cl
from nmt_engine.miner.extract import JobInstance, extract, load_traces
from nmt_engine.store import load_run

AUDITOR = "moonshotai/kimi-k3.1-pro"
BASE = "https://api.tensorx.ai/v1"
SEED = 0


def auditor(out: Path) -> LLM:
    return LLM(out, provider="openai", model=AUDITOR, base_url=BASE, max_tokens=16384, timeout=600)


def load_instances(out: Path) -> dict[str, list[JobInstance]]:
    meta = json.loads((out / "extraction.json").read_text("utf-8"))
    res = {}
    for cat, rows in meta["instances"].items():
        res[cat] = [
            JobInstance(
                **{
                    **r,
                    "criteria": [tuple(x) for x in r["criteria"]],
                    "alternatives": [tuple(x) for x in r["alternatives"]],
                }
            )
            for r in rows
        ]
    return res


def stage_extract(out: Path, specs: list[str]) -> None:
    llm = LLM(out)
    res, stats = {}, {}
    for spec in specs:
        r3, r0, cat = spec.split(":", 2)
        t0, c0 = time.monotonic(), llm.cost
        demote(Path(r3), GateConfig(forbidden_corpus=forbidden_corpus_dir()))
        first = frozenset(t.source.id for t in load_traces(load_run(Path(r0))))
        traces = load_traces(load_run(Path(r3)), first=first)
        ex = extract(llm, traces, cat)
        res[cat] = [asdict(i) for i in ex.instances]
        stats[cat] = {
            "run_dir": r3,
            "traces": len(traces),
            "carried": len(first & {t.source.id for t in traces}),
            "instances": len(ex.instances),
            "spans_proposed": ex.proposed_spans,
            "spans_rejected": ex.rejected_spans,
            "failed_batches": ex.failed_batches,
            "cost_usd": round(llm.cost - c0, 4),
            "runtime_s": round(time.monotonic() - t0, 1),
        }
        print(cat, stats[cat], flush=True)
    llm.close()
    body = {"model": llm.model, "host": llm.host, "stats": stats, "instances": res}
    (out / "extraction.json").write_text(json.dumps(body, indent=1, sort_keys=True), "utf-8")


def stage_pairs(out: Path) -> None:
    insts = load_instances(out)
    t0 = time.monotonic()
    texts, dists = {}, {}
    with Embedder(out) as emb:
        for cat, rows in insts.items():
            texts[cat] = [cl.instance_text(i) for i in rows]
            dists[cat], _ = cl.cosine_linkage(emb.embed(texts[cat], "audit.embed"))
        embed_cost, embed_tokens = emb.cost, emb.tokens
    pairs, edges = cl.sample_pairs(dists, {c: len(r) for c, r in insts.items()}, seed=SEED)
    llm = auditor(out)
    labels = audit.label_pairs(
        llm, [(p.category, texts[p.category][p.a], texts[p.category][p.b]) for p in pairs]
    )
    llm.close()
    rows = [
        {**asdict(p), "text_a": texts[p.category][p.a], "text_b": texts[p.category][p.b], "same": s}
        for p, s in zip(pairs, labels, strict=True)
    ]
    with (out / "pairs.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    lab = [r for r in rows if r["same"] is not None]
    if len(lab) < len(rows):
        sys.exit(f"{len(rows) - len(lab)} pairs still unlabelled; t* needs all {len(rows)}")
    th = cl.choose_threshold([r["distance"] for r in lab], [r["same"] for r in lab])
    missing = [i for i, r in enumerate(rows) if r["same"] is None]  # empty past the check above
    blind = audit.blind_sample(len(rows), 30, SEED + 1, missing)
    summary = {
        "pairs": len(rows),
        "labelled": len(lab),
        "same": sum(r["same"] for r in lab),
        "band_edges": [round(e, 6) for e in edges],
        "per_band": [sum(r["band"] == b for r in rows) for b in range(len(edges) - 1)],
        "t_star": th.t,
        "f1": th.f1,
        "precision": th.precision,
        "recall": th.recall,
        "curve": th.curve,
        "auditor": AUDITOR,
        "auditor_cost_usd": round(llm.cost, 4),
        "auditor_calls": llm.calls,
        "embed_model": emb.model,
        "embed_tokens": embed_tokens,
        "embed_cost_usd": round(embed_cost, 6),
        "runtime_s": round(time.monotonic() - t0, 1),
        "blind": blind,
    }
    (out / "threshold.json").write_text(json.dumps(summary, indent=1), "utf-8")
    lines = [
        "# Blind pair check (30 pairs)",
        "",
        "For each pair answer **same** (same goal and same expected outcome) or **different**.",
        "",
    ]
    for n, i in enumerate(blind, 1):
        r = rows[i]
        lines += [
            f"**{n}.** ({r['category']})",
            "",
            "A: " + r["text_a"].replace("\n", " / "),
            "",
            "B: " + r["text_b"].replace("\n", " / "),
            "",
        ]
    (out / "human_pairs.md").write_text("\n".join(lines), "utf-8")
    print({k: v for k, v in summary.items() if k != "curve"})


def stage_spans(out: Path) -> None:
    insts = load_instances(out)
    t0 = time.monotonic()
    spans = audit.sample_spans(insts, 50, SEED)
    llm = auditor(out)
    verdicts = audit.audit_spans(llm, spans)
    llm.close()
    rates = audit.mislabel_rates(spans, verdicts)
    with (out / "spans.jsonl").open("w", encoding="utf-8") as f:
        for s, v in zip(spans, verdicts, strict=True):
            f.write(json.dumps({**asdict(s), "correct": v}, sort_keys=True) + "\n")
    missing = [i for i, v in enumerate(verdicts) if v is None]
    blind = audit.blind_sample(len(spans), 20, SEED + 2, missing)
    summary = {
        "spans": len(spans),
        "answered": len(spans) - len(missing),
        "rates": rates,
        "excluded": sorted(e for e, r in rates.items() if r["excluded"]),
        "auditor": AUDITOR,
        "auditor_cost_usd": round(llm.cost, 4),
        "auditor_calls": llm.calls,
        "runtime_s": round(time.monotonic() - t0, 1),
        "blind": blind,
    }
    (out / "audit.json").write_text(json.dumps(summary, indent=1), "utf-8")
    lines = [
        "# Blind span check (20 spans)",
        "",
        "For each item answer **yes** if the quote is evidence of the element for that job, "
        "else **no**.",
        "",
    ]
    for n, i in enumerate(blind, 1):
        s = spans[i]
        lines += [
            f"**{n}.** ({s.category}) job: {s.job}",
            "",
            f"element: `{s.element}`",
            "",
            f"> {s.span}",
            "",
        ]
    (out / "human_spans.md").write_text("\n".join(lines), "utf-8")
    print({k: v for k, v in summary.items() if k != "rates"})
    for e, r in rates.items():
        print(e, r)


def stage_roles(out: Path) -> None:
    """Builder-vs-user author share over the audited spans; reported, never part of the verdict."""
    t0 = time.monotonic()
    spans = [json.loads(x) for x in (out / "spans.jsonl").read_text("utf-8").splitlines()]
    stats = json.loads((out / "extraction.json").read_text("utf-8"))["stats"]
    runs = {cat: load_run(Path(s["run_dir"])) for cat, s in stats.items()}
    keys = sorted({(s["category"], s["source_id"]) for s in spans})
    texts = {(c, t.source.id): t.prompt_text for c, run in runs.items() for t in load_traces(run)}
    llm = auditor(out)
    roles = dict(
        zip(keys, audit.author_roles(llm, [(c, texts[(c, s)]) for c, s in keys]), strict=True)
    )
    llm.close()
    per_span = [roles[(s["category"], s["source_id"])] for s in spans]

    def share(vals: list) -> dict:
        known = [v for v in vals if v is not None]
        return {
            "n": len(known),
            "builder": sum(known),
            "share": round(sum(known) / len(known), 4) if known else None,
        }

    res = {
        "spans": share(per_span),
        "posts": share(list(roles.values())),
        "by_category": {
            c: share([v for s, v in zip(spans, per_span, strict=True) if s["category"] == c])
            for c in stats
        },
        "by_element": {
            e: share([v for s, v in zip(spans, per_span, strict=True) if s["element"] == e])
            for e in sorted({s["element"] for s in spans})
        },
        "auditor": AUDITOR,
        "auditor_cost_usd": round(llm.cost, 4),
        "auditor_calls": llm.calls,
        "runtime_s": round(time.monotonic() - t0, 1),
    }
    with (out / "roles.jsonl").open("w", encoding="utf-8") as f:
        for (c, s), v in roles.items():
            f.write(
                json.dumps({"category": c, "source_id": s, "builder": v}, sort_keys=True) + "\n"
            )
    (out / "roles.json").write_text(json.dumps(res, indent=1), "utf-8")
    print(json.dumps(res, indent=1))


def stage_agree(out: Path) -> None:
    """human_pairs.answers.json / human_spans.answers.json: lists of booleans in packet order."""
    res = {}
    for name, rows_file, meta_file, field in (
        ("pairs", "pairs.jsonl", "threshold.json", "same"),
        ("spans", "spans.jsonl", "audit.json", "correct"),
    ):
        ans = out / f"human_{name}.answers.json"
        if not ans.is_file():
            continue
        rows = [json.loads(x) for x in (out / rows_file).read_text("utf-8").splitlines()]
        blind = json.loads((out / meta_file).read_text("utf-8"))["blind"]
        human = json.loads(ans.read_text("utf-8"))
        res[name] = {
            "n": len(human),
            "agreement": audit.agreement(human, [rows[i][field] for i in blind]),
            "disagreements": [
                n + 1
                for n, (h, i) in enumerate(zip(human, blind, strict=True))
                if h != rows[i][field]
            ],
        }
    res["pairs_ok"] = res.get("pairs", {}).get("agreement", 0) >= audit.AGREE_MIN
    (out / "agreement.json").write_text(json.dumps(res, indent=1), "utf-8")
    print(res)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    stage, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    {
        "extract": lambda: stage_extract(out, sys.argv[3:]),
        "pairs": lambda: stage_pairs(out),
        "spans": lambda: stage_spans(out),
        "roles": lambda: stage_roles(out),
        "agree": lambda: stage_agree(out),
    }[stage]()
