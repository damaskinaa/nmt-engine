"""`nmt` command-line interface."""

from __future__ import annotations

import json
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
    from nmt_engine.llm import PRODUCER, THIRD_MODEL
    from nmt_engine.sim import agents, world
    from nmt_engine.sim.ssr import SSR
    from nmt_engine.verify import gold

    g = _sim_graph()
    reasoning = {THIRD_MODEL: "none", PRODUCER: gold.PRODUCER_REASONING}.get(model)
    llm = _tensorx(model, run_dir, reasoning, max_tokens=1200)
    with Embedder(run_dir) as emb:
        ags = agents.build(g, emb, agents.user_pool(harvest_dir))
        cells = world.main_cells(g, ags, repeats)
        out = run_dir / f"world_{model.split('/')[-1]}_r{repeats}.jsonl"
        try:
            rows = world.run(llm, SSR(emb), g, ags, cells, out)
        finally:
            llm.close()
    grounding = {a.id: a.quote_ids for a in ags}
    typer.echo(
        json.dumps(
            {
                "cells": len(rows),
                "out": str(out),
                "grounding": grounding,
                "budget": llm.budget.as_dict(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
