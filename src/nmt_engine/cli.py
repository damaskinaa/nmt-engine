"""`nmt` command-line interface."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from nmt_engine.config import forbidden_corpus_dir
from nmt_engine.gates import GateConfig, demote, run_gates, write_reports

app = typer.Typer(no_args_is_help=True, add_completion=False, help="nmt-engine CLI")
gates_app = typer.Typer(no_args_is_help=True, help="Deterministic evidence gates 1-14")
app.add_typer(gates_app, name="gates")

CorpusOpt = Annotated[
    Path | None,
    typer.Option("--forbidden-corpus", help="Folder of forbidden texts (gate 10)"),
]


def _cfg(corpus: Path | None) -> GateConfig:
    return GateConfig(forbidden_corpus=corpus or forbidden_corpus_dir())


@gates_app.command("check")
def gates_check(
    run_dir: Path,
    forbidden_corpus: CorpusOpt = None,
    out: Annotated[Path | None, typer.Option(help="Where to write gate_report.*")] = None,
) -> None:
    """Run all gates; write gate_report.json + gate_report.md; exit 0 (pass) or 1 (fail)."""
    report = run_gates(run_dir, _cfg(forbidden_corpus))
    jpath, mpath = write_reports(report, out)
    failed = report.failed_gates()
    typer.echo(f"{'PASS' if report.passed else 'FAIL'} {run_dir} -> {mpath}")
    if report.schema_errors:
        typer.echo(f"schema errors: {len(report.schema_errors)}")
    if failed:
        typer.echo("failed gates: " + ", ".join(str(n) for n in failed))
    raise typer.Exit(0 if report.passed else 1)


@gates_app.command("demote")
def gates_demote(run_dir: Path, forbidden_corpus: CorpusOpt = None) -> None:
    """Apply gate actions (demote / single-signal / collapse / drop / flag) as store revisions."""
    summary = demote(run_dir, _cfg(forbidden_corpus))
    typer.echo(json.dumps(summary, indent=2, sort_keys=True))


@app.command("collect")
def collect_cmd(
    category: Annotated[str, typer.Option("--category", help="Category search query")],
    since: Annotated[str, typer.Option("--since", help="YYYY-MM-DD")],
    geo: Annotated[str, typer.Option("--geo")] = "IE",
    competitors: Annotated[str, typer.Option("--competitors", help="a.com,b.com")] = "",
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    per_adapter: Annotated[int, typer.Option("--per-adapter")] = 200,
    stack_sites: Annotated[
        str, typer.Option("--stack-sites", help="Stack Exchange sites, e.g. webapps,money")
    ] = "",
    apps: Annotated[str, typer.Option("--apps", help="App Store app names, e.g. Habitica")] = "",
    only: Annotated[
        str,
        typer.Option(
            "--only",
            help="run only steps with these name prefixes, e.g. appstore:,web: (a top-up: run "
            "it on a copy of the base run dir; summary totals are recomputed from its whole store)",
        ),
    ] = "",
    as_of: Annotated[
        str, typer.Option("--as-of", help="YYYY-MM-DD cache date; reuse an earlier run's responses")
    ] = "",
) -> None:
    """Collect lawful public traces for a category into a run folder."""
    from datetime import date

    from nmt_engine.collect.base import MissingKeyError
    from nmt_engine.collect.run import STACK_SITES, CollectPlan, run_collect

    plan = CollectPlan(
        category=category,
        since=date.fromisoformat(since),
        geo=geo,
        competitors=[d.strip() for d in competitors.split(",") if d.strip()],
        per_adapter=per_adapter,
        stack_sites=[s.strip() for s in stack_sites.split(",") if s.strip()] or list(STACK_SITES),
        apps=[a.strip() for a in apps.split(",") if a.strip()],
        as_of=date.fromisoformat(as_of) if as_of else None,
        only=[o.strip() for o in only.split(",") if o.strip()],
    )
    slug = "".join(ch if ch.isalnum() else "-" for ch in category.lower()).strip("-")
    out = run_dir or Path("runs") / f"{date.today():%Y%m%d}-{slug}"
    try:
        summary = run_collect(plan, out)
    except MissingKeyError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(summary, indent=2))


gold_app = typer.Typer(help="L3 gold set and precision gate (ARCHITECTURE_v3 §4.3, §8 A1-A3)")
app.add_typer(gold_app, name="gold")


def _tensorx(
    model: str, run_dir: Path, reasoning: str | None = None, max_tokens: int = 4096, budget=None
):
    from nmt_engine.llm import LLM, TENSORX_URL, Budget

    return LLM(
        run_dir,
        provider="openai",
        model=model,
        base_url=TENSORX_URL,
        reasoning_effort=reasoning,
        timeout=600,
        max_tokens=max_tokens,
        budget=budget or Budget(),  # share one Budget across models in the same run
    )


@gold_app.command("build")
def gold_build(
    run_dirs: list[Path],
    category: Annotated[str, typer.Option("--category")] = "invoicing",
    seed: Annotated[int, typer.Option("--seed")] = 0,
) -> None:
    """Sample the gold posts from collected runs (text goes to the gitignored cache)."""
    from nmt_engine.verify import gold

    typer.echo(json.dumps(gold.build(run_dirs, category, seed), indent=2))


@gold_app.command("label")
def gold_label(run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold")) -> None:
    """Auditor (Kimi) gold labels."""
    from nmt_engine.llm import AUDITOR
    from nmt_engine.verify import gold

    llm = _tensorx(AUDITOR, run_dir, max_tokens=16000)  # Kimi reasons before it answers
    try:
        res = gold.label(llm)
    finally:
        llm.close()
    typer.echo(json.dumps({**res, "budget": llm.budget.as_dict()}, indent=2))


@gold_app.command("record")
def gold_record(run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold")) -> None:
    """Producer (DeepSeek) answers on the gold posts, saved under the current prompt hash."""
    from nmt_engine.llm import PRODUCER
    from nmt_engine.verify import gold

    llm = _tensorx(PRODUCER, run_dir, gold.PRODUCER_REASONING)
    try:
        path = gold.record(llm)
    finally:
        llm.close()
    typer.echo(json.dumps({"recorded": str(path), "budget": llm.budget.as_dict()}, indent=2))


@gold_app.command("cross")
def gold_cross(run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold")) -> None:
    """Third model (GLM-5.3, thinking off) labels the gold posts blind; cross-model agreement."""
    from nmt_engine.llm import THIRD_MODEL
    from nmt_engine.verify import gold

    llm = _tensorx(THIRD_MODEL, run_dir, "none", max_tokens=8000)
    try:
        path = gold.cross_label(llm)
    finally:
        llm.close()
    res = gold.cross_agreement(path)
    (gold.GOLD_DIR / "cross_agreement.json").write_text(json.dumps(res, indent=1) + "\n", "utf-8")
    typer.echo(json.dumps({**res, "budget": llm.budget.as_dict()}, indent=2))
    raise typer.Exit(0 if res["passed"] else 1)


@gold_app.command("check")
def gold_check() -> None:
    """Producer precision vs gold; exit 1 below 85% on the held-out test split."""
    from nmt_engine.verify import gold

    res = gold.check()
    typer.echo(json.dumps(res, indent=2))
    raise typer.Exit(0 if res["passed"] else 1)


@gold_app.command("node-canary")
def gold_node_canary(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold"),
) -> None:
    """Amendment 2 canary: 6 synthetic pairs through the frozen gold node prompt (never T1)."""
    from nmt_engine.llm import AUDITOR
    from nmt_engine.verify import node_gold

    llm = _tensorx(AUDITOR, run_dir, max_tokens=16000)
    try:
        res = node_gold.canary(llm)
    finally:
        llm.close()
    typer.echo(json.dumps({**res, "budget": llm.budget.as_dict()}, indent=2))
    raise typer.Exit(0 if res["ok"] else 1)


@gold_app.command("node-pick")
def gold_node_pick(
    round_: Annotated[int, typer.Option("--round")] = 0,
    harvest_dir: Annotated[Path, typer.Option("--harvest-dir")] = Path("runs/l2"),
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold"),
) -> None:
    """Amendment 2: Kimi author roles down each node's ranked harvest posts; top 8 + 2 negatives."""
    from nmt_engine.llm import AUDITOR
    from nmt_engine.verify import node_gold

    llm = _tensorx(AUDITOR, run_dir, max_tokens=16000)
    try:
        res = node_gold.pick(llm, harvest_dir, round_)
    finally:
        llm.close()
    typer.echo(json.dumps({**res, "budget": llm.budget.as_dict()}, indent=2))


