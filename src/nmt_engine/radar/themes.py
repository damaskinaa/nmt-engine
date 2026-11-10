"""Merged themes and single-app concentration (PREREG_v3 amendment 8 rules 1-2)."""

from __future__ import annotations

from collections import Counter

import numpy as np

MERGE_QUANTILE = 0.25
ONE_APP = 0.5


def centroids(groups: list[dict], vec: dict[str, np.ndarray]) -> np.ndarray:
    c = np.array([np.mean([vec[i] for i in g["members"]], axis=0) for g in groups])
    return c / np.linalg.norm(c, axis=1, keepdims=True)


def merge(cent: np.ndarray) -> tuple[list[int], float]:
    """Average linkage on cosine distance, cut at the 25th percentile of pairwise distances."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    d = pdist(cent, "cosine")
    t = float(np.quantile(d, MERGE_QUANTILE))
    lab = fcluster(linkage(cent, method="average", metric="cosine"), t, criterion="distance")
    return [int(x) for x in lab], t


def concentration(authors: dict[str, set[str]]) -> dict:
    """Share of distinct authors who reviewed the largest app; flag over 50%."""
    total = len(set().union(*authors.values())) if authors else 0
    app, n = max(((a, len(s)) for a, s in authors.items()), key=lambda x: (x[1], x[0]))
    share = round(n / total, 4) if total else 0.0
    return {
        "top_app": app,
        "top_share": share,
        "flag": f"mostly one app: {app}" if share > ONE_APP else None,
    }


def themes(groups: list[dict], vec: dict[str, np.ndarray], post: dict[str, dict]) -> dict:
    """`post` maps id -> {author, app}. Returns the merged themes plus per-group concentration."""
    lab, t = merge(centroids(groups, vec))

    def by_app(ids) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for i in ids:
            out.setdefault(post[i]["app"] or "HN", set()).add(post[i]["author"])
        return out

    for g in groups:
        g["concentration"] = concentration(by_app(g["members"]))
    out = []
    for k in sorted(set(lab)):
        mem = [g for g, x in zip(groups, lab, strict=True) if x == k]
        mem.sort(key=lambda g: -g["authors"])
        ids = [i for g in mem for i in g["members"]]
        apps = by_app(ids)
        authors = {post[i]["author"] for i in ids}
        out.append(
            {
                "theme": mem[0].get("name") or f"group {mem[0]['group']}",
                "groups": [g["group"] for g in mem],
                "group_names": [g.get("name") for g in mem],
                "posts": len(ids),
                "authors": len(authors),
                "author_sum_of_groups": sum(g["authors"] for g in mem),
                "apps": dict(Counter({a: len(s) for a, s in apps.items()}).most_common()),
                "concentration": concentration(apps),
                "quote": mem[0].get("quote"),
                "quote_post": mem[0].get("quote_post"),
            }
        )
    out.sort(key=lambda th: -th["authors"])
    return {"threshold": t, "quantile": MERGE_QUANTILE, "labels": lab, "themes": out}
