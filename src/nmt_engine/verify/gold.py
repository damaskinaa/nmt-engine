"""Gold set and CI precision gate for L3 (ARCHITECTURE_v3 §4.3, §8 A1-A3, A9).

- `build`: seeded, family-stratified sample of customer-voice posts from L2-collector runs, split
  200 dev / 100 test. Post text goes to the gitignored cache only.
- `label`: the auditor (Kimi) labels every post; these are the gold labels (`gold.jsonl`, committed:
  source ids, URLs and labels only; quotes stay in the cache).
- `record`: the producer (DeepSeek) answers the same closed questions; its answers are committed
  under `recorded/<prompt hash>.json`.
- `check`: precision of the producer against gold, per class (§8 A3), on dev and held-out test.
  CI fails when no recording matches the current prompt hash, or when a test precision is < 85%.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from nmt_engine.collect.base import scrub_pii
from nmt_engine.config import repo_root
from nmt_engine.llm import LLM, PRODUCER
from nmt_engine.stats import Z95, agreement, precision, wilson
from nmt_engine.store import load_run
from nmt_engine.subtraction import collector_on
from nmt_engine.util import canonical_json, normalize_ws, sha256_text
from nmt_engine.verify import prompts
from nmt_engine.verify.author import Post, author_gate, tag_elements

GOLD_DIR = repo_root() / "tests" / "gold" / "invoicing"
CACHE_DIR = repo_root() / "cache" / "gold" / "invoicing"
MAX_CHARS = 1000
N_GOLD, N_TEST = 300, 100
PRECISION_MIN = 0.85
MIN_CALLS = 20  # fewer positive calls on test: NOT MEASURED, never a pass
QUOTE_CHARS = 120
BATCH = 8
PRODUCER_REASONING = "none"


def prompt_hash(model: str = PRODUCER, reasoning: str | None = PRODUCER_REASONING) -> str:
    """Hash of everything that shapes the producer's answers on the gold set."""
    return sha256_text(
        canonical_json(
            {
                "author": [prompts.AUTHOR_SYSTEM, prompts.AUTHOR_PROMPT],
                "elements": [prompts.ELEMENT_SYSTEM, prompts.ELEMENT_PROMPT],
                "fields": prompts.ELEMENT_FIELDS,
                "model": model,
                "reasoning_effort": reasoning,
                "max_chars": MAX_CHARS,
                "batch": BATCH,
            }
        )
    )[:16]


def _clip(text: str, n: int = MAX_CHARS) -> str:
    text = scrub_pii(normalize_ws(text))
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."


def build(run_dirs: list[Path], category: str, seed: int = 0, out: Path = GOLD_DIR) -> dict:
    """Sample N_GOLD posts, stratified by evidence family, from L2-collector customer voice."""
    pool = []
    for rd in run_dirs:
        for s in load_run(rd).sources.values():
            if s.retracted or not s.customer_voice or not collector_on(s.platform, {}):
                continue
            pool.append((s, rd))
    pool.sort(key=lambda p: p[0].id)
    rng = random.Random(seed)
    fam = Counter(s.evidence_family for s, _ in pool)
    quota = {f: round(N_GOLD * n / len(pool)) for f, n in fam.items()}
    quota[max(quota, key=quota.get)] += N_GOLD - sum(quota.values())
    chosen = []
    for f in sorted(quota):
        items = [p for p in pool if p[0].evidence_family == f]
        chosen += rng.sample(items, quota[f])
    rng.shuffle(chosen)
    test = set(rng.sample(range(len(chosen)), N_TEST))
    rows, posts = [], []
    for i, (s, rd) in enumerate(chosen):
        gid = f"G{i + 1:03d}"
        rows.append(
            {
                "id": gid,
                "source_id": s.id,
                "url": s.url,
                "platform": s.platform,
                "family": s.evidence_family,
                "split": "test" if i in test else "dev",
            }
        )
        text = _clip((rd / s.text_path).read_text("utf-8"))
        posts.append({"id": gid, "category": category, "text": text})
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "items.jsonl", rows)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _write_jsonl(CACHE_DIR / "posts.jsonl", posts)
    return {"n": len(rows), "by_family": dict(sorted(Counter(r["family"] for r in rows).items()))}


def load_posts() -> list[Post]:
    return [Post(**r) for r in _read_jsonl(CACHE_DIR / "posts.jsonl")]


def label_prompt_hash() -> str:
    """Hash of the frozen auditor prompts the gold labels were made with."""
    return sha256_text(
        canonical_json(
            [
                prompts.GOLD_AUTHOR_SYSTEM,
                prompts.GOLD_AUTHOR_PROMPT,
                prompts.GOLD_ELEMENT_SYSTEM,
                prompts.GOLD_ELEMENT_PROMPT,
                prompts.ELEMENT_FIELDS,
                MAX_CHARS,
                BATCH,
            ]
        )
    )[:16]


def _answers(llm: LLM, posts: list[Post], step: str, gold: bool = False) -> dict[str, dict]:
    authors = author_gate(llm, posts, f"{step}.author", BATCH, gold=gold)
    tags = tag_elements(llm, posts, f"{step}.elements", BATCH, gold=gold)
    out = {}
    for p, a, t in zip(posts, authors, tags, strict=True):
        out[p.id] = {
            "role": a.role if a else None,
            "names_solution": a.names_solution if a else None,
            "elements": t,
            "role_quote": _short(a.role_quote) if a else None,
        }
    return out


def _short(q: str | None) -> str | None:
    return None if q is None else scrub_pii(q)[:QUOTE_CHARS]


