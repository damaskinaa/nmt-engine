"""L3 prompts. Closed questions only; every yes needs a quote copied from the post."""

from __future__ import annotations

ROLES = ("USER", "BUILDER", "VENDOR", "OTHER")
ELEMENTS = ("trigger", "success_criterion", "alternative", "problem", "aha")

AUTHOR_SYSTEM = """You classify who wrote public posts about a product category. You answer closed \
questions only and back every answer with a quote copied exactly from the post. Output JSON only."""

AUTHOR_PROMPT = """Category: {category}

Roles:
- USER: uses, used, pays or paid for, or is looking for a product or method in this category for \
their own work or life.
- BUILDER: builds, maintains or is writing their own product or tool in this category.
- VENDOR: speaks for a company that sells a product in this category (staff, founder, support, \
marketing).
- OTHER: anyone else (commentator, journalist, moderator, unclear).

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

ELEMENT_SYSTEM = """You check public posts for specific kinds of statement. You answer yes or no \
and back every yes with a quote copied exactly from the post. When unsure, answer no. Output \
JSON only."""

ELEMENT_PROMPT = """Category: {category}

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
