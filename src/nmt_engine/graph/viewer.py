"""Self-contained graph.html (Cytoscape.js 3.30.2 inlined) and report.html."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from nmt_engine.gates.g08_validation_lint import offending_sentences
from nmt_engine.store import RunData

CYTOSCAPE_VERSION = "3.30.2"
_ENV = Environment(
    loader=PackageLoader("nmt_engine.graph", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    keep_trailing_newline=True,
)


def cytoscape_js() -> str:
    return (
        resources.files("nmt_engine.graph")
        .joinpath(f"static/cytoscape-{CYTOSCAPE_VERSION}.min.js")
        .read_text("utf-8")
    )


def _script_json(data: object) -> str:
    """JSON safe to embed in a <script> element."""
    text = json.dumps(data, sort_keys=True)
    for ch, esc in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        text = text.replace(ch, esc)
    return text


def write_graph_html(graph: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    html = _ENV.get_template("graph.html.j2").render(
        graph_json=_script_json(graph),
        cytoscape=cytoscape_js(),
        version=CYTOSCAPE_VERSION,
        n_nodes=len(graph["nodes"]),
        n_edges=len(graph["edges"]),
    )
    path.write_text(html, "utf-8")
    return path


def receipts(run: RunData, claim_id: str, shown: set[str], limit: int = 3) -> list[dict]:
    """Up to `limit` verbatim receipts of a displayable claim (quotes that would trip the
    validation-language lint are left out of the report, not reworded)."""
    c = run.claims.get(claim_id)
    if c is None or claim_id not in shown:
        return []
    out = []
    for r in c.source_refs:
        src = run.sources.get(r.source_id)
        if src is None or src.retracted or offending_sentences(r.verbatim, set()):
            continue
        out.append({"quote": r.verbatim, "url": src.url, "kind": src.kind})
        if len(out) >= limit:
            break
    return out


def write_report_html(
    summary: dict, table: list[dict], graph: dict, run: RunData, shown: set[str], path: Path
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    jobs = []
    for row in sorted(table, key=lambda r: (not r["passes"], -len(r["elements"]), r["job_id"])):
        jid = row["job_id"]
        node = next((n for n in graph["nodes"] if n["id"] == jid), {})
        jobs.append(
            {
                **row,
                "importance": node.get("importance"),
                "consideration": graph["consideration_sets"].get(jid, []),
                "receipts": {
                    el: receipts(run, f"c_{jid}_{el}", shown)
                    for el in (*row["elements"], "problem", "aha", "workaround")
                },
            }
        )
    breaks = [e for e in graph["edges"] if e["break"]]
    segs = sorted(
        (s for s in run.segments.values() if not s.retracted), key=lambda s: (s.thin, s.id)
    )
    html = _ENV.get_template("report.html.j2").render(
        s=summary, jobs=jobs, breaks=breaks, segments=segs, labels=_labels(graph)
    )
    path.write_text(html, "utf-8")
    return path


def _labels(graph: dict) -> dict[str, str]:
    return {n["id"]: n["label"] for n in graph["nodes"]}