@gold_app.command("node-pick-embed")
def gold_node_pick_embed(
    harvest_dir: Annotated[Path, typer.Option("--harvest-dir")] = Path("runs/l2"),
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold"),
) -> None:
    """Amendment 3: customer-voice pool ranked per node by Qwen3 similarity; top 8 + 2 random."""
    from nmt_engine.embed import Embedder
    from nmt_engine.llm import AUDITOR
    from nmt_engine.verify import node_gold

    llm = _tensorx(AUDITOR, run_dir, max_tokens=16000)
    emb = Embedder(run_dir)
    try:
        res = node_gold.pick_embed(llm, emb, harvest_dir)
    finally:
        llm.close()
        emb.close()
    typer.echo(json.dumps({**res, "budget": llm.budget.as_dict()}, indent=2))


@gold_app.command("node-cross")
def gold_node_cross(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold"),
) -> None:
    """GLM-5.3 (thinking off) labels every node item blind; agreement over designated pairs."""
    from nmt_engine.llm import THIRD_MODEL
    from nmt_engine.verify import node_gold

    llm = _tensorx(THIRD_MODEL, run_dir, "none", max_tokens=16000)
    try:
        path = node_gold.cross_label(llm)
    finally:
        llm.close()
    res = node_gold.cross_agreement(path)
    typer.echo(json.dumps({**res, "budget": llm.budget.as_dict()}, indent=2))
    raise typer.Exit(0 if res["passed"] else 1)


