"""Kill line v2 report (PREREG_killline_v2.md §7-§8). Usage: v2_report.py LABELS_DIR ABLATION_DIR

R0 = Session A runs (~/nmt-live); R1 and R2 are one mined copy of R0 with clustering, scored on
source kinds (R1) and customer-voice families (R2); R3 = clustered mining of the R3 collection;
R4 = R3 with the label-audit exclusions. Robustness re-mines R3 at t* -/+ 0.05.
Without agreement.json (pairs_ok) or specificity.json for every category the verdict is
STOPPED or PENDING by design: the human checkpoint is not done, which is not a kill-line result."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from nmt_engine.miner.killline import KILL_LINE, score_v2, verdict_v2

CATS = (
    ("habit-tracker", "habit-tracker"),
    ("feature-flags", "feature-flags"),
    ("invoicing", "invoicing-deepseek"),
)
R0 = Path.home() / "nmt-live"
R3 = Path.home() / "nmt-v2" / "r3"
FAMILIES = (
    "discussion",
    "support_issue",
    "qa",
    "review",
    "vendor_page",
    "change_history",
    "search_demand",
    "market_record",
)
PREREG = Path(__file__).resolve().parents[1] / "docs" / "PREREG_killline_v2.md"


def summary(d: Path) -> dict:
    f = d / "mine_summary.json"
    if not f.is_file():
        sys.exit(f"missing {f}: run scripts/v2_ablate.sh first")
    return json.loads(f.read_text("utf-8"))


def cost(s: dict) -> float:
    return round(s.get("cost_usd", 0) + (s.get("grouping") or {}).get("embed_cost_usd", 0), 4)


def pct(x) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def main(labels: Path, abl: Path) -> None:
    th = json.loads((labels / "threshold.json").read_text("utf-8"))
    au = json.loads((labels / "audit.json").read_text("utf-8"))
    ag_p = labels / "agreement.json"
    agree = json.loads(ag_p.read_text("utf-8")) if ag_p.is_file() else {}
    spec_p = labels / "specificity.json"  # {category: number of top-10 clusters judged too broad}
    broad = json.loads(spec_p.read_text("utf-8")) if spec_p.is_file() else {}
    excluded = frozenset(au["excluded"])
    out = [f"PREREG_killline_v2.md sha256 `{hashlib.sha256(PREREG.read_bytes()).hexdigest()}`", ""]
    out += [
        "| category | run | clusters | denominator | v1 share | v2 share | v2 weighted | "
        "largest | over-merged | cost | time |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    r4, raw, lo, hi, tops, extra = {}, {}, {}, {}, {}, []
    for name, r0 in CATS:
        s0 = summary(R0 / r0)
        out.append(
            f"| {name} | R0 | {s0['jobs']} | - | {pct(s0['share_passing'])} | - | - | - | - "
            f"| ${cost(s0)} | {s0['runtime_s']:.0f} s |"
        )
        d12, d34 = abl / f"r12-{name}", abl / f"r34-{name}"
        s12, s34 = summary(d12), summary(d34)
        v12 = score_v2(d12)
        v3, v4 = score_v2(d34), score_v2(d34, excluded)
        rows = (
            ("R1", v12, "v2_kinds_share", s12),
            ("R2", v12, "v2_share", s12),
            ("R3", v3, "v2_share", s34),
            ("R4", v4, "v2_share", s34),
        )
        for run, v, key, s in rows:
            share = v[key]
            out.append(
                f"| {name} | {run} | {v['jobs']} | {v['denominator']} | {pct(v['v1_share'])} | "
                f"{pct(share)} | {pct(v['v2_weighted_share'])} | {v['largest']} "
                f"({pct(v['largest_share'])}) | {'yes' if v['over_merged'] else 'no'} | "
                f"{'$' + str(cost(s)) if run in ('R1', 'R3') else '-'} | "
                f"{str(round(s['runtime_s'])) + ' s' if run in ('R1', 'R3') else '-'} |"
            )
        ok = lambda v: None if v["over_merged"] else v["v2_share"]  # noqa: E731
        raw[name] = ok(v4)
        r4[name] = None if broad.get(name, 0) > 3 else raw[name]
        dlo, dhi = abl / f"r34lo-{name}", abl / f"r34hi-{name}"
        summary(dlo), summary(dhi)
        lo[name] = ok(score_v2(dlo, excluded))
        hi[name] = ok(score_v2(dhi, excluded))
        tops[name] = v4["top"]
        extra.append((name, v3, v4))
    # Robustness compares the three thresholds under one rule (no specificity review, which
    # judged the t* clusters only); the specificity rule then applies to the t* verdict.
    verdicts = {k: verdict_v2(v) for k, v in (("t*", raw), ("t*-0.05", lo), ("t*+0.05", hi))}
    hit = {k: v.startswith("KILL LINE v2 HIT") for k, v in verdicts.items()}
    final = verdict_v2(r4) if len(set(hit.values())) == 1 else "Kill line v2 UNDECIDABLE"
    # A category with no passing R4 cluster has nothing to review and is already below 30%.
    unreviewed = [name for name, _ in CATS if name not in broad and tops[name]]
    if not agree.get("pairs_ok"):
        got = agree.get("pairs", {}).get("agreement")
        final = f"STOPPED: human pair agreement {got} is not >= 80% (or not recorded); no verdict"
    elif unreviewed:
        final = f"PENDING: no top-10 specificity review for {', '.join(unreviewed)}; no verdict"
    out += ["", f"**Verdict (R4, kill line {KILL_LINE:.0%}):** {final}", ""]
    tag = "provisional, " if final.startswith(("STOPPED", "PENDING")) else ""
    out.append(
        f"- t* after specificity review ({tag}R4): "
        + ", ".join(f"{c} {pct(s)}" for c, s in r4.items())
    )
    out += [
        f"- {k} ({tag}before specificity review): {v}  shares "
        + ", ".join(f"{c} {'over-merged' if s is None else pct(s)}" for c, s in d.items())
        for (k, v), d in zip(verdicts.items(), (raw, lo, hi), strict=True)
    ]
    out += [
        "",
        f"Threshold t* = {th['t_star']} (F1 {th['f1']:.3f}, precision {th['precision']:.3f}, "
        f"recall {th['recall']:.3f}) on {th['labelled']} auditor-labelled pairs; "
        f"human agreement pairs {agree.get('pairs', {}).get('agreement')}, "
        f"spans {agree.get('spans', {}).get('agreement')}.",
        "",
    ]
    out += [
        "| element | audited | mislabelled | rate | 95% Wilson | excluded |",
        "|---|---:|---:|---:|---|---|",
    ]
    for e, r in au["rates"].items():
        lo95, hi95 = r["wilson95"]
        out.append(
            f"| {e} | {r['n']} | {r['mislabelled']} | {pct(r['rate'])} | "
            f"{lo95:.1%}-{hi95:.1%} | {'yes' if r['excluded'] else 'no'} |"
        )
    out += collection_section() + roles_section(labels) + labels_cost_section(labels, th, au)
    for name, v3, v in extra:
        out += [
            "",
            f"### {name}",
            "",
            f"levels {v['levels']}, level disagreement "
            f"{pct(v['level_disagreement'])}, mixed {v['mixed']}, sizes {v['sizes']}",
            "",
        ]
        out += [
            "| # | cluster | level | voices | posts | families |",
            "|---|---|---|---:|---:|---|",
        ]
        rows = [("R4", r) for r in tops[name]] or [("R3", r) for r in v3["top"]]
        if not tops[name]:
            out.append(
                "| - | no R4 cluster passes; R3 (no audit exclusions, reported only): | | | | |"
            )
        for n, (_run, r) in enumerate(rows, 1):
            out.append(
                f"| {n} | {r['statement']} | {r['level']} | {r['voices']} | "
                f"{r['cluster_posts']} | {', '.join(r['families'])} |"
            )
    print("\n".join(out))


def collection_section() -> list[str]:
    out = ["", "### R3 collection (sources by family; adapters with 0 or skipped listed)", ""]
    out += [
        "| category | " + " | ".join(FAMILIES) + " | customer voice |",
        "|---|" + "---:|" * (len(FAMILIES) + 1),
    ]
    notes = []
    for name, _ in CATS:
        c = json.loads((R3 / name / "collect_summary.json").read_text("utf-8"))
        fam = c["sources_by_family"]
        out.append(
            f"| {name} | "
            + " | ".join(str(fam.get(f, 0)) for f in FAMILIES)
            + f" | {c['trace_sources']} |"
        )
        ad = c["adapters"]
        ok = ", ".join(
            f"{k} {v['sources']}"
            for k, v in sorted(ad.items())
            if v["status"] == "ok" and v.get("sources")
        )
        off = ", ".join(
            sorted(k for k, v in ad.items() if v["status"] != "ok" or not v.get("sources"))
        )
        notes.append(f"- {name}: {ok}. None: {off}.")
    return out + [""] + notes


def roles_section(labels: Path) -> list[str]:
    f = labels / "roles.json"
    if not f.is_file():
        return ["", "Builder-vs-user diagnostic: not run (v2_label.py roles)."]
    r = json.loads(f.read_text("utf-8"))
    row = lambda k, v: f"| {k} | {v['n']} | {v['builder']} | {pct(v['share'])} |"  # noqa: E731
    out = [
        "",
        "### Diagnostic (not part of the verdict): audited spans whose author builds a "
        "product in the category",
        "",
        "| group | n | builder | share |",
        "|---|---:|---:|---:|",
    ]
    out += [row("all spans", r["spans"]), row("distinct posts", r["posts"])]
    out += [row(c, v) for c, v in r["by_category"].items()]
    out += [row(e, v) for e, v in r["by_element"].items()]
    return out + [
        "",
        f"Auditor {r['auditor']}, {r['auditor_calls']} calls, "
        f"${r['auditor_cost_usd']}, {r['runtime_s']:.0f} s.",
    ]


def labels_cost_section(labels: Path, th: dict, au: dict) -> list[str]:
    ex = json.loads((labels / "extraction.json").read_text("utf-8"))["stats"]
    out = ["", "### Label-stage costs (all logged calls, including retries and cache misses)", ""]
    by: dict[str, list[float]] = {}
    for line in (labels / "llm_log.jsonl").read_text("utf-8").splitlines():
        r = json.loads(line)
        if not r.get("cached"):
            v = by.setdefault(f"{r['purpose']} ({r['model']})", [0, 0.0])
            v[0] += 1
            v[1] += r.get("cost_usd") or 0
    out += [f"- {k}: {n} calls, ${c:.4f}" for k, (n, c) in sorted(by.items())]
    out += [
        f"- extraction replay {c}: {s['instances']} instances, {s['spans_rejected']} of "
        f"{s['spans_proposed']} spans rejected as non-verbatim, ${s['cost_usd']}, "
        f"{s['runtime_s']:.0f} s"
        for c, s in ex.items()
    ]
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
