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
        typer.Option("--only", help="run only steps with these name prefixes, e.g. appstore:,web:"),
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


@app.command("mine")
def mine_cmd(
    run_dir: Path,
    category: Annotated[str, typer.Option("--category")],
    geo: Annotated[str, typer.Option("--geo")] = "IE",
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Skip every LLM step")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Max traces")] = None,
    seed: Annotated[int, typer.Option("--seed")] = 0,
    forbidden_corpus: CorpusOpt = None,
    t_star: Annotated[
        float | None,
        typer.Option("--t-star", help="v2: whole-category embedding clustering cut at this t*"),
    ] = None,
    carry_from: Annotated[
        Path | None,
        typer.Option(help="Earlier run whose traces are extracted first (LLM cache replay)"),
    ] = None,
) -> None:
    """Job-Graph Miner on a collected run: jobs, segments, graph, gates, graph/report HTML."""
    from nmt_engine.embed import Embedder
    from nmt_engine.llm import LLM
    from nmt_engine.miner.cluster import v2_grouper
    from nmt_engine.miner.pipeline import mine

    llm = LLM(run_dir, no_llm=no_llm)
    embedder = Embedder(run_dir) if t_star is not None else None
    grouper = v2_grouper(embedder, t_star, category) if embedder else None
    try:
        summary = mine(
            run_dir,
            category,
            llm,
            geo,
            limit,
            seed,
            _cfg(forbidden_corpus),
            grouper=grouper,
            carry_from=carry_from,
        )
    finally:
        llm.close()
        if embedder:
            embedder.close()
    typer.echo(json.dumps(summary, indent=2, sort_keys=True, default=str))
    raise typer.Exit(0 if summary.get("status") in ("ok", "skipped") else 1)


@app.command("killline")
def killline_cmd(
    run_dirs: list[Path],
    out: Annotated[Path | None, typer.Option(help="Write the table to this .md file")] = None,
) -> None:
    """Kill-line table over mined runs (one per category)."""
    from nmt_engine.miner.killline import killline

    table, verdict = killline(run_dirs)
    text = table + "\n\n" + verdict + "\n"
    if out:
        out.write_text(text, "utf-8")
    typer.echo(text)


if __name__ == "__main__":
    app()