@gold_app.command("node-label")
def gold_node_label(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold"),
) -> None:
    """Kimi node-check gold on the amendment-2 node items (all 10 statements per item)."""
    from nmt_engine.llm import AUDITOR
    from nmt_engine.verify import node_gold

    llm = _tensorx(AUDITOR, run_dir, max_tokens=16000)
    try:
        res = node_gold.label(llm)
    finally:
        llm.close()
    typer.echo(json.dumps({**res, "budget": llm.budget.as_dict()}, indent=2))


@gold_app.command("node-record")
def gold_node_record(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/gold"),
) -> None:
    """Producer node-check answers on the node gold posts, saved under the node prompt hash."""
    from nmt_engine.llm import PRODUCER
    from nmt_engine.verify import gold, node_gold

    llm = _tensorx(PRODUCER, run_dir, gold.PRODUCER_REASONING)
    try:
        path = node_gold.record(llm)
    finally:
        llm.close()
    typer.echo(json.dumps({"recorded": str(path), "budget": llm.budget.as_dict()}, indent=2))


@gold_app.command("grow")
def gold_grow(
    round_: Annotated[int, typer.Option("--round")],
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/l2"),
) -> None:
    """Add 150 L2 posts to the held-out test split (PREREG_v3 amendment 1); no model calls."""
    from nmt_engine.verify import node_gold

    typer.echo(json.dumps(node_gold.grow(run_dir, round_), indent=2))


@gold_app.command("t1")
def gold_t1() -> None:
    """T1: per-class precision against model labels; says whether T2 may run."""
    from nmt_engine.verify import node_gold

    res = node_gold.t1()
    typer.echo(json.dumps(res, indent=2))
    raise typer.Exit(0 if res["passed"] else 1)


@gold_app.command("agree")
def gold_agree(answers: str) -> None:
    """Human blind labels (30 letters U/B/V/O) vs auditor gold; fewer than 24 agreeing stops."""
    from nmt_engine.verify import gold

    res = gold.human_agreement(answers)
    path = gold.GOLD_DIR / "human_agreement.json"
    path.write_text(json.dumps(res, indent=1) + "\n", "utf-8")
    typer.echo(json.dumps({k: v for k, v in res.items() if k != "items"}, indent=2))
    raise typer.Exit(0 if res["passed"] else 1)


l1_app = typer.Typer(help="L0 brief + L1 hypothesis Job Graph (ARCHITECTURE_v3 §3, §8 C3)")
app.add_typer(l1_app, name="l1")
BRIEF_OPT = typer.Option("--brief")


def _graph_path(brief_path: Path) -> Path:
    return brief_path.with_suffix(".l1.json")


