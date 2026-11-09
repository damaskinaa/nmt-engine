# Pre-registration v3: invoicing thin slice (T1, T2, T3)

Written in B2, before the L1 graph is generated and before any B3–B5 verdict run. The PR records
this file's sha256. Results never change these rules (ARCHITECTURE_v3 §4 rule 5). Any change made
after this commit becomes a new pre-registration, with its own hash and a stated reason, and
applies only to runs that start after it.

Source of truth: `docs/ARCHITECTURE_v3.md` on `main`, including §8 (C1–C4, A1–A9).

## 1. Fixed inputs

| Input | Value |
|---|---|
| Market | `briefs/invoicing.json`: "I want to get paid in full and on time for work I have done for clients" |
| Hypothesis graph | `briefs/invoicing.l1.json`, generated once in B2. Its sha256 goes in the B2 PR and is frozen from then on. B3 never edits it |
| Producer | `deepseek/deepseek-v4.1-flash`, reasoning off, temperature 0 |
| Auditor | `moonshotai/kimi-k3.1-pro`, temperature 0 |
| Third model | `z-ai/glm-5.3`, thinking off |
| Embeddings | `qwen/qwen3-embedding-8b` |
| Host | TensorX (`https://api.tensorx.ai/v1`) only |
| Budget | $20 per run, enforced in code with per-step caps |
| Collectors (L2) | hackernews, stackexchange, appstore (reviews only), github, web (competitor pages), wayback |
| Active gates | 1, 2, 4, 7, 8, 10, 11, 13, 14 |

## 2. Riskiest nodes

- **Which nodes count:** jobs except the Big Job, solutions, criteria and problems. Segments are left out, because they are tested in L6 by simulation and a desk quote can't support a criteria order. The Big Job is the brief itself.
- **Priority:** the model picks a tier (low, medium or high) for P wrong, cost if wrong and cost to check. Code turns each tier into a number:

  | tier | P wrong | cost |
  |---|---:|---:|
  | low | 0.2 | 1 |
  | medium | 0.5 | 3 |
  | high | 0.8 | 9 |

  Priority = P wrong × cost if wrong / cost to check.
- **Ranking:** by priority, highest first. Ties go to higher PageRank importance (damping 0.85), then to node id.
- **Selection:** the 10 riskiest are the top 10 of that ranking, as written in the frozen graph's `riskiest` field.

## 3. T1: verification precision

T1 is precision against **model labels**. The L3 gold labels are Kimi's (model-labelled, not human-verified). The B1 human check was NOT DONE. The substitute was cross-model agreement with GLM-5.3: 91.3%, kappa 0.88.

- **Classes (A3):**
  - USER in the author gate;
  - supports and contradicts in the node check (node-check gold is added in B3, labelled by Kimi);
  - trigger, success criterion, alternative, problem and aha in element tagging.
- **Status per class**, on the held-out test split:

  | test calls | precision | status |
  |---|---|---|
  | fewer than 20 | any | NOT MEASURED |
  | 20 or more | ≥ 85% | PASS |
  | 20 or more | < 85% | FAIL |

  NOT MEASURED is never a pass.
- **What each class gates:**
  - USER, supports and contradicts gate T2. The T2 verdict run starts only if all three PASS.
  - An element tag gates only the outputs that use it. For example, trigger evidence appears in the report only if trigger PASSes.
- **Growing the test split:** B3 adds held-out posts until every class has at least 20 calls on test. New posts are drawn the same way (family-stratified) and labelled by Kimi with the frozen prompts. If a class still has fewer than 20 calls after the gold pool runs out, it is reported as NOT MEASURED. For USER, supports or contradicts, that means T2 does not run, and the build stops for the user.
- **Prompts:** no prompt change is tuned on test items. Each prompt change gets a new prompt hash and a new recording, and the test split is scored once per prompt hash.

## 4. Node status (L4)

