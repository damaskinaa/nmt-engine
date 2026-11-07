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


if __name__ == "__main__":
    app()