@l1_app.command("build")
def l1_build(
    brief_path: Annotated[Path, BRIEF_OPT] = Path("briefs/invoicing.json"),
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/l1"),
) -> None:
    """Producer drafts the graph; schema + Kimi link check decide (max 2 regenerations)."""
    from nmt_engine.brief import load_brief
    from nmt_engine.hypothesis import generate
    from nmt_engine.llm import AUDITOR, PRODUCER, Budget

    brief = load_brief(brief_path)
    budget = Budget()
    producer = _tensorx(PRODUCER, run_dir, "none", max_tokens=16000, budget=budget)
    auditor = _tensorx(AUDITOR, run_dir, max_tokens=16000, budget=budget)
    try:
        res = generate.build(producer, auditor, brief)
    finally:
        producer.close()
        auditor.close()
    out = generate.to_json(res["graph"], brief, res["status"])
    out["attempts"] = res["attempts"]
    _graph_path(brief_path).write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", "utf-8"
    )
    typer.echo(
        json.dumps(
            {
                "status": res["status"],
                "attempts": res["attempts"],
                "riskiest": out["riskiest"],
                "budget": budget.as_dict(),
            },
            indent=2,
        )
    )
    raise typer.Exit(0 if res["status"] == "passed" else 1)


@l1_app.command("gold-build")
def l1_gold_build(brief_path: Annotated[Path, BRIEF_OPT] = Path("briefs/invoicing.json")) -> None:
    """Consistency gold: real links (consistent) + code-corrupted links (inconsistent)."""
    from nmt_engine.hypothesis import generate, gold

    typer.echo(json.dumps(gold.build(generate.load(_graph_path(brief_path))), indent=2))


@l1_app.command("gold-record")
def l1_gold_record(
    brief_path: Annotated[Path, BRIEF_OPT] = Path("briefs/invoicing.json"),
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/l1"),
) -> None:
    """Kimi answers the consistency gold; committed under the check prompt hash."""
    from nmt_engine.brief import load_brief
    from nmt_engine.hypothesis import gold
    from nmt_engine.llm import AUDITOR

    llm = _tensorx(AUDITOR, run_dir, max_tokens=16000)
    try:
        path = gold.record(llm, load_brief(brief_path).market_job)
    finally:
        llm.close()
    typer.echo(json.dumps({"recorded": str(path), "budget": llm.budget.as_dict()}, indent=2))


@l1_app.command("gold-check")
def l1_gold_check() -> None:
    """Consistency-check precision vs constructed truth; exit 1 if a measured class < 85%."""
    from nmt_engine.hypothesis import gold

    res = gold.check()
    typer.echo(json.dumps(res, indent=2))
    raise typer.Exit(0 if res["passed"] else 1)


l2_app = typer.Typer(help="L2 targeted harvest from the 10 riskiest nodes (ARCHITECTURE_v3 §3)")
app.add_typer(l2_app, name="l2")


def _riskiest(brief_path: Path):
    from nmt_engine.hypothesis import generate

    path = _graph_path(brief_path)
    frozen = json.loads(path.read_text("utf-8"))
    return generate.load(path), frozen["brief_hash"], [r["id"] for r in frozen["riskiest"]]


@l2_app.command("plan")
def l2_plan(
    brief_path: Annotated[Path, BRIEF_OPT] = Path("briefs/invoicing.json"),
    competitors: Annotated[str, typer.Option("--competitors", help="a.com,b.com")] = "",
    since: Annotated[str, typer.Option("--since")] = "2023-01-01",
    apps: Annotated[
        str, typer.Option("--apps", help="extra App Store names, comma-separated")
    ] = "",
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/l2"),
) -> None:
    """Template + producer queries for the 10 riskiest nodes; written next to the brief."""
    from nmt_engine import harvest
    from nmt_engine.llm import PRODUCER
    from nmt_engine.verify import node

    g, bhash, risky = _riskiest(brief_path)
    llm = _tensorx(PRODUCER, run_dir, "none")
    try:
        p = harvest.plan(
            llm,
            g,
            bhash,
            risky,
            node.statements(g, risky),
            [d.strip() for d in competitors.split(",") if d.strip()],
            since,
            [a.strip() for a in apps.split(",") if a.strip()],
        )
    finally:
        llm.close()
    out = brief_path.with_suffix(".l2.json")
    out.write_text(json.dumps({**p.as_dict(), "hash": p.hash}, indent=1) + "\n", "utf-8")
    typer.echo(json.dumps({"plan": str(out), "queries": len(p.queries), "hash": p.hash}))


@l2_app.command("harvest")
def l2_harvest(
    brief_path: Annotated[Path, BRIEF_OPT] = Path("briefs/invoicing.json"),
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/l2"),
) -> None:
    """Run the committed plan through the six L2 collectors."""
    from nmt_engine import harvest

    d = json.loads(brief_path.with_suffix(".l2.json").read_text("utf-8"))
    p = harvest.HarvestPlan.from_dict(d)
    if p.hash != d["hash"]:
        raise typer.BadParameter("plan file was edited after planning (hash mismatch)")
    s = harvest.run(p, run_dir)
    typer.echo(json.dumps({k: v for k, v in s.items() if k != "steps"}, indent=2))


