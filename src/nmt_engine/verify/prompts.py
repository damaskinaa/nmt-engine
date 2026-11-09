"""L3 prompts. Closed questions only; every yes needs a quote copied from the post.

The auditor labels the gold set with the frozen GOLD_* prompts. The producer prompts may be
refined on the gold dev split; any change changes the prompt hash and must be re-recorded."""

from __future__ import annotations

ROLES = ("USER", "BUILDER", "VENDOR", "OTHER")
ELEMENTS = ("trigger", "success_criterion", "alternative", "problem", "aha")

GOLD_AUTHOR_SYSTEM = (
    "You classify who wrote public posts about a product category. You answer closed questions "
    "only and back every answer with a quote copied exactly from the post. Output JSON only."
)

GOLD_AUTHOR_PROMPT = """Category: {category}

Roles (pre-registered boundary rules, set by the project owner):
- USER = the author describes their OWN experience with a {category} Solution they use, used, \
paid for, evaluated or left. This includes someone who replaced a paid tool with a self-built \
one, if they name what they left and why (it is a switching story, which is user evidence).
- BUILDER = the author writes code, specs, issues or developer questions for something they are \
building, and does not promote it to customers. API "how do I" questions count as BUILDER even \
if the author also invoices.
- VENDOR = the author promotes or launches their own product to get users: Show HN, links, \
pricing pitch, vouchers, "try it".
- OTHER = job ads, CVs, commentary not about their own {category}, and tax or accounting \
questions that don't involve a {category} tool.
Tiebreaks, in order: promotes own product -> VENDOR. Otherwise, names a prior Solution and the \
reason for leaving -> USER. Otherwise, mainly code or specs -> BUILDER.
Each label must cite the verbatim phrase that decided it.

Posts (possibly cut short):

{posts}

For each post answer:
1. role: one of USER, BUILDER, VENDOR, OTHER.
2. role_quote: the verbatim phrase from the post that decided the role, copied exactly.
3. names_solution: true only if the author names a product, service, spreadsheet or manual method \
that they themselves use or used for this category's work.
4. solution: that name, or null. solution_quote: the phrase naming it, copied exactly, or null.

Return {{"posts": [{{"id": <post number>, "role": "...", "role_quote": "...", \
"names_solution": <true|false>, "solution": <string|null>, "solution_quote": <string|null>}}, \
...]}} with one entry per post."""

GOLD_ELEMENT_SYSTEM = (
    "You check public posts for specific kinds of statement. You answer yes or no and back every "
    "yes with a quote copied exactly from the post. When unsure, answer no. Output JSON only."
)

GOLD_ELEMENT_PROMPT = """Category: {category}

Questions, each about the author's own experience:
- trigger: does the post say what event or change made the author start looking for, or change, \
how they do this work?
- success_criterion: does the post say how the author judges whether this work went well (for \
example faster, cheaper, fewer errors, paid on time)?
- alternative: does the post name another product or method the author used, tried or compared?
- problem: does the post say that a product or method the author uses falls short for them?
- aha: does the post describe the moment the author first saw that a product or method worked \
for them?

Posts (possibly cut short):

{posts}

For each post and each question answer true or false; for true, give a quote copied exactly from \
the post, else null.
Return {{"posts": [{{"id": <post number>, {fields}}}, ...]}} with one entry per post."""

ELEMENT_FIELDS = ", ".join(f'"{e}": <true|false>, "{e}_quote": <string|null>' for e in ELEMENTS)

AUTHOR_SYSTEM = GOLD_AUTHOR_SYSTEM
AUTHOR_PROMPT = GOLD_AUTHOR_PROMPT.replace(
    "Each label must cite the verbatim phrase that decided it.",
    "Each label must cite the verbatim phrase that decided it.\n"
    "Checks before answering USER (all must hold, else pick another role):\n"
    "- OWN: the experience is the author's own work. A spouse's, employer's or client's system \
the author only describes is OTHER.\n"
    "- SOLUTION: the post is about a {category} Solution the author relies on, not a passing \
mention inside commentary on something else (computers, AI, jobs, ERP stories). Passing mentions \
are OTHER.\n"
    "- SELF-BUILT: someone who built their own {category} tool is USER only if they name the \
product they left and why; otherwise a list of their projects or a note about building it is \
BUILDER.",
    1,
)  # producer refinement, tuned on the dev split only
assert AUTHOR_PROMPT != GOLD_AUTHOR_PROMPT
ELEMENT_SYSTEM = GOLD_ELEMENT_SYSTEM
ELEMENT_PROMPT = GOLD_ELEMENT_PROMPT.replace(
    "- alternative: does the post name another product or method the author used, tried or \
compared?",
    "- alternative: does the post name another product or method the author used before, tried \
or compared, besides the one they rely on now? The tool they use now is not an alternative.",
    1,
).replace(
    "- problem: does the post say that a product or method the author uses falls short for them?",
    "- problem: does the post say that a product, service or method the author uses for this work \
falls short for them? A dispute with a supplier, or a bug report about the author's own project, \
is not a problem with a product they use.",
    1,
)
assert ELEMENT_PROMPT != GOLD_ELEMENT_PROMPT

# --- step b: node check (PREREG_v3 amendment 1) -------------------------------------------------

VERDICTS = ("supports", "contradicts", "unrelated")

GOLD_NODE_SYSTEM = (
    "You check what authors of public posts say about their own experience against fixed "
    "statements. You answer closed questions only and back every supports or contradicts with a "
    "quote copied exactly from the post. Unrelated is the default. Output JSON only."
)

GOLD_NODE_PROMPT = """Category: {category}

Each post below was written by someone describing their own experience with a {category} \
Solution. Check each statement against what the author says about their OWN experience.
- supports: the post shows the statement is true for the author (they do it, use it, judge by it \
or have that problem).
- contradicts: the post shows the statement is false for the author (they do the opposite, do not \
need it, judge by something else instead, or say the Solution does what the statement says it \
fails at).
- unrelated: anything else, including posts that do not touch the statement. When unsure, answer \
unrelated.
Every supports or contradicts needs a quote copied exactly from the post.

Statements:
{statements}

Posts (possibly cut short):

{posts}

For each post answer every statement.
Return {{"posts": [{{"id": <post number>, "answers": [{{"node": "<statement id>", \
"verdict": "supports|contradicts|unrelated", "quote": <string|null>}}, ...]}}, ...]}} with one \
entry per post."""

NODE_SYSTEM = GOLD_NODE_SYSTEM
NODE_PROMPT = GOLD_NODE_PROMPT
