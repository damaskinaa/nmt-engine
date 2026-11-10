"""Radar inputs (PREREG_v3 amendment 7 rules 1-4): pool, producer pass, problem groups, map."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from nmt_engine.sim import replay
from nmt_engine.sim.agents import QUOTE_CHARS, _mask
from nmt_engine.store import load_run, read_text_in
from nmt_engine.verify import author
from nmt_engine.verify.gold import GOLD_DIR, _read_jsonl

K = 12
SEED = 0
NAME_POSTS = 8
THIN_AUTHORS = 3
THIN_APPS = 2
ALLOWED = {v: k for k, v in replay.APPSTORE_IDS.items()}  # listing id -> app


def app_of(url: str) -> str | None:
    m = re.search(r"/id(\d+)", url)
    return ALLOWED.get(m.group(1)) if m else None


def pool(harvest_dir: Path, out: Path = GOLD_DIR) -> list[dict]:
    """Allow-listed App Store reviews plus the HN posts Kimi labelled USER (amendment 3 pool)."""
    run = load_run(harvest_dir)
    rows = []
    for s in run.sources.values():
        if s.platform != "appstore" or not s.author_hash:
            continue
        app = app_of(s.url)
        if app is None:
            continue
        rows.append((s, app))
    users = {a["source_id"] for a in _read_jsonl(out / "node_authors.jsonl") if a["role"] == "USER"}
    for s in run.sources.values():
        if s.platform == "hackernews" and s.id in users and s.author_hash:
            rows.append((s, None))
    posts = []
    for s, app in rows:
        text = read_text_in(Path(harvest_dir), s.text_path)
        posts.append(
            {
                "id": s.id,
                "author": s.author_hash,
                "platform": s.platform,
                "app": app,
                "country": s.geography,
                "year": s.published_at.year if s.published_at else None,
                "url": s.url,
                "text": text,
            }
        )
    return sorted(posts, key=lambda p: p["id"])


def producer_pass(llm, posts: list[dict], category: str = "invoicing") -> None:
    """Frozen B3 producer prompts: author gate, then element tags on posts called USER."""
    ps = [author.Post(p["id"], category, p["text"][:3000]) for p in posts]
    roles = author.author_gate(llm, ps, purpose="radar.author")
    for p, v in zip(posts, roles, strict=True):
        p["role"] = v.role if v else None
    users = [(p, q) for p, q in zip(posts, ps, strict=True) if p["role"] == "USER"]
    tags = author.tag_elements(llm, [q for _, q in users], purpose="radar.elements")
    for (p, _), t in zip(users, tags, strict=True):
        p["problem"] = bool(t and t.get("problem"))


def groups(emb, posts: list[dict]) -> list[dict]:
    """k-means (k=12, seed 0, ++ init) on unit Qwen3 vectors of the masked first 300 chars."""
    from scipy.cluster.vq import kmeans2

    texts = [_mask(p["text"])[:QUOTE_CHARS] for p in posts]
    v = np.asarray(emb.embed(texts, "radar.embed"), dtype=float)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    cent, lab = kmeans2(v, K, minit="++", seed=SEED)
    total = len(posts)
    out = []
    for g in range(K):
        idx = [i for i in range(total) if lab[i] == g]
        if not idx:
            continue
        c = cent[g] / (np.linalg.norm(cent[g]) or 1.0)
        near = sorted(idx, key=lambda i: -float(v[i] @ c))[:NAME_POSTS]
        authors = {posts[i]["author"] for i in idx}
        apps = Counter(posts[i]["app"] or "HN" for i in idx)
        out.append(
            {
                "group": g,
                "posts": len(idx),
                "share": round(len(idx) / total, 4),
                "authors": len(authors),
                "apps": dict(apps.most_common()),
                "years": dict(sorted(Counter(posts[i]["year"] for i in idx).items())),
                "countries": dict(Counter(posts[i]["country"] for i in idx).most_common()),
                "thin": len(authors) < THIN_AUTHORS or len(apps) < THIN_APPS,
                "nearest": [posts[i]["id"] for i in near],
                "members": [posts[i]["id"] for i in idx],
            }
        )
    return sorted(out, key=lambda g: -g["authors"])


NAME_SYSTEM = "You name groups of customer reviews. Answer only with JSON. Quote words exactly."
NAME_PROMPT = """These reviews of invoicing apps were grouped together by text similarity.

{posts}

What problem do these reviewers share? Give a short name (at most 8 words, plain words, no app
names), a one-sentence description, and the exact words from one review that best show it.
Answer as JSON: {{"name": "...", "description": "...", "post": "<post id>", "quote": "..."}}"""


def name_groups(llm, gs: list[dict], texts: dict[str, str]) -> None:
    for g in gs:
        body = "\n\n".join(
            f'<post id="{i}">\n{_mask(texts[i])[:600]}\n</post>' for i in g["nearest"]
        )
        g["name"] = None
        for retry in (False, True):
            p = NAME_PROMPT.format(posts=body) + ("\nUse a shorter quote." if retry else "")
            try:
                a = llm.complete_json(p, NAME_SYSTEM, "radar.name")
            except Exception:  # noqa: BLE001 - a failed name leaves the group unnamed
                continue
            i = a.get("post") if isinstance(a, dict) else None
            if i in g["nearest"] and author.verbatim(a.get("quote"), _mask(texts[i])[:600]):
                g.update(
                    name=a.get("name"),
                    description=a.get("description"),
                    quote_post=i,
                    quote=a["quote"],
                )
                break


def alternatives(posts: list[dict]) -> dict:
    """Per reviewed app: how many distinct authors name each other listed option (regex)."""
    by_app: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for p in posts:
        app = p["app"] or "HN"
        pats = replay.option_patterns(p["app"]) if p["app"] else _all_patterns()
        for opt, pat in pats.items():
            if pat.search(p["text"]):
                by_app[app][opt].add(p["author"])
    return {
        a: dict(sorted(((o, len(s)) for o, s in m.items()), key=lambda x: -x[1]))
        for a, m in sorted(by_app.items())
    }


def _all_patterns() -> dict:
    pats = dict(replay.option_patterns("Bonsai"))
    pats.update(replay.option_patterns("FreshBooks"))
    return pats


def write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str), "utf-8")
