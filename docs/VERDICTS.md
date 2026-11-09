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
  Current roles: USER 50, BUILDER 101, OTHER 92, VENDOR 57.
- **Human check (§8 A2, 30 blind labels): NOT DONE.** The labels were skipped by decision.
- **Weaker substitute, cross-model agreement:** `z-ai/glm-5.3` (thinking off) labels the same
  300 posts blind with the same frozen prompts (`tests/gold/invoicing/cross_agreement.json`).
  - **Round 1 (first gold role definitions):** 223 of 288 posts agree (77.4%), kappa 0.68. This
    is below the 80% bar, so B1 stopped. Disagreements were USER vs BUILDER/OTHER and
    BUILDER vs VENDOR.
  - **Round 2 (option A):** the role definitions were sharpened into an ordered rule
    (VENDOR > BUILDER > USER > OTHER) and committed before any re-run. Both models then
    relabelled. Result: 263 of 288 posts agree (**91.3%**), kappa **0.88**, which passes. GLM left
    12 posts unanswered.
  - **Element tags:** these prompts did not change. Kappa is weak for success_criterion (0.21),
    alternative (0.47) and aha (0.40).
- **T1:** every T1 number from this gold set is **precision against model labels**, not against
  human labels.

## Known weaknesses carried forward

- **L3 author gate: USER precision below 85% (B1 gold set, invoicing).** The producer
  (`deepseek/deepseek-v4.1-flash`, prompt hash `ff9227c435465ec4`) is measured against the
  round-2 Kimi gold:
  - **Test:** precision 14/19 = 73.7%, recall 14/19 = 73.7%.
  - **Dev:** precision 24/31 = 77.4%, recall 24/31 = 77.4%.
  - **Status:** NOT MEASURED (fewer than 20 calls), but the point estimate is below 85%.
  - **Recall history:** recall was 42% (13/31) against the round-1 gold. That gold had a broader
    USER definition.
  - **Owner: B3.** Target: USER recall ≥ 60% at USER precision ≥ 85%, on a test split large
    enough for 20 or more calls per class. B1 is not blocked on it.