l4_app = typer.Typer(help="L3 on the harvest + L4 node status and T2 (ARCHITECTURE_v3 §3, §5)")
app.add_typer(l4_app, name="l4")


@l4_app.command("run")
def l4_run(
    brief_path: Annotated[Path, BRIEF_OPT] = Path("briefs/invoicing.json"),
    run_dir: Annotated[Path, typer.Option("--run-dir")] = Path("runs/l2"),
    force: Annotated[bool, typer.Option("--force", help="run even if T1 blocks T2")] = False,
) -> None:
    """Producer author gate + node check on the harvest, then node status and T2. Refuses to run
    unless T1 passed for USER, supports and contradicts (PREREG_v3 §3)."""
    from nmt_engine import ledger
    from nmt_engine.llm import PRODUCER
    from nmt_engine.verify import gold, node, node_gold

    t1 = node_gold.t1()
    if not t1["t2_may_run"] and not force:
        typer.echo(json.dumps({"t2": "NOT RUN", "reason": "T1 blocks T2", **t1}, indent=2))
        raise typer.Exit(1)
    g, _, risky = _riskiest(brief_path)
    llm = _tensorx(PRODUCER, run_dir, gold.PRODUCER_REASONING)
    try:
        records = ledger.verify_run(llm, run_dir, node.statements(g, risky))
    finally:
        llm.close()
    statuses = ledger.node_status(records, risky)
    res = {
        "t1_t2_may_run": t1["t2_may_run"],
        "forced": force and not t1["t2_may_run"],
        "posts": len(records),
        "user_naming_solution": sum(1 for r in records if r["nodes"] is not None),
        "t2": ledger.t2(statuses),
        "nodes": [ledger.public(s) for s in statuses],
        "budget": llm.budget.as_dict(),
    }
    brief_path.with_suffix(".l4.json").write_text(json.dumps(res, indent=1) + "\n", "utf-8")
    typer.echo(json.dumps({k: v for k, v in res.items() if k != "nodes"}, indent=2))
    raise typer.Exit(0 if res["t2"]["passed"] else 1)


sim_app = typer.Typer(
    help="L6 simulation world, SSR and its gold (ARCHITECTURE_v3 L6, PREREG amendment 4)"
)
app.add_typer(sim_app, name="sim")
SIM_DIR = Path("runs/b4")


def _sim_budget(run_dir: Path):
    """The `sim` step cap covers all of B4 (PREREG amendment 6 rule 8): seed spend from the log."""
    from nmt_engine.llm import Budget

    spent = 0.0
    log = run_dir / "llm_log.jsonl"
    for line in log.read_text("utf-8").splitlines() if log.is_file() else []:
        r = json.loads(line)
        if r.get("purpose", "").startswith("sim"):
            spent += r.get("cost_usd") or 0.0
    return Budget(spent=spent, by_step={"sim": spent})


def _sim_graph():
    from nmt_engine.verify import node_gold

    return node_gold.candidates()[0]


@sim_app.command("ssr-gold")
def sim_ssr_gold(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = SIM_DIR,
    generate: Annotated[
        bool, typer.Option("--generate", help="Kimi writes the 150 answers")
    ] = False,
) -> None:
    """SSR anchor gold: (optionally) generate, record similarities under the anchor hash, check."""
    from nmt_engine.embed import Embedder
    from nmt_engine.llm import AUDITOR
    from nmt_engine.sim import ssr_gold

    if generate:
        llm = _tensorx(AUDITOR, run_dir, max_tokens=8000)
        try:
            typer.echo(json.dumps(ssr_gold.generate(llm, _sim_graph())))
        finally:
            llm.close()
    with Embedder(run_dir) as emb:
        ssr_gold.record(emb, _sim_graph())
    res = ssr_gold.check()
    typer.echo(json.dumps(res, indent=2))
    raise typer.Exit(0 if res["passed"] else 1)


