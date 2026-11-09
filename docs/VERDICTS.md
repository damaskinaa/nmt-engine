# Verdicts on record

Earlier experiments, kept as history when B1 superseded them (ARCHITECTURE_v3 §6 B1, §8 C1).
Their code stays on the closed PR branches; B1 salvaged only the LLM client, embeddings, evidence
families, collector fixes, graph viewer and statistics.

## Session A: kill line v1 (PR #4, branch `devin/pr4-job-graph-miner`)

- **Question:** do ≥ 30% of mined jobs meet the evidence bar (≥ 4 of 8 elements, ≥ 3 voices,
  ≥ 2 source kinds)?
- **Run:** TensorX, producer `deepseek/deepseek-v4.1-flash` (chosen over `z-ai/glm-5.3` for fewer
  invented quotes: 0.39% vs 1.80% on invoicing).

| category | posts | invented quotes | jobs | jobs meeting bar | share |
|---|---:|---:|---:|---:|---:|
| habit tracker (consumer app) | 447 | 0.46% | 213 | 16 | 7.5% |
| feature flags (developer tool) | 450 | 0.29% | 313 | 10 | 3.2% |
| invoicing (SMB SaaS) | 486 | 0.39% | 141 | 8 | 5.7% |

- **Verdict: KILL LINE HIT**, 3 of 3 categories below 30%. Narrow to Problems + Consideration
  Sets (Radar first).
- LLM cost: $0.51 for the three runs, $1.39 including the model check.

## Kill line v2 (PR #5, branch `devin/pr4b-miner-v2`)

- Pre-registered before any re-run: `docs/PREREG_killline_v2.md` on that branch,
  sha256 `1255636ecd82e922a923379c93d15fcd465ae56e401da5083c88274e05fdbab3`.
- Changes tested: embedding clustering (`qwen/qwen3-embedding-8b`, t* = 0.18 from 200 Kimi pair
  labels, F1 0.60), source diversity by evidence family, Kimi semantic audit of 400 spans.
- Audit excluded 5 of 8 elements (context, trigger, negative emotions, positive emotions, higher
  goal: lower 95% Wilson bound of wrong labels > 20%), so the 4-of-8 pass rule could no longer be met.

| category | R0 (v1) | R1 | R2 | R3 | R4 (verdict) |
|---|---:|---:|---:|---:|---:|
| habit tracker | 7.5% | 3.3% | 3.3% | 2.3% | 0.0% |
| feature flags | 3.2% | 0.3% | 0.3% | 0.3% | 0.0% |
| invoicing | 5.7% | 0.4% | 0.4% | 0.8% | 0.0% |

- R4 is 0% in all categories at t* and at t* ± 0.05 (habit tracker over-merged at t* + 0.05).
- **Verdict: KILL LINE v2 HIT.**
- Human checks (30 pairs, 20 spans): **not done**, by the owner's decision; pair and span
  agreement were not measured. They cannot change the verdict because R4 is 0% at every threshold.
- Diagnostic only, not part of the verdict: 40.2% of the 400 audited spans (38.5% of 314 distinct
  posts) were written by people building a product in the category rather than using one
  (habit tracker 52%, invoicing 44%, feature flags 24%). This motivated the v3 author gate (L3a).
- Full report: `docs/REPORT_killline_v2.md` on that branch.

## B1: L3 gold set (invoicing, PR #7)

- **Gold labels:** model-labelled (Kimi, `moonshotai/kimi-k3.1-pro`), **not human-verified**.
  Current roles: USER 46, BUILDER 85, OTHER 109, VENDOR 60 (round 3).
