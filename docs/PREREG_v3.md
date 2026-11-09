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
