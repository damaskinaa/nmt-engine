"""L1 prompts. Written for this engine; no canon text. Changing a prompt changes its hash, and the
consistency gold set (A1) then needs re-recorded outputs."""

from __future__ import annotations

from nmt_engine.util import sha256_text

DRAFT_SYSTEM = "You draft hypotheses for market research. You reply with JSON only."

DRAFT_PROMPT = """Brief
Goal: {goal}
Market, as a Job: {market_job}
Geography: {geography}
The new product could cover: {product_reach}

Draft a hypothesis Job Graph for this market. Everything is an assumption to be checked later
against public evidence, so write plain, checkable statements in the words customers would use.

Nodes (every node, of every type, has id, type, text, rationale, rat):
- job: one Big Job (level "big", no parent): the market Job above, in your words. Then 3 to 5
  Core Jobs (level "core", parent = the Big Job), and under each Core Job its Small Jobs (level
  "small") and, where useful, Micro Jobs (level "micro", parent = a Small Job). Levels are
  relative to what the new product could cover. Every job text starts with exactly "I want to "
  followed by a verb ("I want to see every unpaid invoice", never "I want one list of ..." or
  "I want the invoice to ..."), and names an outcome the person wants, not a feature.
- solution: what people hire today to get Core Jobs done: named products, services, spreadsheets,
  manual methods, home-made tools. kind is one of product, service, spreadsheet, manual, diy.
  serves = the job ids it is used for (at least one Core Job).
- criterion: how a person judges that a job went well (e.g. "money arrives without chasing").
  job = the job id it judges. Every Core Job has at least two.
- segment: 3 to 6 candidate customer groups. A segment is NOT a demographic: it is defined by the
  Core Jobs it does (core_jobs: ids of level "core" jobs only) and the ORDER in which it weighs
  success criteria (criteria_order, most important first, at least 2 criterion ids).
  No two segments share the same order. The text names the group by what it does and what it
  values first.
- problem: a way a Solution falls short on criteria for a job; text says how, in the customer's
  words. solution = solution id, job = the job the person used it for, criteria = the criterion
  ids it fails. A solution serves only jobs it actually helps get done.

For every node, rationale says in one sentence why you believe it. rat rates how risky the belief
is, by picking tiers, never numbers:
  p_wrong: low | medium | high - how likely the belief is wrong
  cost_if_wrong: low | medium | high - how much a product built on it would lose if it is wrong
  cost_to_check: low | medium | high - how costly it is to check with public evidence
  reason: one sentence for the three tiers

Rules: no numbers, prices, shares or counts anywhere except inside product names. ids are J1, J2..
for jobs, S1.. solutions, C1.. criteria, G1.. segments, P1.. problems. status is not needed.

Reply as JSON: {{"nodes": [{{"id": "J1", "type": "job", "level": "big", "text": "I want to ...",
"rationale": "...", "rat": {{"p_wrong": "low", "cost_if_wrong": "high", "cost_to_check": "low",
"reason": "..."}}}}, ...]}}
{feedback}"""

FEEDBACK = """
Your previous draft is below. It was rejected for these reasons:
{errors}

Previous draft:
{draft}

Reply with the full corrected graph. Change only what the reasons require; keep every other node
exactly as it was.
"""

CHECK_SYSTEM = "You check a research hypothesis graph for internal consistency. JSON only."

CHECK_PROMPT = """Market, as a Job: {market_job}

Each numbered statement below is one link in a hypothesis graph about this market. For each, answer
whether the link is internally consistent: does it make sense on its own terms? You are not judging
whether it is proven, only whether the two things linked fit together.
Answer "yes" if it fits, "no" if it does not (wrong parent, a criterion that does not judge that
job, a solution not used for that job, a problem that solution cannot cause, a segment whose order
contradicts the jobs it does). Give a short reason for every "no".

{statements}

Reply as JSON: {{"answers": [{{"n": 1, "consistent": "yes" | "no", "reason": "..."}}, ...]}}
with one answer per statement, in order."""


def prompt_hash() -> str:
    return sha256_text(CHECK_SYSTEM + CHECK_PROMPT)[:16]