@sim_app.command("world")
def sim_world(
    model: Annotated[str, typer.Option("--model")] = "deepseek/deepseek-v4.1-flash",
    repeats: Annotated[int, typer.Option("--repeats")] = 1,
    harvest_dir: Annotated[Path, typer.Option("--harvest-dir")] = Path("runs/l2"),
    run_dir: Annotated[Path, typer.Option("--run-dir")] = SIM_DIR,
) -> None:
    """Main world: every segment agent on every incumbent it can hold, under every condition."""
    from nmt_engine.embed import Embedder
    from nmt_engine.llm import AUDITOR, PRODUCER, THIRD_MODEL
    from nmt_engine.sim import agents, world
    from nmt_engine.sim.ssr import SSR
    from nmt_engine.verify import gold

    g = _sim_graph()
    reasoning = {THIRD_MODEL: "none", PRODUCER: gold.PRODUCER_REASONING}.get(model)
    budget = _sim_budget(run_dir)
    llm = _tensorx(
        model, run_dir, reasoning, max_tokens=4000 if model == AUDITOR else 1200, budget=budget
    )
    tagger = _tensorx(PRODUCER, run_dir, gold.PRODUCER_REASONING, budget=budget)
    with Embedder(run_dir) as emb:
        pool = agents.user_pool(harvest_dir)
        agents.tag_pool(tagger, pool, "invoicing")
        ags = agents.build(g, emb, pool, support=agents.supporting())
        calib = agents.calibration_record(g, ags)
        (run_dir / "calibration.json").write_text(json.dumps(calib, indent=2), "utf-8")
        cells = world.main_cells(g, ags, repeats)
        out = run_dir / f"world_a6_{model.split('/')[-1]}_r{repeats}.jsonl"
        try:
            rows = world.run(llm, SSR(emb), g, ags, cells, out)
        finally:
            llm.close()
            tagger.close()
    typer.echo(
        json.dumps(
            {
                "cells": len(cells),
                "answered": len(rows),
                "out": str(out),
                "grounding": {a.id: a.quote_ids for a in ags},
                "budget": budget.as_dict(),
            },
            indent=2,
        )
    )


@sim_app.command("replay-events")
def sim_replay_events(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = SIM_DIR,
    until: Annotated[str, typer.Option("--until")] = "20251107",
) -> None:
    """Replay events (amendment 6 rule 5): Wayback candidates, Kimi confirmation, selection."""
    import os

    from nmt_engine.collect.base import Collector
    from nmt_engine.llm import AUDITOR
    from nmt_engine.sim import replay

    out = run_dir / "replay"
    cand = out / "candidates.jsonl"
    if cand.is_file():
        rows = [json.loads(x) for x in cand.read_text("utf-8").splitlines()]
    else:
        c = Collector(out / "store", salt=os.environ.get("NMT_AUTHOR_SALT"))
        rows = replay.discover(c, out, until)
    llm = _tensorx(AUDITOR, run_dir, max_tokens=4000, budget=_sim_budget(run_dir))
    try:
        events = replay.select(rows, lambda rs: replay.confirm(llm, rs, workers=1), workers=9)
    finally:
        llm.close()
    cand.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    doc = {
        "amendment": 6,
        "confirm_prompt_hash": replay.confirm_prompt_hash(),
        "events": [
            {
                k: e[k]
                for k in (
                    "id",
                    "app",
                    "url",
                    "old",
                    "new",
                    "t0",
                    "t1",
                    "gap_days",
                    "freeze",
                    "lines",
                    "quote",
                )
            }
            for e in events
        ],
    }
    (out / "events.json").write_text(json.dumps(doc, indent=2), "utf-8")
    summary = {
        "candidates": len(rows),
        "usable_dates": sum(bool(r.get("usable_dates")) for r in rows),
        "confirmed": sum(bool(r.get("confirmed")) for r in rows),
        "unlabelled": sum(bool(r.get("unlabelled")) for r in rows),
        "events": [e["id"] for e in events],
        "budget": llm.budget.as_dict(),
    }
    typer.echo(json.dumps(summary, indent=2))