- **Human check (§8 A2, 30 blind labels): NOT DONE.** The labels were skipped by decision.
- **Weaker substitute, cross-model agreement:** `z-ai/glm-5.3` (thinking off) labels the same
  300 posts blind with the same frozen prompts (`tests/gold/invoicing/cross_agreement.json`).
  - **Round 1 (first gold role definitions):** 223 of 288 posts agree (77.4%), kappa 0.68. This
    is below the 80% bar, so B1 stopped. Disagreements were USER vs BUILDER/OTHER and
    BUILDER vs VENDOR.
  - **Round 2 (option A, assistant-written rules):** the role definitions were sharpened into an
    ordered rule (VENDOR > BUILDER > USER > OTHER) and committed before any re-run. Result: 263
    of 288 posts agree (91.3%), kappa 0.88. Superseded by round 3, which uses the owner's rules.
  - **Round 3 (option A, the one pre-registered retry, owner's rules):** the owner's boundary
    rules and tiebreaks (VENDOR first; then a named prior Solution plus the reason for leaving
    is USER; then code or specs is BUILDER; each label cites the deciding phrase) were committed
    into the frozen gold prompt before relabelling (commit `f90a386`). Each model got one try
    plus exactly one retry with a shorter quote. Kimi labelled all 300; GLM left 8 unlabelled
    after the retry. Result: 262 of 292 posts agree (**89.7%**), kappa **0.86**; USER class
    93.5% (kappa 0.74). This passes the 80% bar, so **gold = Kimi labels** (branch 2) and the
    producer was re-recorded against it. Cost: Kimi $3.72, GLM $0.20, producer $0.06.
  - **Element tags:** these prompts did not change. Kappa is weak for success_criterion (0.21),
    alternative (0.47) and aha (0.40).
- **T1:** every T1 number from this gold set is **precision against model labels**, not against
  human labels.

## Known weaknesses carried forward

- **L3 author gate: USER precision below 85% (B1 gold set, invoicing).** The producer
  (`deepseek/deepseek-v4.1-flash`, prompt hash `b5b0f532e5df5c5a`) is measured against the
  round-3 Kimi gold:
  - **Test:** precision 10/12 = 83.3%, recall 10/16 = 62.5%.
  - **Dev:** precision 23/29 = 79.3%, recall 23/30 = 76.7%.
  - **Status:** NOT MEASURED (fewer than 20 calls), and the point estimate is below 85%.
  - **Recall history:** recall was 42% (13/31) against the round-1 gold. That gold had a broader
    USER definition.
  - **Owner: B3.** Target: USER recall ≥ 60% at USER precision ≥ 85%, on a test split large
    enough for 20 or more calls per class. B1 is not blocked on it.
  - **B3 status: fixed.** After the dev-only prompt fix (hash `77cc88767bdfe9df`) and growth
    round 1 (150 posts, all to test), USER test precision is 75/77 = **97.4%** with recall
    75/84 = 89%, and problem is 44/44. Both now have 20 or more calls and PASS (precision
    against model labels). Growth stopped after round 1: each round costs about $3.2, and the
    remaining element classes (trigger 6, success_criterion 2, alternative 5, aha 0 test calls)
    would not reach 20 within the B3 budget. They stay NOT MEASURED.

## B3: node verification (T1 nodes, T2) — invoicing

- **Round 0 (amendment 2, targeted harvest pairs): run and failed.** 12 posts qualified (USER
  naming a Solution), 38 designated pairs, Kimi and GLM both said unrelated for all 38. Finding
  for all 10 nodes: "no public evidence in this harvest". Kept on record, not scored.
- **Amendment 3 (customer-voice pool, Qwen3 ranking):** pool 3,359 posts (3,343 App Store
  reviews, 16 HN USER posts; no Reddit collector in the first build). Per node, top 8 by
  embedding similarity to the closed question plus 2 random, split by post id. 38 posts
  qualified; 33 items, 85 designated pairs (33 dev, 52 test). Canary 6/6 (amendment 2).
  - **Kimi node gold:** 4 supports (J2 ×2, J3, S2), 0 contradicts, 81 unrelated.
  - **Cross-model agreement (GLM-5.3, thinking off):** 82/85 = 96.5%, kappa 0.55; passes the
    80% bar. Not human-verified.
  - **Producer on test:** supports 1/1 called, contradicts 0 called.
  - **Cost:** $1.62 (cap $6). B3 total about $11 (cap $20).
- **Pre-registered outcome: supports + contradicts have 1 test call (< 20). Node precision is
  NOT MEASURED and T2 FAILS.** Per §5 the product narrows to the **Radar** (problems +
  alternatives): downstream layers report problems and alternatives, and no node is reported as
  supported or contradicted by public evidence.
- **Planner finding (affects future harvests, not this test):** the L2 planner retrieved
  BUILDER/OTHER-heavy sources (GitHub issues, tax questions on Stack Exchange). New plans now
  carry `source_weights` (App Store 2.0, HN 1.0, Stack Exchange 0.3, GitHub 0.3).
- **Harvest data-quality finding:** 60 of the 3,343 App Store reviews come from two unrelated
  listings that share the name "Wave" (Wave Mobile Money 58, a dating app 2). They were in the
  amendment-3 pool, but none was selected as a node item or labelled. Future App Store harvests need an
  app-ID allow-list.
- **Scope after T2:** `docs/RADAR_SCOPE.md` describes the Radar report that B1–B3 can support
  and which of B4–B7 it still needs. B4 (simulation) is on hold pending the owner's decision.
