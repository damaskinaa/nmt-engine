"""Groundwork report packet, red team and HTML/PDF (ARCHITECTURE_v3 L7-L8; amendments 6-7).

Every figure here is read from a committed or logged artefact; nothing is hand-typed except
fixed wording. Simulation output appears only in its own section, labelled SYNTHETIC."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

import numpy as np
from jinja2 import Environment, FileSystemLoader, select_autoescape

from nmt_engine.decide import chain
from nmt_engine.sim.agents import _mask
from nmt_engine.sim.stability import internal_validity
from nmt_engine.sim.world import CLAIM_LABEL, CONDITIONS
from nmt_engine.synth.grade import GradeInputs
from nmt_engine.verify import node_gold

L4_AUTHORS = 3
NO_INPUT = "no input of any family was collected in B1-B4"
Q_NOTES = {
    "Q1": (NO_INPUT, "needs an official statistics count of the segment"),
    "Q2": (NO_INPUT,),
    "Q3": (NO_INPUT,),
    "Q4": (
        "simulated family dropped: cross-model rho below 0.5 and SSR gold failed",
        "list prices of 9 alternatives exist as Wayback snapshots (B4 replay) but are not "
        "extracted into a recomputable calculation",
    ),
    "Q5": (NO_INPUT,),
    "Q6": (NO_INPUT,),
    "Q7": ("simulated family dropped: cross-model rho below 0.5 and SSR gold failed",),
    "Q8": (NO_INPUT,),
    "Q9": (NO_INPUT,),
}
TOUCH = (
    "T4 landing-page test (not run yet; B7): 3 headlines, EUR 49 vs EUR 149, "
    "about 200 founders or PMs"
)


def _load(p: Path):
    return json.loads(p.read_text("utf-8"))


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]


def quantities() -> dict[str, chain.Quantity]:
    return {
        q: chain.Quantity(q, GradeInputs(anchored=False), None, Q_NOTES[q]) for q in chain.CHAIN
    }


def riskiest(graph_path: Path = node_gold.GRAPH) -> list[dict]:
    g = _load(graph_path)
    counts = node_gold.per_node()
    out = []
    for r in g["riskiest"]:
        c = counts.get(r["id"], {})
        sup, con = c.get("supports", 0), c.get("contradicts", 0)
        if sup >= L4_AUTHORS or con >= L4_AUTHORS:
            raise ValueError(f"{r['id']}: B3 status is fixed at unknown")
        out.append(
            {
                "id": r["id"],
                "type": r["type"],
                "text": r["text"],
                "priority": r["priority"],
                "status": "unknown",
                "supports": sup,
                "contradicts": con,
                "evidence": (
                    f"{sup} supporting post{'s' if sup != 1 else ''}, below the bar"
                    if sup
                    else "no public evidence in this harvest"
                ),
                "test": (
                    "Supported only if at least 3 distinct authors in at least 2 customer-voice "
                    "families (reviews plus a user community) describe it; contradicted on the "
                    f"same bar. Now: {sup} supporting, {con} contradicting."
                ),
            }
        )
    return out


ENTRANT_NOTE = (
    "The new app was not one of the switch destinations SSR scored (B4 offered only existing "
    "options), so switching to it is undercounted here."
)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def simulation(b4: Path) -> dict:
    rows = _jsonl(b4 / "world_a6_deepseek-v4.1-flash_r3.jsonl")
    rng = np.random.default_rng(0)
    conds = []
    for cond in CONDITIONS:
        ps = np.array([r["p_switch"] for r in rows if r["condition"] == cond])
        boot = rng.choice(ps, (2000, len(ps))).mean(axis=1)
        lo, hi = np.percentile(boot, [10, 90])
        conds.append(
            {
                "condition": cond,
                "text": _cap(
                    CONDITIONS[cond].format(inc="the current app", job="get paid", rival="a rival")
                ),
                "p_switch": round(float(ps.mean()), 3),
                "interval80": [round(float(lo), 3), round(float(hi), 3)],
                "cells": int(len(ps)),
                "label": CLAIM_LABEL,
                "note": ENTRANT_NOTE if cond == "entrant" else None,
            }
        )
    cal = _load(b4 / "calibration.json")
    calibrated_on = sorted({q["id"] for qs in cal["agents"].values() for q in qs})
    return {
        "status": "exploratory, unvalidated",
        "model": "deepseek/deepseek-v4.1-flash, 3 repeats",
        "conditions": conds,
        "validity": internal_validity(rows),
        "stability": _load(b4 / "stability_a6.json"),
        "t3": {k: v for k, v in _load(b4 / "replay" / "t3.json").items() if k != "per_event"},
        "calibration": {k: v for k, v in cal.items() if k != "agents"},
        "calibrated_on": calibrated_on,
    }


def radar(b5: Path) -> dict:
    r = _load(b5 / "radar.json")
    quotes = _load(b5 / "radar_quotes.json")
    for g in r["groups"]:
        pid = g.get("quote_post")
        g["receipt"] = r["meta"][pid]["url"] if pid else None
        g["quote"] = _mask(g["quote"]) if g.get("quote") else None
        g["verbatim"] = bool(pid) and _nfc(g["quote"]) in _nfc(_mask(quotes[pid]))
        g["examples"] = [
            {"text": _mask(quotes[i])[:240], "url": r["meta"][i]["url"]} for i in g["nearest"][:3]
        ]
        g.pop("members", None)
    r.pop("meta", None)
    return r


def packet(root: Path = Path("."), b5: Path | None = None) -> dict:
    b4, b5 = root / "runs" / "b4", b5 or root / "runs" / "b5"
    qs = quantities()
    blocked = chain.can_run(qs)
    mc = None if blocked else chain.monte_carlo(qs, chain.Targets())
    t1 = _load(root / "runs" / "t1.json")
    risk = riskiest()
    return {
        "market": "invoicing",
        "scope": "Radar (problems and alternatives); T2 failed, so no Job node has a status",
        "status": {
            "supported": sum(n["status"] == "supported" for n in risk),
            "contradicted": sum(n["status"] == "contradicted" for n in risk),
            "no_public_evidence": sum(n["supports"] == 0 and n["contradicts"] == 0 for n in risk),
            "nodes": len(risk),
            "human_check": "NOT DONE",
            "gold": t1["gold_provenance"],
        },
        "t1": {c: v["test"] for c, v in t1["classes"].items()},
        "riskiest": risk,
        "radar": radar(b5),
        "quantities": [q.row() for q in qs.values()],
        "monte_carlo": mc or {"ran": False, "blocked_by": blocked},
        "touch": TOUCH,
        "simulation": simulation(b4),
    }


RT_SYSTEM = (
    "You are a red-team reviewer of a market research report. You see only the JSON packet the "
    "report is built from. Be specific and short. Answer only with JSON."
)
RT_PROMPT = """Packet:
{packet}

