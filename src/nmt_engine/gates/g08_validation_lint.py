"""Gate 8: validation-language lint. 'validated', 'proven', 'customers want' and
'confirmed demand' are allowed only with 'synthetic, grade S3/S4' or a MarketTouch id."""

import re

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.gates.outputs import output_texts
from nmt_engine.store import RunData

BANNED = re.compile(
    r"(?<!not )(?<!never )(?<!un)\b(validated|validation of demand|proven|customers want|"
    r"confirmed demand)\b",
    re.I,
)
QUALIFIED = re.compile(r"\bsynthetic\b.{0,80}?\b(?:grade\s*)?S[34]\b", re.I | re.S)
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def offending_sentences(text: str, touch_ids: set[str]) -> list[str]:
    out = []
    for sent in _SENT.split(text):
        if not BANNED.search(sent):
            continue
        if QUALIFIED.search(sent) or any(t in sent for t in touch_ids):
            continue
        out.append(sent.strip())
    return out


@gate(8, "validation_lint", "Validation-language lint")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    touch_ids = set(run.market_touches)
    findings: list[Finding] = []
    for obj_type, obj_id, text in output_texts(run):
        for sent in offending_sentences(text, touch_ids):
            findings.append(
                Finding(obj_type, obj_id, f"unqualified validation claim: {sent[:120]!r}")
            )
    return findings
