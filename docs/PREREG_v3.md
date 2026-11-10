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

## 10. Amendment 3 (2026-11-09, B3, before any amendment-3 labelling)

Reason: the project owner's decision after amendment 2 round 0. Of 475 query-retrieved candidates,
12 were USER posts naming a Solution, and all 38 designated pairs came back unrelated (GLM agreed
on 38/38). The query-retrieved pool is mostly BUILDER (GitHub issues) and OTHER (tax questions on
Stack Exchange), and App Store reviews never got a node rank because no query returns them.

Round 0 stays on record as run and failed: "no public evidence in this harvest" for all 10
nodes. Its items stay in `node_items.jsonl` and are not scored. Amendment 3 changes only the
candidate pool and its ranking. The labels (frozen gold author and node prompts, one
shorter-quote retry), the 80% cross-model agreement bar and the 85% precision bar stay as they
are. The frozen amendment-2 node growth is stopped. The USER test split keeps growing under
amendment 1.

Pool. Every customer-voice post of these kinds: App Store reviews of the named invoicing apps in
the L2 harvest (`runs/l2`), plus Hacker News posts that Kimi already labelled USER (in `gold.jsonl`
or `node_authors.jsonl`). Reddit is not in the first-build collectors, so it adds no posts. Round-0
node items are left out.

Ranking. For each node, every pool post is ranked by cosine similarity between its Qwen3 embedding
(`qwen/qwen3-embedding-8b`) and the embedding of the node's closed question (the statement the node
check asks about). Ties go by source id.

Pick, split and labels. These follow amendment 2. Kimi labels author role down each node's ranking
until 8 posts qualify (USER and naming a Solution), after 60 candidates, or when the pool runs out.
HN posts already labelled keep their label. Each node gets its top 8 qualifying posts plus 2
qualifying posts drawn at random (seed `"a3:<node>"`) from the qualifying posts outside its top 8.
The split is fixed by post id (`test` if `int(sha256(source_id), 16)` is odd). Kimi labels each
item against all 10 statements. GLM-5.3 (thinking off) labels them blind, and agreement below
80% stops the work. Only amendment-3 designated pairs are scored for the node classes.

Budget. Amendment 3 costs at most $6, embeddings included. B3 stays at or under $20 in total.

Pre-registered outcome. If the producer's supports plus contradicts calls on the test split come to
fewer than 20 in total, node precision is NOT MEASURED and T2 FAILS. Per §5 the product then
narrows to the Radar (problems + alternatives), which is recorded, and the work goes on to B4
without stopping. With 20 or more, T1 runs as written, and then T2 runs if T1 allows it.

## 11. Amendment 4 (2026-11-09, B4, before any simulation, SSR-gold or replay run)

Reason: §6 fixes T3 but leaves the simulator, the SSR scoring, "usable", "beats" and the event
date rule open. This amendment fixes them before any L6 output exists. §6 and ARCHITECTURE_v3 §5
are unchanged except where a rule below says so. B3 ended with T2 FAILED, so the product is
narrowed to the Radar. L6 still runs, behind the firewall: its output never counts toward L4,
T2 or a Job node (gate 13).

Agents. One agent per L1 segment (G1–G5), defined by its Core Jobs and its criteria in order.
Each agent is grounded by up to 5 masked quotes (first 300 characters) from posts Kimi labelled
USER naming a Solution (`gold.jsonl`, `node_authors.jsonl`), ranked by Qwen3 cosine similarity
to the segment's text. Only post ids go to git. In a replay, only posts published before the
freeze date are eligible.

World. In the main world each agent starts once on every L1 Solution whose `serves` overlaps its
Core Jobs, and the offers are the other L1 Solutions. Each run is one round under one condition:
no change, incumbent price +10%, incumbent price +50%, a new entrant, the incumbent drops a Job,
a service takes the Job off the customer, and a competitor copies the incumbent's best feature.
The prompt gives the agent its criteria in order, the 6 costs, the five switching conditions
(push, pull, habit, anxiety, barriers) and the condition. It answers in 2–4 sentences of free
text and never gives a number. The producer (DeepSeek V4.1 Flash) runs the world.

SSR. Each outcome has 3 fixed anchor statements: stay, consider (looks but does not move yet),
and switch to X, one outcome for every offer X. The response and anchors are embedded with Qwen3.
With s_i the outcome's mean cosine similarity, p_i ∝ s_i − min_j s_j + 0.01. P(switch) is the sum
over the switch outcomes.

