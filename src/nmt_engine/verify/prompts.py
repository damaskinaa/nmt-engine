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

Roles. Check them in this order and give the first that fits:
1. VENDOR: the author speaks for a business that sells or offers a product or service in this \
category: staff, founder, support, marketing, or someone launching or promoting their own product \
to others ("we built", "try it", "sign up", pricing or vouchers). Promoting a product they built \
is VENDOR, not BUILDER.
2. BUILDER: the author builds, codes, maintains or specifies software for this work but is not \
promoting it for sale: a developer asking how to implement or fix code, an API or formulas; a \
task, spec or issue written by the team that builds the project; someone who wrote, scripted or \
"vibecoded" a tool, even only for themselves.
3. USER: the author personally uses, used, pays or paid for, or is choosing a product, service, \
spreadsheet or manual method for their own work or life in this category. A bug report or \
feature request from someone using a product is USER.
4. OTHER: anyone else: job ads, CVs and "who is hiring" posts; commentary on a company, price, \
market or news without saying the author uses it; advice, or choosing tools, for someone else; \
unclear.

Posts (possibly cut short):

{posts}

For each post answer:
1. role: one of USER, BUILDER, VENDOR, OTHER.
2. role_quote: the shortest phrase from the post that shows the role, copied exactly.
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
AUTHOR_PROMPT = GOLD_AUTHOR_PROMPT  # role rules now live in the frozen gold prompt
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
