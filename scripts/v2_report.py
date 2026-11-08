"""Kill line v2 report (PREREG_killline_v2.md §7-§8). Usage: v2_report.py LABELS_DIR ABLATION_DIR

R0 = Session A runs (~/nmt-live); R1 and R2 are one mined copy of R0 with clustering, scored on
source kinds (R1) and customer-voice families (R2); R3 = clustered mining of the R3 collection;
R4 = R3 with the label-audit exclusions. Robustness re-mines R3 at t* -/+ 0.05."""

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
PREREG = Path(__file__).resolve().parents[1] / "docs" / "PREREG_killline_v2.md"


def summary(d: Path) -> dict:
    return json.loads((d / "mine_summary.json").read_text("utf-8"))


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
    r4, lo, hi, tops, extra = {}, {}, {}, {}, []
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
        too_broad = broad.get(name, 0) > 3
        r4[name] = None if too_broad else ok(v4)
        vlo, vhi = (
            score_v2(abl / f"r34lo-{name}", excluded),
            score_v2(abl / f"r34hi-{name}", excluded),
        )
        lo[name] = None if too_broad else ok(vlo)
        hi[name] = None if too_broad else ok(vhi)
        tops[name] = v4["top"]
        extra.append((name, s34, v4))
    verdicts = {k: verdict_v2(v) for k, v in (("t*", r4), ("t*-0.05", lo), ("t*+0.05", hi))}
    hit = {k: v.startswith("KILL LINE v2 HIT") for k, v in verdicts.items()}
    final = verdicts["t*"] if len(set(hit.values())) == 1 else "Kill line v2 UNDECIDABLE"
    unreviewed = [name for name, _ in CATS if name not in broad]
    if not agree.get("pairs_ok"):
        got = agree.get("pairs", {}).get("agreement")
        final = f"STOPPED: human pair agreement {got} is not >= 80% (or not recorded); no verdict"
    elif unreviewed:
        final = f"PENDING: no top-10 specificity review for {', '.join(unreviewed)}; no verdict"
    out += ["", f"**Verdict (R4, kill line {KILL_LINE:.0%}):** {final}", ""]
    out += [
        f"- {k}: {v}  shares " + ", ".join(f"{c} {pct(s)}" for c, s in d.items())
        for (k, v), d in zip(verdicts.items(), (r4, lo, hi), strict=True)
    ]
    out += [
        "",
        f"Threshold t* = {th['t_star']} (F1 {th['f1']}, precision {th['precision']}, "
        f"recall {th['recall']}) on {th['labelled']} auditor-labelled pairs; "
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
    for name, _s, v in extra:
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
        for n, r in enumerate(tops[name], 1):
            out.append(
                f"| {n} | {r['statement']} | {r['level']} | {r['voices']} | "
                f"{r['cluster_posts']} | {', '.join(r['families'])} |"
            )
    print("\n".join(out))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