- **Who counts:** a voice is a distinct salted author hash, on a post the author gate calls USER that names a Solution the author uses or used (A4). USER posts without a named Solution count toward Problems only.
- **Supported:** at least 3 voices with a "supports" quote, from at least 2 customer-voice families (discussion, support_issue, qa, review).
- **Contradicted:** the mirror rule. At least 3 voices with a "contradicts" quote, from at least 2 customer-voice families (A5).
- **Unknown:** everything else. A node that meets both rules is unknown and flagged **contested**.
- **Context only:** vendor pages, change history, search demand and market records never count as voices.
- **Firewall:** simulation output never counts as a voice (gate 13).

## 5. T2: desk evidence decisive

- **Pass:** at least 5 of the 10 riskiest nodes end supported or contradicted.
- **Fail:** the product narrows to the Radar (problems plus alternatives). The rule's outcome is reported as is.
- **One harvest:** T2 uses one harvest planned from the 10 riskiest nodes (customer-word queries), with collection, L3 and L4 under the run budget. Nodes still unknown after it stay unknown. A second harvest would be a new run with a new pre-registration.

## 6. T3: simulation predicts

- **Events:** past price or plan changes of invoicing products, found in Wayback history. An event is usable if its date is known to the day and at least 3 USER posts after the date say where switchers went.
- **Fewer than 3 usable events (A6):** T3 is undecidable, and simulation ships as "exploratory, unvalidated".
- **Replay:** evidence is frozen as of the day before each event (leakage guard). The simulator's top destination is compared with where switchers actually went.
- **Baseline:** the most-mentioned alternative before the date.
- **Pass:** the simulator beats the baseline on at least 2 of 3 events, or the same share if there are more events.
- **Cross-model stability (L6):** the same run on DeepSeek, GLM and Kimi. Spearman ρ < 0.5 means the simulation is unusable; 0.5–0.8 caps it at S1.

## 7. L1 consistency gate (not a verdict, recorded here so it can't move)

- **Pass:** the graph is schema-valid and Kimi answers "consistent" for every link. Otherwise the graph is regenerated with feedback, at most twice, and then flagged.
- **Consistency gold:**
  - Real links of the frozen graph are "consistent".
  - Code-corrupted links are "inconsistent": a link is re-pointed at a node under a different Core Job.
  - Dev and test are split by origin node.
- **Gate:** the same precision rule as T1, for both classes, with Kimi's answers committed under the check prompt hash.

## 8. Amendment 1 (2026-11-09, B3, before any T1 or T2 run)

Written before the L2 harvest, before the node-check gold exists, and before any test split is
scored for a T1 verdict. It corrects one stale figure and fills in details §3 left open. It
changes no threshold and no rule in §2–§7. The PR records the new sha256.

**Correction to §3.** The cross-model figure in §3 (91.3%, kappa 0.88) was from round 2, which
was superseded. The final round used the project owner's frozen role rules: 262 of 292 posts
agree (89.7%), Cohen's kappa 0.86, USER-class agreement 93.5%. GLM left 8 posts unlabelled after
its one shorter-quote retry. The gold set stays model-labelled (Kimi), not human-verified; the
human check stays NOT DONE.

**Node check (§3, supports and contradicts).**
- **Candidate nodes:** the 10 riskiest nodes of the frozen graph (§2).
- **Statements:** code writes one statement per node from the frozen graph, by node type:
  - job: the author needs to do that Job;
  - solution: the author uses that Solution for the Jobs it serves;
  - criterion: the author judges that Job by that criterion;
  - problem: the author has that problem with that Solution.
- **Answers:** supports, contradicts or unrelated per post and node, with a verbatim quote for
  supports and contradicts. Unrelated is the default.
- **Gold items:** every gold post that Kimi labels USER and naming a Solution (A4), crossed with
  the 10 candidate nodes. A pair takes its post's split.