SSR gold (CI gate, ARCHITECTURE_v3 §4 rule 3). Kimi writes 150 synthetic answers, 50 for each
intended class (stay, consider, switch), across the 5 segments and the 7 conditions. These are
model-written, not human-verified. Split by answer id (`test` if `int(sha256(id), 16)` is odd).
The predicted class is the largest of P(stay), P(consider) and P(switch). Bar: per class ≥85%
precision with ≥20 test calls; fewer than 20 is NOT MEASURED. Anchors may be changed on dev only.
Similarities are committed under the anchor-set hash, and CI fails if they are missing or below
the bar. If SSR fails, T3 does not run and the simulation ships as "exploratory, unvalidated".

Cross-model stability. The main world runs on DeepSeek, GLM-5.3 (thinking off) and Kimi. Cells
are agent × incumbent × condition, and the value is P(switch). ρ is the lowest pairwise
Spearman. ρ < 0.5: unusable (exploratory, and Q4/Q7 lose the simulated family). 0.5 ≤ ρ < 0.8:
the simulated family is capped at S1. ρ ≥ 0.8: no cap.

Internal validity (reported, not a gate). Repeat consistency is the mean absolute difference in
P(switch) over 3 DeepSeek repeats (the prompt carries the repeat number). Scale compression is
the standard deviation of P(switch) across cells. Preserved relationship is the share of agent ×
incumbent pairs where P(switch) for none ≤ +10% ≤ +50%.

Replay events (replaces "date known to the day" in §6). Products: the 10 apps in
`briefs/invoicing.l2.json`. Wayback monthly snapshots of each pricing page since 2019-01-01. A
candidate is a pair of consecutive snapshots whose diff adds or removes a line with a currency
amount, and Kimi confirms from the diff that it is a price or plan change (closed question with
a verbatim quote). Daily snapshots between the pair bracket the change: T0 is the last snapshot
with the old page and T1 the first with the new one. A gap above 31 days makes the event
unusable. Evidence is frozen at T0 − 1 day (leakage guard), and outcomes are counted from T1.

Options. For every event: the other 9 apps, plus "a spreadsheet", "invoices by hand (word
processor and email)", "an accountant or bookkeeper" and "a self-built tool". The list is fixed
before outcomes are read.

Prediction. The 5 agents start on the product. The condition is the change, taken from the
diff lines as they are. Offers are the options by name. The prediction is the option with the
highest mean P(switch to X) across agents (DeepSeek). The baseline is the option named most
often, by a code count of names, in posts mentioning the product dated in the 365 days before
T0 (HN comments and App Store reviews). Ties go to option order. Predictions and baselines for
every candidate event are written and committed before any outcome is read.

