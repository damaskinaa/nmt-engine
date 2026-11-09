"""Subtraction (ARCHITECTURE_v3 §4.9, §8 C2): what is switched off, and why.

Gates and collectors listed here are off by default. Turning one back on needs a written reason,
which goes into the gate report or collect summary."""

from __future__ import annotations

GATES_OFF: dict[int, str] = {
    3: "author-entered numbers: v3 takes numbers only from code (§4.2)",
    5: "geography consistency: one market, one geography in the thin slice (§4.1)",
    6: "segment double-count: v3 segments by criteria order, not by population shares",
    9: "run manifest: replaced by pinned model, host and prompt-hash logs (§4.8)",
    12: "astroturf burst check: L3 author gate screens builders and vendors instead",
}

COLLECTORS_ON: tuple[str, ...] = (
    "hackernews",
    "stackexchange",
    "appstore",
    "github",
    "web",
    "wayback",
)
COLLECTOR_OFF_REASON = "off in v3 (§4.9): only the six L2 collectors run"


def active_gates(all_gates: list[int], reenable: dict[int, str]) -> list[int]:
    _need_reasons(reenable)
    return [g for g in sorted(all_gates) if g not in GATES_OFF or g in reenable]


def collector_on(step: str, reenable: dict[str, str]) -> bool:
    _need_reasons(reenable)
    name = step.split(":", 1)[0]
    return name in COLLECTORS_ON or name in reenable


def _need_reasons(reenable: dict) -> None:
    blank = [k for k, why in reenable.items() if not str(why).strip()]
    if blank:
        raise ValueError(f"re-enabling {blank} needs a reason (ARCHITECTURE_v3 §4.9)")