@sim_app.command("replay-predict")
def sim_replay_predict(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = SIM_DIR,
    harvest_dir: Annotated[Path, typer.Option("--harvest-dir")] = Path("runs/l2"),
) -> None:
    """Predictions and baselines for every event, written before any outcome post is fetched."""
    import os
    from datetime import UTC, datetime, timedelta

    from nmt_engine.collect.base import Collector
    from nmt_engine.embed import Embedder
    from nmt_engine.llm import PRODUCER
    from nmt_engine.sim import agents, replay
    from nmt_engine.sim.ssr import SSR
    from nmt_engine.store import load_run
    from nmt_engine.verify import gold

    out = run_dir / "replay"
    events = json.loads((out / "events.json").read_text("utf-8"))["events"]
    budget = _sim_budget(run_dir)
    llm = _tensorx(PRODUCER, run_dir, gold.PRODUCER_REASONING, max_tokens=1200, budget=budget)
    c = Collector(out / "store", salt=os.environ.get("NMT_AUTHOR_SALT"))
    harvest = load_run(harvest_dir)
    g = _sim_graph()
    res = []
    with Embedder(run_dir) as emb:
        pool = agents.user_pool(harvest_dir)
        agents.tag_pool(llm, pool, "invoicing")
        support = agents.supporting()
        try:
            for e in events:
                t0 = datetime.fromisoformat(e["t0"]).replace(tzinfo=UTC)
                before = replay.posts(c, harvest, e["app"], t0 - timedelta(days=365), t0)
                base = replay.baseline(e["app"], before)
                pred = replay.predict(llm, SSR(emb), g, emb, pool, support, e)
                res.append({"id": e["id"], "app": e["app"], "baseline": base, "prediction": pred})
                typer.echo(f"{e['id']}: sim {pred['option']} | baseline {base['option']}")
        finally:
            llm.close()
    doc = {"amendment": 6, "written_before_outcomes": True, "events": res}
    (out / "predictions.json").write_text(json.dumps(doc, indent=2, default=str), "utf-8")
    typer.echo(json.dumps({"events": len(res), "budget": budget.as_dict()}, indent=2))


@sim_app.command("replay-outcomes")
def sim_replay_outcomes(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = SIM_DIR,
    harvest_dir: Annotated[Path, typer.Option("--harvest-dir")] = Path("runs/l2"),
    max_usd: Annotated[float, typer.Option("--max-usd")] = 2.0,
) -> None:
    """Outcomes (amendment 6 rule 7), Kimi labels capped at --max-usd, then T3."""
    import os
    from datetime import UTC, datetime, timedelta

    from nmt_engine.collect.base import Collector
    from nmt_engine.llm import AUDITOR
    from nmt_engine.sim import replay
    from nmt_engine.store import load_run

    out = run_dir / "replay"
    preds = json.loads((out / "predictions.json").read_text("utf-8"))["events"]
    events = {e["id"]: e for e in json.loads((out / "events.json").read_text("utf-8"))["events"]}
    budget = _sim_budget(run_dir)
    budget.step_caps["sim"] = min(budget.step_caps["sim"], budget.spent + max_usd)
    llm = _tensorx(AUDITOR, run_dir, max_tokens=6000, budget=budget)
    c = Collector(out / "store", salt=os.environ.get("NMT_AUTHOR_SALT"))
    harvest = load_run(harvest_dir)
    labels_all = {}
    try:
        for p in sorted(preds, key=lambda p: events[p["id"]]["t1"]):
            e = events[p["id"]]
            t1 = datetime.fromisoformat(e["t1"]).replace(tzinfo=UTC)
            rows = replay.posts(c, harvest, e["app"], t1, t1 + timedelta(days=365))
            cand = replay.prefilter(e["app"], rows, e["id"])
            labels = replay.label_outcomes(llm, e["app"], cand)
            labels_all[e["id"]] = labels
            p["outcome"] = replay.votes(cand, labels, e["app"]) | {
                "posts": len(rows),
                "prefiltered": len(cand),
                "unlabelled": sum(v is None for v in labels.values()),
            }
            typer.echo(f"{e['id']}: {json.dumps(p['outcome']['named'])}")
    finally:
        llm.close()
    res = replay.score(preds)
    doc = {
        "amendment": 6,
        "outcome_prompt_hash": replay.outcome_prompt_hash(),
        **res,
        "per_event": [
            {k: p.get(k) for k in ("id", "app", "beats", "outcome")}
            | {"sim": p["prediction"]["option"], "baseline": p["baseline"]["option"]}
            for p in preds
        ],
    }
    (out / "t3.json").write_text(json.dumps(doc, indent=2), "utf-8")
    (out / "outcome_labels.json").write_text(json.dumps(labels_all, indent=2), "utf-8")
    typer.echo(json.dumps({**res, "budget": budget.as_dict()}, indent=2))


if __name__ == "__main__":
    app()


radar_app = typer.Typer(help="B5 Radar inputs (PREREG_v3 amendment 7).", no_args_is_help=True)
app.add_typer(radar_app, name="radar")
B5_DIR = Path("runs/b5")