- **Gold labels:** Kimi, with a frozen gold node prompt committed before labelling; one try plus
  exactly one retry with a shorter quote, as in B1.
- **Calls:** a class's test calls are the producer's answers of that class on test pairs that
  Kimi answered.

**Producer prompts.** The producer prompts may be refined on dev only. They are frozen before
growth round 1 and do not change during growth. The B3 refinement of the author prompt was
tuned on the 200 dev posts.

**Growing the test split (§3).**
- **Pool:** customer-voice posts (discussion, support_issue, qa, review) from the one L2 harvest
  of §5, minus posts already in the gold set (same source id or URL).
- **Rounds:** 150 posts per round, stratified by evidence family, seeded with the round number.
  Every new post goes to test.
- **Labels:** Kimi labels each new post with the frozen author and element prompts, then
  node-labels the posts it calls USER and naming a Solution.
- **Stop:** when USER, supports and contradicts each have at least 20 test calls, or after 6
  rounds (900 posts), or when the pool runs out, whichever comes first.
- **Then:** each class is scored once on test (§3). A class still under 20 calls is NOT
  MEASURED. For USER, supports or contradicts, that means T2 does not run, and the build stops
  for the user.

## 9. Amendment 2 (2026-11-09, B3, before any node-check T1 is scored)

Reason: the project owner's decision after the first node gold (19 random gold USER posts × 10
nodes) came back 190/190 unrelated. Random posts are unrelated to a given node almost by design,
so that design could not measure supports or contradicts. That first node gold is kept as a record
(`node_gold_amend1.jsonl`) and is never scored. This amendment replaces amendment 1's "Gold items"
and its growth rule for the node classes only. Thresholds and the USER rules are unchanged.

Pool. Customer-voice posts from the L2 harvest (`runs/l2`, the plan hash committed in
`briefs/invoicing.l2.json`) that are not already node items. A post's rank for node n is the best
(lowest) position at which any query listed for n returned it, counting from 0 within each step.
Ties are broken by source id.

Who counts as USER. Kimi labels author role with the frozen gold author prompt (one try plus one
shorter-quote retry), working through each node's candidates in rank order. A post qualifies if
it is USER and names a Solution (§8 A4). For each node, labelling stops when 8 qualifying posts are
found, after 60 candidates, or when the candidates run out, whichever comes first.

Pairs. For each node: its top 8 qualifying posts by rank, plus 2 qualifying posts drawn at random
(seed `"<round>:<node>"`) from the qualifying posts not retrieved for that node at all, or failing
that, from the qualifying posts outside that node's top 8. A (post, node) pair is a designated pair.
Each node item is checked against all 10 statements in one call (same frozen prompts as
amendment 1), but only designated pairs are scored.

Split. Fixed by post before any labelling: `test` if `int(sha256(source_id), 16)` is odd, else
`dev`. All pairs of a post share its split.

Growth. If supports or contradicts has fewer than 20 producer calls on test, each growth round r
(1 to 6) adds, per node, the next 8 qualifying posts by rank plus 2 random negatives. Only posts not
yet node items are eligible, and every growth post goes to `test`. The USER test split still grows
by the amendment 1 rule (150 random posts per round, stratified by family).

Canary. Before any node-gold labelling, 6 synthetic pairs (2 obvious supports, 2 obvious
contradicts, 2 unrelated) run through the frozen gold node prompt. If Kimi gets an obvious supports
or contradicts wrong, the prompt is broken and gets fixed on dev before any gold labelling. Canaries
never count toward T1.

Cross-model check. GLM-5.3 (thinking off) labels every node item blind with the same prompt.
Agreement and Cohen's kappa are computed over designated pairs. At 80% or above, gold stays Kimi.
Below 80% the work stops and the owner is told. This is called cross-model agreement, never
human-verified.

Reporting. Any node with 0 supports and 0 contradicts in node gold is reported per node as "no
public evidence in this harvest". It is not padded.
