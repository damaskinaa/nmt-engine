"""Prompt templates. They are written to runs/<id>/prompts/ so gate 10 can scan them."""

ELEMENTS = (
    "context",
    "trigger",
    "job",
    "success_criteria",
    "alternatives",
    "negative_emotions",
    "positive_emotions",
    "higher_goal",
)
VALUE_MARKERS = ("problem", "aha", "workaround")
CONTEXT_TYPES = (
    "review",
    "switching_story",
    "how_to",
    "workaround",
    "recommendation_request",
    "complaint",
    "praise",
    "other",
)
LEVELS = ("big", "core", "small", "micro")
JOB_TYPES = ("regular", "orientation", "tax", "fake", "emotional", "viral")

EXTRACT_SYSTEM = """You read public posts (reviews, forum comments, Q&A, issues) and extract the \
jobs their authors are trying to get done. You copy evidence; you never invent it.

Rules:
- Every span you return MUST be copied character for character from the post (a contiguous \
substring, 3 to 40 words). Do not fix typos, translate, paraphrase or join pieces. If you are \
not sure a span is verbatim, leave it out.
- Only extract what the author says about their own situation or people they work for. Skip \
marketing copy, generic opinions and jokes. A post may contain zero jobs.
- Never output numbers of your own: no scores, counts, probabilities or estimates.
- Output JSON only, no commentary."""

EXTRACT_PROMPT = """Category under study: {category}

For each post, give:
- "context_type": one of {context_types}
- "jobs": list of jobs (may be empty). For each job:
  - "statement": the job in the form "I want to <verb> ..." (your words, max 15 words, no \
product names)
  - "level": one of {levels} (big = life/business goal, core = the main task, small = a step, \
micro = a click-level action)
  - "type": one of {job_types} (tax = work the author does only because a tool falls short)
  - "order": position of this job in a first-I-then-I sequence the author narrates (1, 2, ...), \
else null
  - "search_query": a 2-5 word web search someone doing this job would type, else null
  - verbatim span lists (each [] if the post has no evidence):
    "context" (situation/circumstances), "trigger" (what made them start now), "job" (where they \
say what they try to get done), "negative_emotions", "positive_emotions", "higher_goal" (the \
bigger goal this job serves), "problem" (product under-delivered vs expectation), "aha" \
(over-delivered / pleasant surprise), "workaround" (extra work to compensate)
  - "success_criteria": list of {{"label": "<2-4 word criterion, e.g. 'fast setup'>", "span": \
"<verbatim>"}}
  - "alternatives": list of {{"name": "<product, tool or manual method named in the post>", \
"span": "<verbatim span containing the name>"}}

Return {{"posts": [{{"i": <post number>, "context_type": ..., "jobs": [...]}}, ...]}} with one \
entry per post.

{posts}"""

MERGE_SYSTEM = """You group job statements that describe the same job (same goal, maybe worded \
differently). Do not group jobs that merely share a topic. Output JSON only."""

MERGE_PROMPT = """Category: {category}

Job statements (id: statement):
{items}

Return {{"groups": [{{"ids": [<ids of statements that are the same job>], "statement": "I want \
to ..."}}]}}. Every id must appear in exactly one group; a job that matches no other is its own \
group."""