def label(llm: LLM, out: Path = GOLD_DIR) -> dict:
    """Auditor gold labels for every item; unanswered items stay null and are not scored."""
    ans = _answers(llm, load_posts(), "gold.label", gold=True)
    rows = []
    for item in _read_jsonl(out / "items.jsonl"):
        meta = {"labeller": llm.model, "label_prompt_hash": label_prompt_hash()}
        rows.append({**item, **ans[item["id"]], **meta})
    # quotes can carry names or handles, so they stay in the gitignored cache (§8 A9)
    _write_jsonl(
        CACHE_DIR / "gold_quotes.jsonl", [{k: r[k] for k in ("id", "role_quote")} for r in rows]
    )
    _write_jsonl(
        out / "gold.jsonl", [{k: v for k, v in r.items() if k != "role_quote"} for r in rows]
    )
    return {"labelled": sum(r["role"] is not None for r in rows), "n": len(rows)}


def record(llm: LLM, out: Path = GOLD_DIR) -> Path:
    """Producer answers on the gold posts, committed under the current prompt hash."""
    ans = _answers(llm, load_posts(), "gold.record")
    path = out / "recorded" / f"{prompt_hash(llm.model, llm.reasoning_effort)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "prompt_hash": path.stem,
        "model": llm.model,
        "host": llm.host,
        "reasoning_effort": llm.reasoning_effort,
        "answers": {
            k: {f: v[f] for f in ("role", "names_solution", "elements")} for k, v in ans.items()
        },
    }
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", "utf-8")
    return path


def check(out: Path = GOLD_DIR, phash: str | None = None) -> dict:
    """Per-class producer precision against gold on dev and test, with 95% Wilson intervals.
    Classes (§8 A3): USER in the author gate; each element tag, scored on posts gold calls USER.
    A class with fewer than MIN_CALLS positive calls on test is NOT MEASURED, which is not a pass:
    T1 counts as passed only for the classes in `t1_passed_for`."""
    phash = phash or prompt_hash()
    path = out / "recorded" / f"{phash}.json"
    if not path.is_file():
        return {"prompt_hash": phash, "passed": False, "error": f"no recording for {phash}"}
    rec = json.loads(path.read_text("utf-8"))["answers"]
    gold = _read_jsonl(out / "gold.jsonl")
    res: dict = {"prompt_hash": phash, "classes": {}}
    for split in ("dev", "test"):
        rows = [g for g in gold if g["split"] == split and g["role"] is not None]
        pred = [rec.get(g["id"], {}).get("role") for g in rows]
        res["classes"].setdefault("USER", {})[split] = _prec(
            pred, [g["role"] for g in rows], "USER"
        )
        users = [g for g in rows if g["role"] == "USER" and g["elements"] is not None]
        for el in prompts.ELEMENTS:
            p = [(rec.get(g["id"], {}).get("elements") or {}).get(el) for g in users]
            res["classes"].setdefault(el, {})[split] = _prec(
                p, [g["elements"][el] for g in users], True
            )
    for c in res["classes"].values():
        t = c["test"]
        if t["called"] < MIN_CALLS:
            t["status"] = "NOT MEASURED"
        else:
            t["status"] = "PASS" if t["precision"] >= PRECISION_MIN else "FAIL"
    status = {k: c["test"]["status"] for k, c in res["classes"].items()}
    res["t1_passed_for"] = sorted(k for k, v in status.items() if v == "PASS")
    res["not_measured"] = sorted(k for k, v in status.items() if v == "NOT MEASURED")
    # CI fails on a missing recording or on any measured class below 85%
    res["passed"] = "FAIL" not in status.values()
    return res


def _prec(pred, gold, positive) -> dict:
    tp, called = precision(pred, gold, positive)
    lo, hi = wilson(tp, called, Z95)
    return {
        "tp": tp,
        "called": called,
        "precision": round(tp / called, 4) if called else None,
        "wilson95": [lo, hi],
    }


def packet(n: int = 30, seed: int = 1, out: Path = GOLD_DIR) -> list[dict]:
    """Blind human packet: n gold items (labelled by the auditor), text from the cache only."""
    gold = [g for g in _read_jsonl(out / "gold.jsonl") if g["role"] is not None]
    pick = sorted(random.Random(seed).sample(range(len(gold)), n))
    text = {p.id: p.text for p in load_posts()}
    return [
        {"n": i + 1, "id": gold[k]["id"], "text": text[gold[k]["id"]]} for i, k in enumerate(pick)
    ]


def human_agreement(answers: str, out: Path = GOLD_DIR, n: int = 30, seed: int = 1) -> dict:
    """`answers`: one letter per packet item in order, U/B/V/O. Agreement < 24/30 stops (§8 A2)."""
    letters = [c for c in answers.upper() if c in "UBVO"]
    if len(letters) != n:
        raise ValueError(f"expected {n} answers (U/B/V/O), got {len(letters)}")
    roles = {"U": "USER", "B": "BUILDER", "V": "VENDOR", "O": "OTHER"}
    gold = {g["id"]: g["role"] for g in _read_jsonl(out / "gold.jsonl")}
    items = packet(n, seed, out)
    human = [roles[c] for c in letters]
    auditor = [gold[it["id"]] for it in items]
    agree = sum(h == a for h, a in zip(human, auditor, strict=True))
    return {
        "n": n,
        "agree": agree,
        "agreement": agreement(human, auditor),
        "passed": agree >= 24,
        "items": [
            {"id": it["id"], "human": h, "auditor": a}
            for it, h, a in zip(items, human, auditor, strict=True)
        ],
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), "utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


__all__ = ["build", "check", "human_agreement", "label", "packet", "record"]
