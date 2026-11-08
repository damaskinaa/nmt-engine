"""Whole-category job clustering (PREREG_killline_v2.md §3, §5).

Instances are embedded as "<statement>\\n<first job span>" and clustered once per category by
average-linkage agglomerative clustering on cosine distance. The cut `t*` is chosen on labelled
pairs (`sample_pairs`, `choose_threshold`), never on the kill-line result. The producer LLM only
confirms merges between tight clusters (t* - 0.05) that sit inside one loose cluster (t* + 0.05),
and names each cluster, flagging clusters whose members name more than one expected outcome.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from nmt_engine.llm import LLM, LLMDisabled, LLMError
from nmt_engine.miner.extract import JobInstance
from nmt_engine.miner.jobs import JobGroup
from nmt_engine.miner.prompts import CONFIRM_PROMPT, CONFIRM_SYSTEM, NAME_PROMPT, NAME_SYSTEM
from nmt_engine.util import sha256_text

BAND = 0.05
LEVEL_ORDER = ("core", "small", "big", "micro")  # tie-break order (§3)
CONFIRM_CHUNK = 120  # tight clusters per confirmation request
NAME_CHUNK = 12  # clusters per naming request
NAME_MEMBERS = 10  # member statements shown per cluster


def instance_text(inst: JobInstance) -> str:
    job = (inst.spans.get("job") or [None])[0]
    return f"{inst.statement}\n{job}" if job else inst.statement


def instance_key(inst: JobInstance) -> str:
    return f"{inst.source_id}|{inst.statement}"


def cosine_linkage(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(condensed cosine distances, average-linkage tree)."""
    if len(vectors) < 2:
        return np.zeros(0), np.zeros((0, 4))
    dist = np.clip(pdist(vectors, "cosine"), 0.0, 2.0)
    return dist, linkage(dist, "average")


def cut(tree: np.ndarray, n: int, t: float) -> np.ndarray:
    """Cluster label per instance: members join while their average distance is <= t."""
    if n < 2:
        return np.ones(n, dtype=int)
    return fcluster(tree, max(t, 0.0), "distance")


def majority_level(levels: Sequence[str]) -> str:
    counts = Counter(levels)
    return max(LEVEL_ORDER, key=lambda lv: (counts[lv], -LEVEL_ORDER.index(lv)))


# --- §5: pairs and threshold ---------------------------------------------------------------


