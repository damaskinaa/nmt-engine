"""List prices of the alternatives from archived pricing pages into Q4 (amendment 8 rule 3).

List price is what a vendor asks, not what a buyer is willing to pay."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from nmt_engine.collect.text import html_to_text
from nmt_engine.decide import chain
from nmt_engine.sim.replay import PRICING
from nmt_engine.synth.grade import GradeInputs
from nmt_engine.verify.author import verbatim

UNTIL = "20251107"
CHARS = 20_000
ANNUAL = re.compile(r"annual|yearly|billed (?:once a |per |each )?year", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)?")
SYSTEM = "You read archived pricing pages. Answer only with JSON. Quote words exactly."
PROMPT = """Archived pricing page of {app} ({url}, snapshot {date}):

<page>
{text}
</page>

List every plan's regular list price on this page. If the page shows a promotion, use the
regular ("was" / "usually") price, not the promotional one. Free plans have price 0. Skip
add-ons, per-transaction fees and payroll. For each plan give the exact words from the page that
show the price (the quote must contain the number).
Answer as JSON: {{"plans": [{{"plan": "...", "price": <number>, "currency": "USD|GBP|EUR|CAD|...",
"period": "month|year", "per_user": true or false, "quote": "..."}}]}}"""


def latest_snapshots(store: Path, until: str = UNTIL) -> dict[str, dict]:
    """Latest status-200 snapshot per pricing URL at or before `until`, from the B4 cache."""
    best: dict[str, dict] = {}
    for line in (store / "retrieval_log.jsonl").read_text("utf-8").splitlines():
        r = json.loads(line)
        m = re.match(r"https://web\.archive\.org/web/(\d{14})id_/(.*)", r["url"])
        if not m or r.get("status_code") != 200 or m.group(1)[:8] > until:
            continue
        for app, u in PRICING.items():
            if u in m.group(2) and (app not in best or m.group(1) > best[app]["stamp"]):
                best[app] = {"stamp": m.group(1), "url": r["url"], "key": r["cache_key"]}
    for s in best.values():
        raw = json.loads((store / "cache" / f"{s['key']}.json").read_text("utf-8"))["text"]
        s["text"] = html_to_text(raw)
        s["date"] = f"{s['stamp'][:4]}-{s['stamp'][4:6]}-{s['stamp'][6:8]}"
    return best


def _ok(row: object, text: str) -> bool:
    if not isinstance(row, dict) or not isinstance(row.get("price"), int | float):
        return False
    if not verbatim(row.get("quote"), text):
        return False
    nums = [float(n.replace(",", "")) for n in NUM.findall(row["quote"])]
    return any(abs(n - float(row["price"])) < 0.005 for n in nums)


def extract(llm, app: str, snap: dict) -> list[dict]:
    text = snap["text"][:CHARS]
    rows: list[dict] = []
    for retry in (False, True):
        p = PROMPT.format(app=app, url=snap["url"], date=snap["date"], text=text)
        if retry:
            p += "\nSome quotes were not exact. Copy the words exactly, shorter if needed."
        try:
            a = llm.complete_json(p, SYSTEM, "a8.prices")
        except Exception:  # noqa: BLE001 - a failed read leaves the app without prices
            continue
        plans = a.get("plans") if isinstance(a, dict) else None
        if not isinstance(plans, list):
            continue
        kept = [r for r in plans if _ok(r, text)]
        if len(kept) > len(rows):
            rows = kept
        if kept and len(kept) == len(plans):
            break
    return [
        {
            "app": app,
            "plan": r.get("plan"),
            "price": float(r["price"]),
            "currency": r.get("currency"),
            "period": r.get("period"),
            "per_user": bool(r.get("per_user")),
            "quote": r["quote"],
            "snapshot_date": snap["date"],
            "url": snap["url"],
        }
        for r in rows
    ]


def _annual(r: dict) -> bool:
    """A per-month figure that is billed annually ("$10 per month with an annual plan")."""
    return bool(ANNUAL.search(f"{r.get('plan')} {r['quote']}"))


def entry_monthly_usd(rows: list[dict]) -> dict[str, float]:
    """Per app: the lowest paid plan in USD a month (annual / 12 only if no monthly price)."""
    out: dict[str, float] = {}
    for app in sorted({r["app"] for r in rows}):
        paid = [r for r in rows if r["app"] == app and r["currency"] == "USD" and r["price"] > 0]
        monthly = [r["price"] for r in paid if r["period"] == "month" and not _annual(r)]
        yearly = [r["price"] / 12 for r in paid if r["period"] == "year"]
        vals = monthly or yearly
        if vals:
            out[app] = round(min(vals), 2)
    return out


def q4(entry: dict[str, float]) -> chain.Quantity:
    notes = (
        "list prices of the alternatives (one family: revealed_price); list price is not "
        "willingness to pay",
        "simulated family dropped: cross-model rho below 0.5 and SSR gold failed",
    )
    if not entry:
        return chain.Quantity("Q4", GradeInputs(anchored=False), None, notes)
    v = np.array(sorted(entry.values()))
    est = tuple(round(float(x), 2) for x in (np.median(v), *np.percentile(v, [10, 90])))
    inputs = GradeInputs(anchored=True, families=frozenset({"revealed_price"}))
    return chain.Quantity("Q4", inputs, est, notes)  # type: ignore[arg-type]