Outcomes. Posts mentioning the product dated T1 to T1 + 365 days (HN comments and App Store
reviews). For each one, Kimi answers a closed question with a verbatim quote: does the author
say they themselves left or are leaving the product, and for which option (or "other" or "not
said")? One vote per author hash. An event is usable if at least 3 authors name an option.

Beats and pass. The simulator beats the baseline on an event if the actual share of its top
option is strictly greater than the actual share of the baseline's top option. When the two
pick the same option, the simulator does not beat it. T3 passes if there are at least 3 usable
events and the simulator beats the baseline on at least 2/3 of them. With fewer than 3 usable
events, T3 is undecidable (A6) and the simulation ships as "exploratory, unvalidated".

Budget. The $20 run cap and the step caps (`sim` $8) apply. B4 as a whole stays at or under $20.

## 12. Amendment 5 (2026-11-09, B4, SSR aggregation; before any world run)

Reason. On the SSR-gold **dev** split, summing P over the five switch outcomes made "switch" the
top class for 74 of 78 dev answers, whatever the answer said: each outcome keeps at least the
floor mass, and five switch outcomes face one stay and one consider. The first recording also
printed the test split (switch 26/72, stay and consider 0 calls); that run is on record as failed
and this amendment was written from dev numbers only. Separately, and within the amendment-4
rule (anchors may change on dev), the stay and consider anchors now name the incumbent, as the
switch anchors name the destination.

Rule. With s_stay and s_consider the mean anchor similarities and s_switch the highest switch
outcome's (best destination), P over {stay, consider, switch} is p_i ∝ s_i − min_j s_j + 0.01.
Within switch, P(switch to X) = P(switch) · q_X, with q_X ∝ s_X − min_Y s_Y + 0.01 over the
switch outcomes (q = 1 with a single offer). Everything else in amendment 4 is unchanged: the
top class is the largest of P(stay), P(consider), P(switch); each class needs ≥ 20 test calls and
≥ 85% precision; the T3 prediction is the highest mean P(switch to X).

## 13. Amendment 6 (2026-11-10, B4 resumed after T2 FAILED; before any further B4 run)

Reason. T2 failed, so the product narrowed to the Radar. The user then chose to keep the full
plan: B4 resumes and runs to the B6 report. This amendment fixes what the simulation may claim,
what it is calibrated on and how T3 is run, before any new world, replay or outcome run. Runs
made before it (the amendment-4 DeepSeek and GLM worlds and the partial Kimi world, about $0.84)
stay on record as superseded and are not reported as results. Amendments 4 and 5 still hold
except where a rule below says otherwise.

1. Evidence status is fixed from B3. All 10 riskiest nodes are **unknown**. J2, J3 and S2 have
   some supporting posts (4 designated supporting pairs: J2 ×2, J3, S2), below the L4 bar of
   ≥ 3 distinct authors from ≥ 2 families, so their status is unknown. The other 7 have no public
   evidence in the amendment-3 harvest. 0 of 10 are supported and 0 are contradicted. No L5, L6
   or replay output may change a node's status (gate 13 and the `simulated` firewall unchanged).

2. Synthetic labelling. Every Job claim that comes from L5 or L6 is written to the ledger and
   the report labelled **SYNTHETIC (simulation estimate)**, with its interval and the inputs it
   was calibrated on (post ids, the class each was measured on, and the flag "unmeasured" where it
   applies). L6 intervals: a cell value (agent × incumbent × condition) is shown with the range
   over models and repeats; any aggregate (a condition's mean P(switch), a share) is shown with a
   90% percentile bootstrap over cells (2,000 resamples, seed 6). L5 intervals are the conformal
   intervals L5 already produces.

3. Calibration inputs. The simulation is grounded only on what was measured:
   - the quote pool stays the posts Kimi labelled USER naming a Solution (USER: PASS, precision
     against model labels);
   - each agent's 5 quote slots start with up to 2 of the 4 supporting posts (N014, N015 for J2;
     N022 for J3; N029 for S2): those whose node is one of the agent's Core Jobs, or S2 when an
     agent's incumbents include S2, nearest first by Qwen3 cosine; the rest are filled by cosine ×
     weight, nearest first;
   - weight 1.0 if the post carries a problem tag (Kimi gold label for B1 gold posts; the
     producer's tag, which passed the problem gate, for L2 posts), 0.6 if it carries only
     unmeasured tags (trigger, success criterion, alternative, aha), 0.5 if it carries none. So
     the unmeasured classes add 0.1 at most: they are inputs at low weight and flagged as
     unmeasured in the calibration record;
   - the segment texts, Core Jobs and criteria order come from the L1 hypothesis graph, which has
     0 of 10 nodes supported; the record flags them as unmeasured structure.

4. T3 runs even though SSR failed. Amendment 4 said T3 does not run if SSR fails. It now runs
   as pre-registered and is reported. Because the SSR gold failed (stay 18/23 = 78%, switch
   23/30 = 77%, bar 85%), the simulation section of the report is marked **exploratory** whatever
   T3's result. If T3 fails or is undecidable, it is exploratory too, and the build continues.

5. Replay events, pinned. Pricing pages (Wayback, monthly snapshots, status 200, from 2019-01-01
   to 2025-11-07, so that every outcome window ends before the harvest):

   | App | Page |
   |---|---|
   | Bonsai | hellobonsai.com/pricing |
   | FreshBooks | freshbooks.com/pricing |
   | Harvest | getharvest.com/pricing |
   | Invoice Ninja | invoiceninja.com/pricing-plans |
   | Invoice2go | invoice.2go.com/pricing |
   | QuickBooks | quickbooks.intuit.com/pricing |
   | Wave | waveapps.com/pricing |
   | Xero | xero.com/us/pricing-plans |
   | Zoho Invoice | zoho.com/invoice/pricing |

   Invoice Simple has no archived pricing page, so it has no events (it stays an option). A
   candidate is a consecutive pair whose diff adds or removes a line with a currency amount
   (`$`, `€`, `£` followed by a digit, or a number followed by USD, EUR or GBP). Daily snapshots
   between the pair bracket the change by binary search on the page's set of currency lines;
   a gap above 31 days is unusable. Kimi then confirms from the diff lines that it is a price or
   plan change (closed question, verbatim quote, one retry). Per app, confirmed events are taken
   in date order, and an event is dropped if its T1 is within 365 days of the T1 of an event
   already kept for that app, so outcome windows never overlap. The kept list, written to
   `runs/b4/replay/events.json` and committed, is the event set. Nothing else selects events.

6. Sources, baseline and prediction. Posts mentioning the app (its name, word-bounded, any
   case, except "Wave" and "Harvest", which must be capitalised because they are common words): HN comments from Algolia searched by the app name, and the B3 App Store reviews of the
   app's own listings (allow-list: Bonsai 1333596451, FreshBooks 1052884030, Harvest 355395846,
   Invoice Ninja 1503970375, Invoice2go 540236748, Invoice Simple 694831622, QuickBooks
   584606479, Xero 441880705, Zoho Invoice 413017364; the two "Wave" listings are other apps and
   are excluded). The baseline and the 13 options are as in amendment 4, with code name patterns
   fixed in `nmt_engine.sim.replay.OPTIONS`. The prediction uses the 5 agents built from posts
   published before the freeze date (T0 − 1 day), each starting on the app, with the condition
   "{app} changed its pricing page." followed by the removed and added diff lines (at most 12,
   200 characters each), DeepSeek, 3 repeats. Prediction = highest mean P(switch to X) over agents
   and repeats; ties go to option order. Predictions and baselines for every event are committed
   before any outcome post is fetched.

7. Outcomes. Window T1 to T1 + 365 days. Pre-filter by code, before any model reads a post: the
   post names the app and contains a leaving word (`left`, `leave`, `leaving`, `switch*`,
   `moved`/`moving` `to`/`from`/`away`, `migrat*`, `cancel*`, `dropped`, `replac*`, `ditch*`,
   `quit`). At most 60 posts per event: if more pass, the 60 with the smallest
   sha256(event id + post id). Kimi answers the amendment-4 closed question with a verbatim quote
   (one retry). One vote per author hash (the author's earliest labelled post in the window).
   Usable: ≥ 3 authors name a listed option. Actual share of an option = its votes / votes naming
   any listed option. Beats and pass as in amendment 4: the simulator beats the baseline if the
   share of its option is strictly greater; T3 passes with ≥ 3 usable events and wins on at least
   2/3 of them (so 2 of 3, 3 of 4, 4 of 5 …); fewer than 3 usable events is undecidable.

8. Order and budget. The `sim` step cap stays $8 for all of B4 (spent before this amendment:
   $1.35). Order: calibrated DeepSeek world (3 repeats) and GLM world; replay events, predictions
   and outcomes (outcome labelling at most $2); then the Kimi world. If the Kimi world would
   take B4 past $8, it stops there, and cross-model stability is reported on DeepSeek and GLM only,
   saying so. Kimi world answers may use up to 4,000 output tokens, because the first run was cut
   off at 1,200.

## 14. Amendment 7 (2026-11-10, B5; before any B5 model call)

T2 failed and T3 is UNDECIDABLE with the simulation exploratory (amendments 3 and 6). B5 builds
the Radar inputs (`docs/RADAR_SCOPE.md`) and the L5/L7 decision step on what B1–B4 measured.
Nothing here changes a B3 label, T1, T2 or T3, or any node status.

1. **Pool.** The amendment-3 App Store reviews restricted to an app-ID allow-list of the nine L2
   invoicing listings (`replay.APPSTORE_IDS`): this drops the two unrelated "Wave" listings
   (ids 1523884528 and 1506820334, 60 reviews). Plus the 16 HN posts labelled USER. The pool has
   11 App Store ids in total, not 13 as earlier text said; the earlier number was a miscount.
2. **Producer pass.** DeepSeek runs the frozen B3 producer prompts (author gate, then element
   tags) on every pool post, batch 8, as recorded for T1. The Radar keeps posts the producer
   calls USER and tags with a problem: the two classes that PASS (precision against Kimi model
   labels, human check NOT DONE). Other element tags are not used.
3. **Problem groups.** Qwen3 embeddings of the masked post text (first 300 characters), cosine,
   k-means with k = 12 and seed 0 (scipy `kmeans2`, `++` init, on unit vectors). k is fixed here
   and not tuned. Each group reports distinct author hashes, apps, a count per year, the mean
   star rating and the share of all Radar posts. A group with fewer than 3 distinct authors or
   fewer than 2 apps is shown as "thin". Kimi names each group from the 8 posts nearest its
   centroid, with a verbatim quote from one of them and one retry; the name is a label, not a
   finding. Counts are voices in this pool, not market prevalence.
4. **Alternatives map.** Deterministic only: the app each review is about (store metadata) and
   the other listed options named in the text (the `replay.option_patterns` matcher). No model
   alternative tag is used (NOT MEASURED).
5. **L5 quantities.** Q1–Q9 are graded by the existing code (`synth.grade`). The simulated
   family is dropped (cross-model ρ < 0.5; T3 UNDECIDABLE). B1–B4 collected no supply-side,
   statistical or revealed-price inputs that are tied to this Job and segment, so every Q is
   graded from what exists, with no new collection in B5.
6. **L7 decision.** The Monte Carlo (≥ 10,000 runs, seed 0) runs only when every Q on the chain
   to profit is at least S1. Synthetic validation follows ARCHITECTURE_v3 L7 verbatim. If it
   fails, the report shows no money figure and the decision is NO GO to build; the next step is
   the cheapest market touch (T4).
7. **Red team.** GLM-5.3 (thinking off), clean context, receives only the report packet (the
   claims and their receipts, as JSON). It lists claims that overreach their receipts and any
   single input that would flip the conclusion. Every finding is recorded and shown in the
   report; an overreaching claim is reworded or removed, and the change is logged.
8. **Budget.** B5 at most $6: producer pass $3, group naming $1, red team $2 (`redteam` step
   cap). A step that would exceed its cap stops and is reported.

## 15. Amendment 8 (2026-11-10, B6 fixes after the user read the first report; before any run)

The user read the first Groundwork report and approved three fixes while T4 waits. Nothing here
changes a B3 label, T1, T2, T3, a node status, page 1, the simulation section or its labels, or
the NO GO. The original k = 12 group table stays in the report as an appendix.

1. **Merged themes.** Input: the 12 amendment-7 groups exactly as recorded in `runs/b5/radar.json`
   (membership is not recomputed). Each group's centroid is the normalised mean of its members'
   cached Qwen3 vectors (the same masked first 300 characters; no new embedding spend).
   Agglomerative merge with average linkage on cosine distance between centroids (scipy
   `linkage(method="average", metric="cosine")`), cut with `fcluster(criterion="distance")` at
   the 25th percentile of the 66 pairwise centroid distances. The threshold is fixed here as that
   quantile, before any merge is seen, and is not tuned. Whatever number of themes it gives is
   reported. A theme's label is the name of its largest member group (by distinct authors), with
   the member group names listed under it; no model call. Distinct voices per theme are the
   union of member author hashes, so an author with posts in two merged groups counts once.
2. **Single-app concentration.** For each theme (and each original group in the appendix): the
   share of its distinct authors who reviewed its largest app. Over 50% is flagged
   "mostly one app: <name>".
3. **List prices into Q4.** Source: for each of the 9 amendment-6 pricing URLs, the latest
   status-200 Wayback snapshot at or before 2025-11-07 that the B4 replay already fetched (read
   from the B4 collector cache via its retrieval log; no new harvest). DeepSeek V4.1 Flash reads
   the snapshot text (first 20,000 characters) and lists each plan's list price as
   `{plan, price, currency, period, quote}`; the list price is the regular price, so where a
   page shows a promotion, the "was"/"usually" price is used. A row is kept only if its quote is
   verbatim in the snapshot text and contains the price digits; one retry on failure. The table
   records app, plan, price, currency, billing period, snapshot date and URL.
   Q4 input per app: the lowest paid (non-zero) plan in USD per month (monthly billing; if only
   an annual price is shown, annual / 12). Q4 estimate = (median, 10th, 90th percentile) across
   apps with a value, numpy linear interpolation. Q4 is graded by `synth.grade` with
   `anchored=True` and one family (`revealed_price`), so the frozen rule gives at most S1. List
   price is not willingness to pay; the report says so. The Monte Carlo still runs only if every
   Q on the chain is at least S1 (amendment 7 rule 6).
4. **Red team.** GLM-5.3 (thinking off) reads only the changed sections (themes, concentration,
   price table and Q4 grade) as JSON, with the amendment-7 prompt; findings are shown and
   answered in the report as before.
5. **Budget.** At most $2 of model spend for this amendment (step `a8`): price extraction and the
   red team. A call that would exceed it stops and is reported.
