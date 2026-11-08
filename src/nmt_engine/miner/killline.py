"""Kill line (PRODUCT.md D1): share of extracted Jobs with >=4 of 8 elements evidenced and
>=2 source types. Below 30% in 2 of 3 categories -> reposition as Problems & Consideration Sets."""

from __future__ import annotations

import json
from pathlib import Path

from nmt_engine.miner.pipeline import KILL_LINE


def killline(run_dirs: list[Path]) -> tuple[str, str]:
    rows = [
        "| category | traces | jobs | thin jobs | jobs meeting bar | share | cost (USD) "
        "| run time (s) |"
    ]
    rows.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    below = done = 0
    for d in run_dirs:
        p = Path(d) / "mine_summary.json"
        s = json.loads(p.read_text("utf-8")) if p.is_file() else {"status": "missing"}
        cat = s.get("category", Path(d).name)
        if s.get("status") != "ok":
            rows.append(
                f"| {cat} | {s.get('traces', '-')} | - | - | - "
                f"| not run ({s.get('status')}) | - | - |"
            )
            continue
        done += 1
        n = s.get("unpriced_llm_calls") or 0
        unpriced = f" + {n} unpriced calls" if n else ""
        below += s["share_passing"] < KILL_LINE
        rows.append(
            f"| {cat} | {s['traces']} | {s['jobs']} | {s.get('thin_jobs', '-')} | "
            f"{s['jobs_passing']} | "
            f"{100 * s['share_passing']:.1f}% | {s['cost_usd']:.2f}{unpriced} | "
            f"{s['runtime_s']:.0f} |"
        )
    if done < 3:
        verdict = f"Kill line not decidable: {done} of 3 categories mined."
    elif below >= 2:
        verdict = (
            f"KILL LINE HIT: {below} of {done} categories below {KILL_LINE:.0%}. "
            "Narrow to Problems + Consideration Sets (Radar-first)."
        )
    else:
        verdict = f"Kill line passed: {below} of {done} categories below {KILL_LINE:.0%}."
    return "\n".join(rows), verdict