1. List every claim in the packet that says more than its receipts or numbers support.
2. Is there a single input whose change would flip the report's conclusion (no node is supported,
   no money figure, NO GO to build, run the market touch first)? Name it, or say none.
Answer as JSON: {{"overreach": [{{"where": "...", "claim": "...", "why": "..."}}],
"flip": {{"exists": true or false, "input": "...", "why": "..."}}}}"""


def red_team(llm, pkt: dict) -> dict:
    body = json.dumps(pkt, default=str)
    a = llm.complete_json(RT_PROMPT.format(packet=body), RT_SYSTEM, "redteam.report")
    if not isinstance(a, dict):
        raise ValueError("red team answer is not an object")
    return a


def decide(pkt: dict, rt: dict | None) -> dict:
    qs = quantities()
    flip = None if rt is None else bool((rt.get("flip") or {}).get("exists"))
    mc = pkt["monte_carlo"] if pkt["monte_carlo"].get("ran", True) else None
    v = chain.validate(qs, mc, flip)
    return v | {"decision": chain.decision(v["validated"], None, 0.0), "evpi": "not computed"}


def render(pkt: dict, rt: dict | None, out: Path) -> Path:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
    )
    html = env.get_template("groundwork.html.j2").render(
        p=pkt, rt=rt, d=decide(pkt, rt), label=CLAIM_LABEL
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, "utf-8")
    return out


def pdf(html: Path) -> Path | None:
    exe = next((shutil.which(b) for b in ("google-chrome", "chromium") if shutil.which(b)), None)
    if exe is None:
        return None
    out = html.with_suffix(".pdf")
    subprocess.run(
        [
            exe,
            "--headless=new",
            "--no-pdf-header-footer",
            f"--print-to-pdf={out.resolve()}",
            html.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return out


FORBIDDEN = (
    "customers want",
    "human-verified",
    "validated simulation",
    "simulation is validated",
    "market size",
    "will pay",
)
PAGE_ONE = ("0 of 10", "7 of 10", "NOT DONE", "exploratory and unvalidated", "No money figure")


def _section(html: str, sid: str) -> str | None:
    m = re.search(rf'<section[^>]*\bid="{sid}"[^>]*>(.*?)</section>', html, re.S)
    return m.group(1) if m else None


def check(html: str, pkt: dict) -> list[str]:
    """Report gates: page-1 facts, banned claims, labelled synthetic rows, receipts on quotes.
    The banned-claim negation test (not/no/never in the 40 chars before) is a heuristic tripwire."""
    problems = []
    first, sim = _section(html, "page1"), _section(html, "simulation")
    if first is None or sim is None:
        problems.append("page 1 or simulation section not found")
    problems += [f"page 1 lacks {s!r}" for s in PAGE_ONE if s not in (first or "")]
    text = re.sub(r"<[^>]+>", " ", html).lower()
    for s in FORBIDDEN:
        for m in re.finditer(re.escape(s), text):
            if not re.search(r"\b(not|no|never)\b", text[max(0, m.start() - 40) : m.start()]):
                problems.append(f"banned claim {s!r}")
    if pkt["status"]["supported"] or pkt["status"]["contradicted"]:
        problems.append("a node has a status; B3 fixed all 10 at unknown")
    sim = sim or ""
    rows = sim.count("<tr><td>")
    if rows != len(pkt["simulation"]["conditions"]) or sim.count(CLAIM_LABEL) < rows:
        problems.append("a simulation row lacks its SYNTHETIC label")
    quotes, receipts = html.count("<blockquote>"), html.count(">receipt</a>")
    bad = [g["name"] for g in pkt["radar"]["groups"] if g.get("quote") and not g["verbatim"]]
    problems += [f"quote not verbatim in its receipt: {n}" for n in bad]
    if quotes != receipts:
        problems.append(f"{quotes - receipts} quotes without a receipt")
    if pkt["monte_carlo"].get("ran") and not pkt["monte_carlo"].get("interval80"):
        problems.append("money figure without an interval")
    return problems
