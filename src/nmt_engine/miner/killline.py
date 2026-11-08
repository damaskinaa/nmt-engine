"""Kill line (PRODUCT.md D1): share of extracted Jobs with >=4 of 8 elements evidenced and
>=2 source types. Below 30% in 2 of 3 categories -> reposition as Problems & Consideration Sets."""

from __future__ import annotations

import json
from collections import Counter
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


SIZE_BINS = ((1, 1), (2, 2), (3, 5), (6, 10), (11, 25), (26, 10**9))


def size_bins(sizes: list[int]) -> dict[str, int]:
    out = {}
    for lo, hi in SIZE_BINS:
        label = str(lo) if lo == hi else (f"{lo}+" if hi >= 10**9 else f"{lo}-{hi}")
        out[label] = sum(lo <= s <= hi for s in sizes)
    return out


def score_v2(run_dir: Path, excluded: frozenset[str] = frozenset()) -> dict:
    """PREREG_killline_v2.md §4 and §7 metrics for one mined run.

    Cluster sizes, posts and mixed flags come from `clusters.json` (written by `mine`); a v1
    run without it counts each job's posts from its element receipts and sizes as unknown."""
    from nmt_engine.miner.pipeline import OVER_MERGED, V2_LEVELS, evidence_table
    from nmt_engine.store import load_run

    run_dir = Path(run_dir)
    p = run_dir / "clusters.json"
    clusters = {c["job_id"]: c for c in json.loads(p.read_text("utf-8"))} if p.is_file() else {}
    mixed = frozenset(j for j, c in clusters.items() if c.get("mixed"))
    run = load_run(run_dir)
    table = evidence_table(run, set(clusters) or None, mixed, excluded)
    for r in table:
        c = clusters.get(r["job_id"], {})
        r["cluster_posts"] = c.get("posts", r["posts"])
        r["instances"] = c.get("instances")
    denom = [r for r in table if r["level"] in V2_LEVELS]
    passing = [r for r in denom if r["passes_v2"]]
    posts_all = sum(r["cluster_posts"] for r in denom)
    sizes = [r["instances"] for r in table if r["instances"] is not None]
    n_inst = sum(sizes)
    largest = max(sizes, default=0)
    levels = Counter(r["level"] for r in table)
    disagree = sum(
        n
        for c in clusters.values()
        for lv, n in c.get("instance_levels", {}).items()
        if lv != c["level"]
    )
    return {
        "jobs": len(table),
        "v1_passing": sum(r["passes"] for r in table),
        "v1_share": round(sum(r["passes"] for r in table) / len(table), 4) if table else 0.0,
        "denominator": len(denom),
        "v2_passing": len(passing),
        "v2_share": round(len(passing) / len(denom), 4) if denom else 0.0,
        "v2_kinds_share": round(sum(r["passes_v2_kinds"] for r in denom) / len(denom), 4)
        if denom
        else 0.0,
        "v2_weighted_share": round(sum(r["cluster_posts"] for r in passing) / posts_all, 4)
        if posts_all
        else 0.0,
        "mixed": len(mixed),
        "levels": dict(sorted(levels.items())),
        "instances": n_inst or None,
        "level_disagreement": round(disagree / n_inst, 4) if n_inst else None,
        "sizes": size_bins(sizes) if sizes else None,
        "largest": largest or None,
        "largest_share": round(largest / n_inst, 4) if n_inst else None,
        "over_merged": bool(n_inst) and largest / n_inst > OVER_MERGED,
        "excluded": sorted(excluded),
        "top": sorted(passing, key=lambda r: (-r["voices"], -r["cluster_posts"], r["job_id"]))[:10],
    }


def verdict_v2(shares: dict[str, float | None]) -> str:
    """Kill line v2 over per-category v2 shares (None = not counted as a pass, e.g. over-merged
    or too broad, which §7 treats as below 30%)."""
    below = sum(s is None or s < KILL_LINE for s in shares.values())
    if len(shares) < 3:
        return f"Kill line v2 not decidable: {len(shares)} of 3 categories scored."
    if below >= 2:
        return (
            f"KILL LINE v2 HIT: {below} of {len(shares)} categories below {KILL_LINE:.0%}. "
            "Narrow to Problems + Consideration Sets (Radar-first)."
        )
    return f"Kill line v2 passed: {below} of {len(shares)} categories below {KILL_LINE:.0%}."