@radar_app.command("build")
def radar_build(
    harvest: Annotated[Path, typer.Option("--harvest")] = Path("runs/l2"),
    run_dir: Annotated[Path, typer.Option("--run-dir")] = B5_DIR,
) -> None:
    """Pool, producer pass, k=12 problem groups, Kimi group names, alternatives map."""
    from nmt_engine.embed import Embedder
    from nmt_engine.llm import AUDITOR, PRODUCER
    from nmt_engine.radar import build
    from nmt_engine.verify.gold import PRODUCER_REASONING

    run_dir.mkdir(parents=True, exist_ok=True)
    posts = build.pool(harvest)
    cache = run_dir / "radar_posts.jsonl"
    done = {}
    for line in cache.read_text("utf-8").splitlines() if cache.is_file() else []:
        r = json.loads(line)
        done[r["id"]] = r
    if len(done) != len(posts):
        prod = _tensorx(PRODUCER, run_dir, PRODUCER_REASONING)
        build.producer_pass(prod, posts)
        cache.write_text(
            "".join(
                json.dumps({k: p.get(k) for k in ("id", "role", "problem")}) + "\n" for p in posts
            ),
            "utf-8",
        )
    else:
        for p in posts:
            p.update(role=done[p["id"]]["role"], problem=done[p["id"]]["problem"])
    radar = [p for p in posts if p.get("role") == "USER" and p.get("problem")]
    with Embedder(run_dir) as emb:
        gs = build.groups(emb, radar)
    kimi = _tensorx(AUDITOR, run_dir, max_tokens=2000)
    build.name_groups(kimi, gs, {p["id"]: p["text"] for p in radar})
    users = [p for p in posts if p.get("role") == "USER"]
    doc = {
        "pool": len(posts),
        "by_platform": dict(Counter(p["platform"] for p in posts)),
        "unanswered": sum(p.get("role") is None for p in posts),
        "user": len(users),
        "radar": len(radar),
        "radar_authors": len({p["author"] for p in radar}),
        "k": build.K,
        "groups": gs,
        "alternatives": build.alternatives(users),
        "quotes": {i: p["text"][:600] for p in radar for i in [p["id"]]},
        "meta": {
            p["id"]: {k: p[k] for k in ("app", "year", "country", "url", "platform")} for p in radar
        },
    }
    build.write(run_dir / "radar.json", {k: v for k, v in doc.items() if k != "quotes"})
    build.write(run_dir / "radar_quotes.json", doc["quotes"])
    keys = ("pool", "by_platform", "unanswered", "user", "radar", "radar_authors")
    typer.echo(json.dumps({k: doc[k] for k in keys}))


report_app = typer.Typer(help="B6 Groundwork report (ARCHITECTURE_v3 L8).", no_args_is_help=True)
app.add_typer(report_app, name="report")


@report_app.command("build")
def report_build(
    run_dir: Annotated[Path, typer.Option("--run-dir")] = B5_DIR,
    red_team: Annotated[bool, typer.Option("--red-team/--no-red-team")] = True,
) -> None:
    """Packet -> GLM red team (once, cached) -> HTML + PDF in run_dir/reports; then run gates."""
    from nmt_engine.llm import THIRD_MODEL
    from nmt_engine.report import groundwork

    pkt = groundwork.packet()
    (run_dir / "packet.json").write_text(json.dumps(pkt, indent=2, default=str), "utf-8")
    rt_path, rt = run_dir / "redteam.json", None
    if rt_path.is_file():
        rt = json.loads(rt_path.read_text("utf-8"))
    elif red_team:
        llm = _tensorx(THIRD_MODEL, run_dir, "none", max_tokens=6000)
        try:
            rt = groundwork.red_team(llm, pkt)
        finally:
            llm.close()
        rt_path.write_text(json.dumps(rt, indent=2), "utf-8")
    resp = run_dir / "redteam_responses.json"
    if rt and resp.is_file():
        answers = json.loads(resp.read_text("utf-8"))
        for i, f in enumerate(rt.get("overreach") or []):
            f["response"] = answers.get(f.get("where", ""), answers.get(str(i)))
    html = groundwork.render(pkt, rt, run_dir / "reports" / "groundwork.html")
    out = groundwork.pdf(html)
    problems = groundwork.check(html.read_text("utf-8"), pkt)
    typer.echo(json.dumps({"html": str(html), "pdf": str(out) if out else None, "gate": problems}))
    if problems:
        raise typer.Exit(1)