def pair_index(k: int, n: int) -> tuple[int, int]:
    """Row/column of entry k in a condensed n x n distance vector."""
    i = int(n - 2 - math.floor(math.sqrt(-8 * k + 4 * n * (n - 1) - 7) / 2 - 0.5))
    j = int(k + i + 1 - n * (n - 1) // 2 + (n - i) * (n - i - 1) // 2)
    return i, j


@dataclass
class Pair:
    category: str
    a: int  # instance index within the category
    b: int
    distance: float
    band: int


def sample_pairs(
    dists: dict[str, np.ndarray],
    n_by_cat: dict[str, int],
    bands: int = 10,
    per_band: int = 20,
    seed: int = 0,
) -> tuple[list[Pair], list[float]]:
    """`per_band` pairs from each of `bands` equal-width bands over [0, pooled median]."""
    rng = random.Random(seed)
    pooled = np.concatenate([d for d in dists.values() if len(d)])
    edges = list(np.linspace(0.0, float(np.median(pooled)), bands + 1))
    out: list[Pair] = []
    cats = sorted(dists)
    for b in range(bands):
        lo, hi = edges[b], edges[b + 1]
        pools = {}
        for cat in cats:
            d = dists[cat]
            mask = (d >= lo) & ((d < hi) if b < bands - 1 else (d <= hi))
            pools[cat] = list(np.flatnonzero(mask))
        taken: dict[str, set[int]] = defaultdict(set)
        order = cats[:]
        rng.shuffle(order)
        while sum(len(v) for v in taken.values()) < per_band and any(
            len(pools[c]) > len(taken[c]) for c in cats
        ):
            for cat in order:  # round-robin: as even across categories as the band allows
                if sum(len(v) for v in taken.values()) >= per_band:
                    break
                free = len(pools[cat]) - len(taken[cat])
                if free <= 0:
                    continue
                while True:
                    k = pools[cat][rng.randrange(len(pools[cat]))]
                    if k not in taken[cat]:
                        taken[cat].add(k)
                        break
        for cat in cats:
            for k in sorted(taken[cat]):
                i, j = pair_index(int(k), n_by_cat[cat])
                out.append(Pair(cat, i, j, round(float(dists[cat][k]), 6), b))
    return out, edges


@dataclass
class Threshold:
    t: float
    f1: float
    precision: float
    recall: float
    curve: list[dict] = field(default_factory=list)


def choose_threshold(
    distances: Sequence[float], same: Sequence[bool], step: float = 0.01
) -> Threshold:
    """t maximising F1 of "distance <= t means same job"; ties go to the smaller t."""
    d = np.asarray(distances, dtype=float)
    y = np.asarray(same, dtype=bool)
    best: Threshold | None = None
    curve = []
    hi = math.ceil(float(d.max()) / step) if len(d) else 0
    for k in range(hi + 1):
        t = round(k * step, 4)
        pred = d <= t + 1e-9
        tp = int((pred & y).sum())
        fp = int((pred & ~y).sum())
        fn = int((~pred & y).sum())
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        curve.append({"t": t, "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)})
        if best is None or f1 > best.f1 + 1e-12:
            best = Threshold(t, f1, p, r)
    assert best is not None, "no labelled pairs"
    best.curve = curve
    return best


# --- §3: clusters ---------------------------------------------------------------------------


@dataclass
class Cluster:
    members: list[int]  # instance indices
    name: str = ""
    mixed: bool = False
    level: str = "core"
    loose: int = 0

    def key(self, keys: list[str]) -> str:
        return "cl_" + sha256_text("\n".join(sorted(keys[i] for i in self.members)))[:12]


@dataclass
class ClusterResult:
    clusters: list[Cluster]
    t: float
    confirm_requests: int = 0
    merges: int = 0
    name_requests: int = 0
    failed_requests: int = 0


def representative(members: list[int], vectors: np.ndarray) -> int:
    """Member closest to the cluster centroid (ties: lowest index)."""
    if len(members) == 1:
        return members[0]
    sub = vectors[members]
    centre = sub.mean(axis=0)
    return members[int(np.argmax(sub @ centre))]


def _ints(raw) -> list[int]:
    return [i for i in (raw if isinstance(raw, list) else []) if isinstance(i, int)]


def confirm(
    llm: LLM, tight: list[list[int]], statements: list[str], category: str
) -> tuple[list[list[int]], int, int, int]:
    """Producer merges tight clusters within one loose cluster. Returns groups of tight ids."""
    parent = list(range(len(tight)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    requests = failed = merges = 0
    for start in range(0, len(tight), CONFIRM_CHUNK):
        ids = list(range(start, min(start + CONFIRM_CHUNK, len(tight))))
        items = "\n".join(f"{i}: {statements[i]}" for i in ids)
        requests += 1
        try:
            data = llm.complete_json(
                CONFIRM_PROMPT.format(category=category, items=items),
                CONFIRM_SYSTEM,
                purpose="miner.confirm",
            )
        except (LLMDisabled, LLMError):
            failed += 1
            continue
        groups = data.get("groups") if isinstance(data, dict) else None
        for g in groups if isinstance(groups, list) else []:
            members = [i for i in _ints(g.get("ids") if isinstance(g, dict) else None) if i in ids]
            for m in members[1:]:
                if find(m) != find(members[0]):
                    parent[find(m)] = find(members[0])
                    merges += 1
    out: dict[int, list[int]] = defaultdict(list)
    for i in range(len(tight)):
        out[find(i)].append(i)
    return list(out.values()), requests, failed, merges


def name_clusters(
    llm: LLM, clusters: list[Cluster], instances: list[JobInstance], category: str
) -> tuple[int, int]:
    """Name clusters of 2+ instances ("I want to <verb> ...") and flag mixed outcomes."""
    multi = [c for c in clusters if len(c.members) > 1]
    requests = failed = 0
    for start in range(0, len(multi), NAME_CHUNK):
        chunk = multi[start : start + NAME_CHUNK]
        blocks = []
        for k, c in enumerate(chunk):
            lines = []
            for i in c.members[:NAME_MEMBERS]:
                inst = instances[i]
                outcome = (inst.spans.get("success_criteria") or [""])[0] or next(
                    (v for _, v in inst.criteria), ""
                )
                lines.append(
                    f"  - {inst.statement}" + (f' (outcome: "{outcome}")' if outcome else "")
                )
            blocks.append(f"cluster {k} ({len(c.members)} posts):\n" + "\n".join(lines))
        requests += 1
        try:
            data = llm.complete_json(
                NAME_PROMPT.format(category=category, clusters="\n\n".join(blocks)),
                NAME_SYSTEM,
                purpose="miner.name",
            )
        except (LLMDisabled, LLMError):
            failed += 1
            continue
        rows = data.get("clusters") if isinstance(data, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("id"), int):
                continue
            if not 0 <= row["id"] < len(chunk):
                continue
            c = chunk[row["id"]]
            name = row.get("name")
            if isinstance(name, str) and name.strip().lower().startswith("i want to "):
                c.name = name.strip()
            c.mixed = row.get("mixed") is True
    return requests, failed


def cluster_category(
    instances: list[JobInstance],
    vectors: np.ndarray,
    t_star: float,
    llm: LLM | None,
    category: str,
    tree: np.ndarray | None = None,
) -> ClusterResult:
    n = len(instances)
    if tree is None:
        _, tree = cosine_linkage(vectors)
    tight = cut(tree, n, t_star - BAND)
    loose = cut(tree, n, t_star + BAND)
    by_tight: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(tight):
        by_tight[int(lab)].append(i)
    loose_of = {lab: int(loose[m[0]]) for lab, m in by_tight.items()}
    by_loose: dict[int, list[int]] = defaultdict(list)
    for lab in sorted(by_tight, key=lambda lab: min(by_tight[lab])):
        by_loose[loose_of[lab]].append(lab)
    res = ClusterResult([], t_star)
    for lid in sorted(by_loose, key=lambda lid: min(min(by_tight[t]) for t in by_loose[lid])):
        tights = [by_tight[t] for t in by_loose[lid]]
        if len(tights) > 1 and llm is not None:
            reps = [instances[representative(m, vectors)].statement for m in tights]
            groups, req, fail, merges = confirm(llm, tights, reps, category)
            res.confirm_requests += req
            res.failed_requests += fail
            res.merges += merges
        else:
            groups = [[k] for k in range(len(tights))]
        for g in groups:
            members = sorted(i for k in g for i in tights[k])
            res.clusters.append(Cluster(members, loose=lid))
    for c in res.clusters:
        c.level = majority_level([instances[i].level for i in c.members])
        rep = instances[representative(c.members, vectors)]
        c.name = rep.statement
    if llm is not None:
        req, fail = name_clusters(llm, res.clusters, instances, category)
        res.name_requests += req
        res.failed_requests += fail
    res.clusters.sort(key=lambda c: (-len(c.members), c.members[0]))
    return res


def to_groups(res: ClusterResult, instances: list[JobInstance]) -> list[JobGroup]:
    keys = [instance_key(i) for i in instances]
    return [
        JobGroup(
            c.name,
            [instances[i] for i in c.members],
            key=c.key(keys),
            level=c.level,
            mixed=c.mixed,
        )
        for c in res.clusters
    ]


def v2_grouper(embedder, t_star: float, category: str):
    """`mine(grouper=...)` hook: embed, cluster, confirm, name; stats go to mine_summary.json."""

    def group(instances: list[JobInstance], llm: LLM) -> tuple[list[JobGroup], dict]:
        tokens0, cost0 = embedder.tokens, embedder.cost
        vectors = embedder.embed([instance_text(i) for i in instances], "miner.embed")
        res = cluster_category(instances, vectors, t_star, llm if llm.enabled else None, category)
        n = len(instances)
        largest = max((len(c.members) for c in res.clusters), default=0)
        stats = {
            "method": "v2",
            "t": t_star,
            "clusters": len(res.clusters),
            "largest": largest,
            "largest_share": round(largest / n, 4) if n else 0.0,
            "confirm_requests": res.confirm_requests,
            "merges": res.merges,
            "name_requests": res.name_requests,
            "failed_requests": res.failed_requests,
            "embed_model": embedder.model,
            "embed_tokens": embedder.tokens - tokens0,
            "embed_cost_usd": round(embedder.cost - cost0, 6),
        }
        return to_groups(res, instances), stats

    return group
