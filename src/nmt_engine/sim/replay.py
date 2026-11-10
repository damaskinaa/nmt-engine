"""Historical replay (PREREG_v3 amendments 4 and 6): pricing-page change events from Wayback,
a simulator prediction and a name-count baseline frozen before any outcome is read, then outcomes
from public posts after the change. Replay output is SIMULATED and never L4 evidence."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nmt_engine.collect import wayback
from nmt_engine.collect.base import Collector

# Amendment 6: one archived pricing page per app (Invoice Simple has none archived since 2019).
PRICING = {
    "Bonsai": "hellobonsai.com/pricing",
    "FreshBooks": "freshbooks.com/pricing",
    "Harvest": "getharvest.com/pricing",
    "Invoice Ninja": "invoiceninja.com/pricing-plans",
    "Invoice2go": "invoice.2go.com/pricing",
    "QuickBooks": "quickbooks.intuit.com/pricing",
    "Wave": "waveapps.com/pricing",
    "Xero": "xero.com/us/pricing-plans",
    "Zoho Invoice": "zoho.com/invoice/pricing",
}
SINCE = "20190101"
MAX_GAP_DAYS = 31
CURRENCY = re.compile(r"[$€£]\s?\d|\b\d+(?:[.,]\d+)?\s?(?:USD|EUR|GBP)\b")


@dataclass
class Candidate:
    app: str
    url: str
    old: str  # monthly snapshot stamps
    new: str
    lines: list[str]  # diff lines that carry a currency amount


def _cdx(c: Collector, url: str, start: str, end: str, collapse: str) -> list[dict]:
    rows = c.fetch_json(
        wayback.CDX,
        wayback.NAME,
        params={
            "url": url,
            "from": start,
            "to": end,
            "output": "json",
            "filter": "statuscode:200",
            "collapse": collapse,
        },
    )
    if not rows:
        return []
    head, *body = rows
    return [dict(zip(head, r, strict=False)) for r in body]


def money_lines(text: str) -> set[str]:
    return {ln.strip() for ln in text.splitlines() if CURRENCY.search(ln)}


def candidates(c: Collector, app: str, url: str, until: str) -> list[Candidate]:
    """Consecutive monthly snapshots whose diff adds or removes a line with a currency amount."""
    out, prev = [], None
    for snap in _cdx(c, url, SINCE, until, "timestamp:6"):
        try:
            text = wayback.snapshot_text(c, snap["original"], snap["timestamp"])
        except Exception:  # an unreadable snapshot is skipped, the pair spans it
            continue
        if prev is not None:
            d = wayback.diff(prev[1], text).splitlines()
            lines = [ln for ln in d if CURRENCY.search(ln)]
            if lines:
                out.append(Candidate(app, url, prev[0], snap["timestamp"], lines))
        prev = (snap["timestamp"], text)
    return out


def _day(stamp: str) -> datetime:
    return datetime.strptime(stamp[:8], "%Y%m%d").replace(tzinfo=UTC)


def bracket(c: Collector, cand: Candidate) -> dict:
    """T0 = last daily snapshot with the old page's money lines, T1 = first with the new page's.
    Binary search over daily snapshots between the monthly pair; gap > 31 days is unusable."""
    snaps = _cdx(c, cand.url, cand.old, cand.new, "timestamp:8")
    stamps = [s["timestamp"] for s in snaps]
    if not stamps or stamps[0] != cand.old:
        stamps = [cand.old, *[s for s in stamps if s > cand.old]]
    if stamps[-1] != cand.new:
        stamps = [*[s for s in stamps if s < cand.new], cand.new]
    orig = snaps[0]["original"] if snaps else cand.url

    def moneys(stamp: str) -> set[str]:
        return money_lines(wayback.snapshot_text(c, orig, stamp))

    new_set = moneys(cand.new)
    lo, hi = 0, len(stamps) - 1  # invariant: stamps[lo] is not the new page, stamps[hi] is
    while hi - lo > 1:
        mid = (lo + hi) // 2
        try:
            is_new = moneys(stamps[mid]) == new_set
        except Exception:
            stamps.pop(mid)
            hi -= 1
            continue
        lo, hi = (lo, mid) if is_new else (mid, hi)
    t0, t1 = _day(stamps[lo]), _day(stamps[hi])
    gap = (t1 - t0).days
    return {
        "t0": t0.date().isoformat(),
        "t1": t1.date().isoformat(),
        "gap_days": gap,
        "usable_dates": gap <= MAX_GAP_DAYS,
        "freeze": (t0 - timedelta(days=1)).date().isoformat(),
    }


def discover(c: Collector, out: Path, until: str) -> list[dict]:
    """All candidates with brackets, written to `candidates.jsonl` (no model calls)."""
    rows = []
    for app, url in PRICING.items():
        for cand in candidates(c, app, url, until):
            row = {**asdict(cand), "id": f"{app}:{cand.old}:{cand.new}"}
            try:
                row.update(bracket(c, cand))
            except Exception as e:
                row.update({"usable_dates": False, "error": str(e)[:200]})
            rows.append(row)
        print(app, sum(r["app"] == app for r in rows), flush=True)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "candidates.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return rows


# --- options and name patterns (amendment 4 option list, amendment 6 rule 6) -----------------

APPS = (
    "Bonsai",
    "FreshBooks",
    "Harvest",
    "Invoice Ninja",
    "Invoice Simple",
    "Invoice2go",
    "QuickBooks",
    "Wave",
    "Xero",
    "Zoho Invoice",
)
OTHER_OPTIONS = {
    "a spreadsheet": r"\b(spreadsheets?|excel|google sheets|numbers app)\b",
    "invoices by hand (word processor and email)": r"\b(by hand|manually|word document|"
    r"word template|google docs?|ms word|microsoft word)\b",
    "an accountant or bookkeeper": r"\b(accountants?|bookkeepers?)\b",
    "a self-built tool": r"\b(built my own|wrote my own|my own (tool|app|script|system)|"
    r"self-built|homegrown|home-grown|roll(ed)? my own)\b",
}
CASED = {"Wave", "Harvest"}  # common words: must be capitalised
APP_PATTERNS = {
    "Bonsai": r"\bbonsai\b",
    "FreshBooks": r"\bfresh ?books\b",
    "Harvest": r"\bHarvest\b",
    "Invoice Ninja": r"\binvoice ?ninja\b",
    "Invoice Simple": r"\binvoice simple\b",
    "Invoice2go": r"\binvoice ?2 ?go\b",
    "QuickBooks": r"\bquick ?books\b|\bQBO\b",
    "Wave": r"\bWave( Accounting| Apps| Invoicing)?\b",
    "Xero": r"\bxero\b",
    "Zoho Invoice": r"\bzoho\b",
}
LEAVING = re.compile(
    r"\b(left|leave|leaving|switch\w*|mov(ed|ing) (to|from|away)|migrat\w*|cancel\w*|dropped|"
    r"replac\w*|ditch\w*|quit)\b",
    re.I,
)
OUTCOME_CAP = 60
DIFF_LINES = 12
DIFF_CHARS = 200
REPEATS = 3
WINDOW_DAYS = 365


def _rx(app: str) -> re.Pattern:
    return re.compile(APP_PATTERNS[app], 0 if app in CASED else re.I)


def options(app: str) -> list[str]:
    return [a for a in APPS if a != app] + list(OTHER_OPTIONS)


def option_patterns(app: str) -> dict[str, re.Pattern]:
    return {
        o: (_rx(o) if o in APP_PATTERNS else re.compile(OTHER_OPTIONS[o], re.I))
        for o in options(app)
    }


def mentions(app: str, text: str) -> bool:
    return bool(_rx(app).search(text))


# --- event confirmation and selection ------------------------------------------------------

CONFIRM_SYSTEM = (
    "You check archived web pages. Answer only with JSON. Quote words exactly as they appear."
)
CONFIRM_PROMPT = """These lines were removed (-) or added (+) between two archived copies of the
pricing page of {app}:

{lines}

Question: do these lines show that {app} changed its own prices or plans (a price, a plan, a
tier or what a plan includes), rather than only layout, wording, a currency display or a
temporary promotion?
Answer as JSON: {{"change": "yes" or "no", "quote": "the exact words from the lines above that
decided it"}}"""


def confirm_prompt_hash() -> str:
    from nmt_engine.util import canonical_json, sha256_text

    return sha256_text(canonical_json({"s": CONFIRM_SYSTEM, "p": CONFIRM_PROMPT}))[:16]


def _diff_lines(row: dict) -> list[str]:
    return [ln[: DIFF_CHARS + 1] for ln in row["lines"]][:DIFF_LINES]


def confirm(llm, rows: list[dict], workers: int = 4) -> list[dict]:
    """Kimi's closed question per usable candidate (verbatim quote, one retry)."""
    from concurrent.futures import ThreadPoolExecutor

    from nmt_engine.llm import LLMError
    from nmt_engine.verify.author import verbatim

    def one(row: dict) -> dict:
        lines = "\n".join(_diff_lines(row))
        prompt = CONFIRM_PROMPT.format(app=row["app"], lines=lines)
        for attempt in range(2):
            p = prompt if attempt == 0 else prompt + "\nUse a shorter quote, copied exactly."
            try:
                ans = llm.complete_json(p, CONFIRM_SYSTEM, "sim.replay.confirm")
            except LLMError:
                continue
            ok = isinstance(ans, dict) and ans.get("change") in ("yes", "no")
            if ok and verbatim(ans.get("quote"), lines):
                return {"confirmed": ans["change"] == "yes", "quote": ans["quote"]}
        return {"confirmed": False, "quote": None, "unlabelled": True}

    todo = [r for r in rows if r.get("usable_dates")]
    with ThreadPoolExecutor(workers) as pool:
        got = list(pool.map(one, todo))
    for r, g in zip(todo, got, strict=True):
        r.update(g)
    return rows


def select(rows: list[dict], confirm_fn=None, workers: int = 1) -> list[dict]:
    """Per app, confirmed events by date; drop one whose T1 is within 365 days of a kept one.
    With `confirm_fn`, a candidate is confirmed only when it could be kept (same result as
    confirming every candidate first, fewer Kimi calls). Apps are independent, so they may run
    in parallel."""

    def one(app: str) -> list[dict]:
        kept, last = [], None
        mine = sorted(
            (r for r in rows if r["app"] == app and r.get("usable_dates")), key=lambda r: r["t1"]
        )
        for r in mine:
            t1 = datetime.fromisoformat(r["t1"])
            if last is not None and (t1 - last).days <= WINDOW_DAYS:
                r.setdefault("skipped", "within 365 days of a kept event")
                continue
            if confirm_fn is not None and "confirmed" not in r:
                confirm_fn([r])
            if r.get("confirmed"):
                kept.append(r)
                last = t1
        return kept

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return [e for kept in pool.map(one, PRICING) for e in kept]


# --- posts: HN comments and allow-listed App Store reviews ---------------------------------

APPSTORE_IDS = {
    "Bonsai": "1333596451",
    "FreshBooks": "1052884030",
    "Harvest": "355395846",
    "Invoice Ninja": "1503970375",
    "Invoice2go": "540236748",
    "Invoice Simple": "694831622",
    "QuickBooks": "584606479",
    "Xero": "441880705",
    "Zoho Invoice": "413017364",
}


def _hn(c: Collector, query: str, start: datetime, end: datetime, limit: int = 1000):
    from nmt_engine.collect.base import ts
    from nmt_engine.collect.hackernews import API, NAME
    from nmt_engine.collect.text import html_to_text

    a, b = int(start.timestamp()), int(end.timestamp())
    out, page = [], 0
    while len(out) < limit:
        data = c.fetch_json(
            API,
            NAME,
            params={
                "query": query,
                "tags": "comment",
                "numericFilters": f"created_at_i>={a},created_at_i<{b}",
                "hitsPerPage": 100,
                "page": page,
            },
        )
        for hit in data.get("hits", []):
            text = html_to_text(hit.get("comment_text") or "")
            src = c.add_source(
                adapter=NAME,
                kind="forum",
                platform="hackernews",
                url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                text=text,
                author=hit.get("author"),
                published_at=ts(hit.get("created_at_i")),
                access_basis="public_api_terms_ok",
                terms_url="https://hn.algolia.com/api",
                geography="GLOBAL",
                existing_ok=True,
            )
            if src:
                out.append(src)
        page += 1
        if page >= data.get("nbPages", 0):
            break
    return out


def posts(c: Collector, harvest, app: str, start: datetime, end: datetime) -> list[dict]:
    """Posts naming `app` dated [start, end): HN comments plus its own App Store reviews."""
    rows = []
    for s in _hn(c, app, start, end):
        rows.append((s, c.run_dir / s.text_path))
    lid = APPSTORE_IDS.get(app)
    for s in harvest.sources.values() if lid else []:
        if s.platform == "appstore" and f"/id{lid}#" in s.url:
            rows.append((s, harvest_dir_of(harvest) / s.text_path))
    out, seen = [], set()
    for s, path in rows:
        when = s.published_at
        if s.id in seen or when is None or not (start <= when < end) or not s.author_hash:
            continue
        text = path.read_text("utf-8")
        if s.platform != "appstore" and not mentions(app, text):
            continue
        seen.add(s.id)
        out.append(
            {
                "id": s.id,
                "author": s.author_hash,
                "published": when.isoformat(),
                "platform": s.platform,
                "text": text,
            }
        )
    return sorted(out, key=lambda p: p["id"])


def harvest_dir_of(harvest) -> Path:
    return Path(harvest.run_dir)


def baseline(app: str, before: list[dict]) -> dict:
    """Option named in the most posts (one count per post), ties to option order."""
    pats = option_patterns(app)
    counts = {o: sum(bool(p.search(x["text"])) for x in before) for o, p in pats.items()}
    opts = options(app)
    top = max(opts, key=lambda o: (counts[o], -opts.index(o)))
    return {"option": top, "counts": counts, "posts": len(before)}


# --- prediction ------------------------------------------------------------------------------


def condition(event: dict) -> str:
    return f"{event['app']} changed its pricing page.\n" + "\n".join(_diff_lines(event))


def predict(llm, ssr, graph, emb, pool: list[dict], support: dict, event: dict) -> dict:
    """5 agents built from posts before the freeze, starting on the app, DeepSeek, 3 repeats."""
    from nmt_engine.sim import agents as ag
    from nmt_engine.sim import world

    freeze = datetime.fromisoformat(event["freeze"]).replace(tzinfo=UTC) + timedelta(days=1)
    agents = ag.build(graph, emb, pool, before=freeze, support=support)
    app, opts = event["app"], options(event["app"])
    cond = condition(event)
    prompts_ = [(a, r, world.render(a, app, opts, cond, r)) for a in agents for r in range(REPEATS)]
    texts = [world.answer(llm, p, "sim.replay.predict") for _, _, p in prompts_]
    ps = ssr.score(texts, [opts] * len(texts), [app] * len(texts), "sim.ssr")
    mean = {o: sum(p[f"switch:{o}"] for p in ps) / len(ps) for o in opts}
    top = max(opts, key=lambda o: (mean[o], -opts.index(o)))
    return {
        "option": top,
        "mean_p_switch_to": mean,
        "label": world.LABEL,
        "claim_label": world.CLAIM_LABEL,
        "agents": {a.id: a.quote_ids for a in agents},
        "cells": [
            {"agent": a.id, "repeat": r, "answer": t, "p": p}
            for (a, r, _), t, p in zip(prompts_, texts, ps, strict=True)
        ],
    }


# --- outcomes -------------------------------------------------------------------------------

OUTCOME_SYSTEM = (
    "You read public posts about software. Answer only with JSON. Quote words exactly as they "
    "appear in the post."
)
OUTCOME_PROMPT = """Each post below mentions {app}.

{posts}

For each post: does the author say that they themselves left {app} or are leaving it? If yes,
for which option? Options: {options}. Use "other" for an option not in the list and "not said"
if they don't say.
Answer as JSON: {{"answers": [{{"post": "<post id>", "left": "yes" or "no", "to": "<option,
other or not said; empty if left is no>", "quote": "the exact words from that post that decided
it"}}]}}"""
OUTCOME_BATCH = 6
POST_CHARS = 1500


def outcome_prompt_hash() -> str:
    from nmt_engine.util import canonical_json, sha256_text

    return sha256_text(canonical_json({"s": OUTCOME_SYSTEM, "p": OUTCOME_PROMPT}))[:16]


def prefilter(app: str, rows: list[dict], event_id: str) -> list[dict]:
    from nmt_engine.util import sha256_text

    hit = [r for r in rows if LEAVING.search(r["text"])]
    hit.sort(key=lambda r: sha256_text(event_id + r["id"]))
    return sorted(hit[:OUTCOME_CAP], key=lambda r: r["id"])


def label_outcomes(llm, app: str, rows: list[dict]) -> dict[str, dict | None]:
    """Kimi's closed question per post, in batches; a post whose answer fails the checks gets one
    retry alone, then stays unlabelled (None)."""
    from nmt_engine.llm import BudgetExceeded, LLMError
    from nmt_engine.verify.author import verbatim

    opts = options(app)
    allowed = set(opts) | {"other", "not said"}
    texts = {r["id"]: r["text"][:POST_CHARS] for r in rows}

    def ask(ids: list[str], retry: bool) -> dict[str, dict]:
        body = "\n\n".join(f'<post id="{i}">\n{texts[i]}\n</post>' for i in ids)
        p = OUTCOME_PROMPT.format(app=app, posts=body, options="; ".join(opts))
        if retry:
            p += "\nUse a shorter quote, copied exactly."
        try:
            ans = llm.complete_json(p, OUTCOME_SYSTEM, "sim.replay.outcome")
        except LLMError:
            return {}
        got = {}
        for a in ans.get("answers", []) if isinstance(ans, dict) else []:
            i = a.get("post") if isinstance(a, dict) else None
            if i not in texts or a.get("left") not in ("yes", "no"):
                continue
            if not verbatim(a.get("quote"), texts[i]):
                continue
            to = a.get("to") if a["left"] == "yes" else None
            if a["left"] == "yes" and to not in allowed:
                continue
            got[i] = {"left": a["left"] == "yes", "to": to, "quote": a["quote"]}
        return got

    out: dict[str, dict | None] = {}
    ids = sorted(texts)
    try:
        for k in range(0, len(ids), OUTCOME_BATCH):
            out.update(ask(ids[k : k + OUTCOME_BATCH], False))
        for i in [i for i in ids if i not in out]:
            out.update(ask([i], True))
    except BudgetExceeded:
        pass
    return {i: out.get(i) for i in ids}


def votes(rows: list[dict], labels: dict[str, dict | None], app: str) -> dict:
    """One vote per author: the earliest labelled post in the window."""
    opts = options(app)
    first: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (r["published"], r["id"])):
        lab = labels.get(r["id"])
        if lab is None or r["author"] in first:
            continue
        first[r["author"]] = lab
    named = {o: 0 for o in opts}
    for lab in first.values():
        if lab["left"] and lab["to"] in named:
            named[lab["to"]] += 1
    n = sum(named.values())
    return {
        "authors": len(first),
        "left": sum(lab["left"] for lab in first.values()),
        "named": named,
        "naming_authors": n,
        "usable": n >= 3,
        "share": {o: (v / n if n else 0.0) for o, v in named.items()},
    }


def score(events: list[dict]) -> dict:
    """Amendment 4 beats and pass; amendment 6: exploratory whatever the result (SSR failed)."""
    usable = [e for e in events if e.get("outcome", {}).get("usable")]
    for e in usable:
        sh = e["outcome"]["share"]
        sim, base = e["prediction"]["option"], e["baseline"]["option"]
        e["beats"] = sim != base and sh[sim] > sh[base]
    wins = sum(e["beats"] for e in usable)
    if len(usable) < 3:
        verdict = "UNDECIDABLE"
    else:
        verdict = "PASS" if 3 * wins >= 2 * len(usable) else "FAIL"
    return {
        "events": len(events),
        "usable": len(usable),
        "wins": wins,
        "t3": verdict,
        "simulation_section": "exploratory",
        "why_exploratory": "SSR gold failed (stay 18/23, switch 23/30, bar 85%); amendment 6",
    }
