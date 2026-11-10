"""Semantic Similarity Rating (arXiv 2510.08338): free-text answers become a probability mass
over outcomes by embedding similarity to fixed anchor statements. The model never outputs numbers.
"""

from __future__ import annotations

import numpy as np

from nmt_engine.util import canonical_json, sha256_text

EPS = 0.01
CLASSES = ("stay", "consider", "switch")
ANCHORS: dict[str, list[str]] = {
    "stay": [
        "I am staying with {inc}; it still does the job well enough.",
        "Nothing here is worth the trouble of moving, so I keep using {inc}.",
        "I will carry on with {inc} exactly as I do now.",
    ],
    "consider": [
        "I keep {inc} for now, but I am going to look at the alternatives before I decide.",
        "This makes me want to try another option, though I have not left {inc} yet.",
        "I will compare what else is out there while I stay on {inc} for the moment.",
    ],
    "switch": [
        "I am leaving my current tool and moving to {x}.",
        "I will switch to {x} now.",
        "From now on I will use {x} instead.",
    ],
}


def anchor_hash() -> str:
    return sha256_text(canonical_json({"anchors": ANCHORS, "eps": EPS, "rule": "a5"}))[:16]


def outcomes(offers: list[str], inc: str) -> dict[str, list[str]]:
    out = {k: [a.format(inc=inc) for a in ANCHORS[k]] for k in ("stay", "consider")}
    for x in offers:
        out[f"switch:{x}"] = [a.format(x=x) for a in ANCHORS["switch"]]
    return out


def pmf(sims: dict[str, float]) -> dict[str, float]:
    """p_i ∝ s_i − min_j s_j + EPS."""
    lo = min(sims.values())
    raw = {k: v - lo + EPS for k, v in sims.items()}
    tot = sum(raw.values())
    return {k: v / tot for k, v in raw.items()}


def probs(sims: dict[str, float]) -> dict[str, float]:
    """Amendment 5: P over stay / consider / best switch, then P(switch) shared across
    destinations by their own floored similarities."""
    sw = {k: v for k, v in sims.items() if k.startswith("switch:")}
    pc = pmf({"stay": sims["stay"], "consider": sims["consider"], "switch": max(sw.values())})
    q = pmf(sw) if len(sw) > 1 else dict.fromkeys(sw, 1.0)
    return {"stay": pc["stay"], "consider": pc["consider"]} | {k: pc["switch"] * q[k] for k in sw}


def collapse(p: dict[str, float]) -> dict[str, float]:
    """stay / consider / switch, with switch summed over every switch outcome."""
    sw = sum(v for k, v in p.items() if k.startswith("switch:"))
    return {"stay": p["stay"], "consider": p["consider"], "switch": sw}


def top_class(p: dict[str, float]) -> str:
    c = collapse(p)
    return max(CLASSES, key=lambda k: (c[k], -CLASSES.index(k)))


class SSR:
    """Mean cosine similarity of an answer to each outcome's anchors (Qwen3 vectors are
    normalised, so cosine is a dot product)."""

    def __init__(self, emb):
        self.emb = emb

    def sims(
        self, answers: list[str], offers: list[list[str]], incs: list[str], purpose: str
    ) -> list[dict]:
        outs = [outcomes(o, i) for o, i in zip(offers, incs, strict=True)]
        anchors = sorted({a for o in outs for texts in o.values() for a in texts})
        av = dict(zip(anchors, self.emb.embed(anchors, purpose), strict=True))
        rv = self.emb.embed(answers, purpose)
        res = []
        for v, o in zip(rv, outs, strict=True):
            res.append({k: float(np.mean([v @ av[a] for a in texts])) for k, texts in o.items()})
        return res

    def score(
        self, answers: list[str], offers: list[list[str]], incs: list[str], purpose: str
    ) -> list[dict]:
        return [probs(s) for s in self.sims(answers, offers, incs, purpose)]
