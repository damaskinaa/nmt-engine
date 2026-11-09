# Groundwork / nmt-engine: Master Architecture v3

**Status:** single source of truth, 9 Nov 2026. It replaces files 02, 06, 07, 08, 09 and 11; those
are history only. Files 04 (synthetic evidence protocol), 10 (simulation research) and 12
(landing page) remain references and are folded in here.

---

## 0. Summary

We are building **Groundwork**: a research report on any market, built only from public data
plus calibrated simulation, where every sentence is either backed by a receipt or carries a
graded synthetic label. It is produced by **nmt-engine**, which runs the NMT algorithm
(goal → diagnosis → hypothesis Job Graph → research → real Job Graph → value → RAT) without
interviews and without customer data.

**What went wrong so far, and what changes:**

| Before | Now |
|---|---|
| Mine Jobs out of hundreds of random posts and hope a graph appears | Start from a **hypothesis Job Graph**, then confirm or refute each node with evidence (the NMT order) |
| Interview-grade bar (4 of 8 Job elements) applied to forum posts | Each node's status is **supported / contradicted / unknown**. Unknown is a valid, useful output |
| The AI fills 8 slots per post | **Closed questions only**: "is this a user?", "does this support node N?", always with a verbatim quote |
| Search for the category word (finds people building the product) | Queries are generated from the riskiest nodes, **in customers' words** |
| 14 gates, 20 collectors, PRs of 56k lines | **One market end to end**, 8 gates, 6 collectors, PRs of about 1,500 lines |
| No test that anyone wants it | **Landing page** (built) is test T4, and its sign-ups are the first real report requests |

---

## 1. Your requirements, and where each one is met

| # | You said | Where it lives |
|---|---|---|
| R1 | Improve the NMT research process (SOP v1 → v2) | §3: the layers *are* the SOP; §6 run book |
| R2 | Derive product ideas from NMT and test them as hypotheses | §2 product; §5 tests T1–T4; every layer has a kill criterion |
| R3 | No customer interviews, no existing customer data: desk research + simulation only, advanced reasoning | L2–L6 use only public data and simulation. L9 market touch is a public demand test, not an interview |
| R4 | Synthetic WTP, market size and validation must be **citable**, reverse-engineered from the canon, the harnesses, the chat ideas and the canon GitHub; strong assumptions on real data; best data sources | L5 (S0–S4 grades, triangulation, conformal calibration, backtests), L7 (definition of synthetic validation), §3 data catalogue, chat ideas mapped in §3 |
| R5 | One full Devin prompt, not pieces | §7: one hand-over message; this document is the spec in the repo |
| R6 | EU / Irish LLM provider | TensorX only (Dublin, zero retention): DeepSeek V4.1 Flash produces, Kimi K3.1 Pro audits, Qwen3 embeddings |
| R7 | Reassess; it must not break | §4 engineering rules, gold sets in CI, budgets, small PRs |
| R8 | MiroFish principles / the strongest similar tools, reverse-engineered | L1 (seed graph), L6 (agents + world + interventions + report agent), plus what MiroFish lacks: historical replay validation, SSR, cross-model stability |
| R9 | Must follow NMT principles | §2 mapping table; segments = Core Jobs + order of success criteria; study people who used or paid; value = prediction delta; RAT; subtraction |
| R10 | Landing page connected to the build | `site/` in the repo; L9; `nmt intake` turns sign-ups into report requests |
| R11 | Devin continues on its own | §7: PR sequence with stop points; it only waits for you at three named checks |

---

## 2. The product

| | |
|---|---|
| Customer (hypothesis) | Founders and PMs about to build, before interviews |
| Core Job | Decide which customer group and problem to bet on before spending build money |
| Output | **Groundwork report** for one market: Job Graph with node status, segments by criteria order, Consideration Set and switching flows, problems with voice counts, Q1–Q9 estimates with grades, simulation of switching under interventions, top-3 RAT with the cheapest real test |
| Price test | €49 vs €149 on the landing page |
| Delivery now | Concierge: the engine plus a human check, within 3 working days |

**NMT principles in the engine:**

| Principle | Implementation |
|---|---|
| Job = desired transition, 8 elements, "I want to + verb" | L1 node schema; L3 attaches evidence per element *when it exists* |
| Levels are relative (Big / Core / Small / Micro) | L1 sets them relative to the brief's product reach |
| Segment = similar Core Jobs + **order** of success criteria; never demographics first | L1 candidate segments are defined by criteria order; L6 agents are segments, not personas |
| Study people who *used or paid* for a Solution | L3 author gate: USER + names a Solution they use or used |
| Problem = Solution under-delivering against criteria | L1 links Problem → Solution → Job; L3 verifies |
| Value = energy efficiency vs prediction; Aha = beating it | L6 agent decision rule; L5 Q8 value gap |
| Consideration Set, switching = swapping Job Graphs | L2 "switched from / alternative to" queries; L6 switching simulation |
| Chain to profit, diagnosed top-down | L7 Monte Carlo over Q1–Q9 along the chain; failing node is named |
| RAT: concrete, falsifiable, ranked by (P × cost) / cost to test | L1 RAT priority on every node; L7 EVPI; L8 top-3 with cheapest test |
| Subtraction | §4: one market, fewer gates and collectors; L7 drops strategies that can't move the goal |
| Unit economics | L5 Q4–Q6, Q9 |

**Licence:** the canon is CC BY-NC-SA. The engine applies the *method* (ideas aren't copyrighted).
No canon text goes into prompts or reports that ship: gate 10 checks n-gram overlap. The site
doesn't use the "Next Move Theory" or Zamesin names.

---

## 3. Architecture (L0–L9)

```
L0 Brief ─▶ L1 Hypothesis Job Graph ─▶ L2 Targeted harvest ─▶ L3 Verify ─▶ L4 Evidence ledger
                    ▲                                                          │
                    │                       L5 Quantities Q1–Q9 ◀──────────────┤
                    │                       L6 Simulation world  ◀─────────────┘
                    │                               │
                    └──── re-plan (loop) ◀── L7 Decision (MC + EVPI) ─▶ L8 Report ─▶ L9 Market touch
                                                                                     │
                                                         forecasts scored ◀──────────┘
```

Status key: **built** = merged on main · **salvage** = in PR 4/5, move into a new PR · **new**.

### L0 Brief and market screening (new)
- Input: goal plus market **in Job terms** ("money people spend to get paid for work they
  did"), not a category.
- Multi-market screening (chat 718): run a quick Q1–Q4 for 3–5 candidate markets, rank them, and
  go deep on 1. *The first build covers invoicing only.*

### L1 Hypothesis Job Graph: the MiroFish "seed graph", in NMT form (new)
- The producer drafts: Big Job → Core Jobs → Small / Micro Jobs; the Solutions hired today
  (named competitors, DIY, spreadsheets); success criteria; 3–6 candidate segments, each
  defined by criteria order; the Problems each Solution creates.
- Every node gets: `status = assumed`, rationale, RAT priority = (P wrong × cost if wrong) / cost
  to check, and graph importance (PageRank, chat 1111).
- Output: a schema-validated graph. **No numbers are invented here.**
- Kill criterion: the schema validates and a second model (Kimi) agrees the graph is
  internally consistent. Otherwise regenerate (max 2), then flag it.

### L2 Targeted harvest (built: collectors, safe hosts; new: query planner)
- Queries come **from the 10 riskiest nodes**, in customer words: "alternative to X",
  "switched from X", "X too expensive", "how do I <job>", "X vs Y".
- Collectors for the first build: HN, Stack Exchange, App Store **reviews** (never app
  descriptions), GitHub issues, competitor pages, Wayback pricing/changelog history.
- Behavioural traces: prices and plan tiers, price-change dates, review counts over time,
  co-usage from integration directories (chat 718).
- Data catalogue for L5 (file 04 §6): CSO, Eurostat, ONS, Companies House, SEC EDGAR, TED,
  Vendr report, Adzuna, npm/PyPI, Twin-2K-500. Every source needs an `access_basis`
  (gate 14). Excluded: LinkedIn/Glassdoor, logged-in scraping, unlicensed G2/Capterra/Trustpilot.

### L3 Verify, don't mine (salvage: auditor, embeddings; new: prompts)
- Step a, **author gate**: USER / BUILDER / VENDOR / OTHER, plus "names a Solution they use or
  used", with a verbatim quote. Only USER posts continue.
- Step b, **node check**: for each USER post × candidate node: supports / contradicts /
  unrelated, with a verbatim quote. "Unrelated" is the default.
- Step c, **element tagging** (only where present): trigger, success criterion, alternative,
  problem, aha. Each is a yes/no with a quote.
- Producer DeepSeek; auditor Kimi on a 20% sample; precision is measured on the gold set (§4).
- Kill criterion (**T1**): precision ≥ 85% on the held-out gold set, else no run proceeds.

### L4 Evidence ledger and node status (built: store, gates)
- Node status: **supported** (≥ 3 USER voices, ≥ 2 customer-voice evidence families) /
  **contradicted** / **unknown**, with the receipts.
- Evidence families: discussion, support_issue, qa, review count as customer voice;
  vendor_page, change_history, search_demand and market_record are context only.
- Active gates: 1 quote exists, 2 voices, 4 calc recompute, 7 source exists, 10 licence,
  11 diversity (by family), 13 simulation firewall, 14 access basis. The others are off by
  default.
- Kill criterion (**T2**): ≥ 5 of the 10 riskiest nodes end decisive (supported or
  contradicted).

### L5 Quantities Q1–Q9: citable synthetic estimates (built: PR 2 core)
- Q1 reachable segment, Q2 Job frequency, Q3 Job budget (→ market size), Q4 WTP, Q5
  cost-to-serve, Q6 CAC, Q7 adoption, Q8 value gap, Q9 retention.
- ≥ 3 method families per quantity (statistical, supply-side, revealed price, behavioural trace,
  simulated respondents), combined in log space. ρ is estimated from joint reference classes;
  the interval is split-conformal; backtests run as of a date with the leakage guard.
- **Grades:**
  - S0 unanchored: never cited
  - S1 anchored
  - S2 triangulated
  - S3 calibrated: citable with a label
  - S4 market-touched
- The citation label is generated by code. "Validated", "proven" or "customers want" are
  forbidden without "synthetic".
- The misspecification matrix already passes (81.5–89.8% coverage at the nominal 80%).

### L6 Simulation world: MiroFish's structure, NMT's decision rule, plus validation (new)

| MiroFish element | Ours |
|---|---|
| Personas from the seed graph | **Segment agents**, one per L1 segment. Each is grounded by retrieving *that segment's* supporting USER quotes (no per-person twins, so no GDPR profiling) |
| Simulated world over rounds | **Switching world:** each agent holds its current Solution. Each round it judges the offers on the market: outcome vs its criteria in its order, minus the 6 costs (money, time, effort, cognitive load, negative emotion, Tax Jobs), against its prediction. Habit, fear and barriers apply (chat 315: the five switching conditions) |
| God's-eye injection | **Interventions:** price change, new entrant, kill a Job, take the Job off the customer, a competitor copies a feature. Each one is a logged experiment |
| Agent answers | Free text, scored by **SSR** (arXiv 2510.08338) against anchor statements (stay / consider / switch to X / pay tier). The model never outputs numbers |
| Report agent | L8 strategist (below) |
| Chat with agents | "Ask the segment", always labelled SIMULATED |
| *Nothing* | **Validation:** (a) **cross-model stability**: the same run on DeepSeek, GLM and Kimi; Spearman ρ < 0.5 means unusable, 0.5–0.8 caps at S1 (arXiv 2609.13148). (b) **Internal validity**: repeat-consistency, scale compression, preserved relationships between answers (arXiv 2609.30030). (c) **Historical replay**: find past price or plan changes in Wayback, freeze evidence as of the day before, simulate, compare with where switchers actually went (posts after the date), against a "most-mentioned alternative" baseline. Forecasts go in the registry |

- Firewall: simulation output **never** becomes a receipt for a Job node or counts toward T2.
  It feeds Q4 and Q7 as the "simulated respondents" family only, graded by its replay record.
- Kill criterion (**T3**): replay on ≥ 3 past events; the simulator beats the baseline in ≥ 2.
  If it fails, simulation ships as "exploratory, unvalidated".

### L7 Decision (built: EVPI, forecast registry; new: Monte Carlo over the chain)
- Monte Carlo (≥ 10k runs, fixed seed) over the calibrated Q1–Q9 along the chain to profit:
  P(margin ≥ target), P(CAC payback ≤ target), P(volume supports the goal); Q8 > 0 vs the best
  alternative.
- **Synthetic validation** (file 04 §5): Q1–Q4 and Q7 ≥ S3, the rest ≥ S2, the three
  probabilities ≥ 0.6, Q8 > 0 with p ≥ 0.8, and the red team finds no single input that flips
  the result.
- Red team: a different model family with clean context receives only the packet (chat
  288–289, 297 N independent estimators).
- EVPI ranks what to learn next. **GO to build** when validated *and* the top EVPI is below the
  cost of the cheapest market touch. Otherwise run that test (chat 1384/1385: strategy as a Tax
  Job, so stop when more analysis doesn't pay).

### L8 Strategist report: Groundwork (new; uses the built viewer)
- Produces the 6-part strategy object (chat 1373): target segment + Core Job, value hypothesis
  and mechanic, why we win, unit economics, demand plan, top-3 RAT with the cheapest test each.
- Every sentence carries a receipt or a generated citation label; simulated content is marked.
  All gates run on the report.
- Output: HTML report (built viewer) + PDF.

### L9 Market touch and learning loop (built: site; new: intake)
- **Ours:** `site/`, the landing page with 3 headline variants, an email + market form, a price
  test and a privacy notice. Test **T4**: ≥ 5% click and ≥ 3 emails from about 200 founders or
  PMs.
- `nmt intake` pulls new requests from Netlify (`NETLIFY_TOKEN` in secrets). It stores the
  market and request id only; **emails stay in Netlify, never in git**. Each request becomes a
  queued L0 brief.
- **For clients:** L8 proposes a fake-door test for their idea, and its results lift that
  client's estimates to S4.
- Every S2+ estimate is a registered forecast. Reality scores it, and scores feed back into
  the calibration sets.

---

## 4. Engineering rules (why it won't keep breaking)

1. **Thin slice:** invoicing end to end before any second market or extra collector.
2. **Closed questions only** for every LLM step, each with a verbatim quote; numbers only from
   code.
3. **Gold sets in CI:** 300 labelled invoicing posts (200 dev / 100 test held out). A prompt
   change that drops test precision below 85% fails CI. The same applies to the L1 consistency
   check and SSR anchors.
4. **Unknown is a valid output.** Nothing pads.
5. **Pre-registration** before every verdict run (hash in the PR). Results never change rules.
6. **Budgets in code:** $20 per run, with per-step caps. Truncated replies fail loudly and are
   never cached.
7. **Small PRs:** one per build step, about 1,500 lines plus fixtures, one capability each, CI green before the
   next. Devin stops after each PR.
8. **Pinned models + cache:** the model id, host and prompt hash are logged; reruns replay from
   cache.
9. **Subtraction:** gates 3, 5, 6, 8, 9 and 12 are off; collectors other than the six above
   are off. Re-enable only with a reason.

---

## 5. Tests that decide what we build (pre-registered)

| Test | Pass | If it fails |
|---|---|---|
| T1 Verification | L3 precision ≥ 85% on held-out gold | Fix prompts; nothing downstream runs |
| T2 Desk evidence decisive | ≥ 5 of 10 riskiest nodes supported or contradicted | Product narrows to the Radar (problems + alternatives) |
| T3 Simulation predicts | Beats baseline on ≥ 2 of 3 historical events | Simulation labelled exploratory; Q4/Q7 lose that family |
| T4 Demand | ≥ 5% click, ≥ 3 emails from about 200 founders/PMs | Stop or change the target customer, whatever T1–T3 say |

The Session A and v2 verdicts stay on record (open mining fails).

---

## 6. Build sequence

| Step | Content | Reuses | Stops for you? |
|---|---|---|---|
| B1 | Subtraction config, gold set + CI precision gate, salvage Wilson / auditor / embeddings from PR 5, close PRs 4–5 | PR 4, 5 | **Yes:** label 30 posts blind (15 min) |
| B2 | L0 brief + L1 hypothesis graph + PREREG_v3 | store, schema | No |
| B3 | L2 query planner + L3 verify + L4 node status → **T1, T2** | collectors, gates | No |
| B4 | L6 segment agents, switching world, SSR, cross-model, historical replay → **T3** | leakage guard, registry | No |
| B5 | L7 Monte Carlo + synthetic validation + red team; L5 wired to L4/L6 | PR 2 core | No |
| B6 | L8 report (HTML/PDF), all gates on it | viewer | **Yes:** read the first invoicing report |
| B7 | `site/` deploy notes + `nmt intake` from Netlify | site | **Yes:** add `NETLIFY_TOKEN` |

Your only other job is T4: deploy the site and share it on one channel (`site/README.md`).

---

## 7. Hand-over message to Devin

```text
New plan. Read docs/ARCHITECTURE_v3.md on branch docs/architecture-v3 (GitHub PR #6).
It is the single source of truth and replaces every earlier prompt. Do not merge that PR. I'll
merge it after you confirm you've read it.

Do now:
1. Reply with any contradiction or ambiguity you see in the document, before coding.
2. Then build steps B1 → B7 in order, exactly as in §6, following the rules in §4. TensorX only
   (DeepSeek V4.1 Flash producer, Kimi K3.1 Pro auditor, Qwen3 embeddings).
   Budget $20 per run.
3. Stop and wait for me only at the three points marked "Yes" in §6. Otherwise continue to the
   next PR when CI is green and the PR description has its report.
4. Close PR 4 and PR 5 in step B1 after salvaging what §6 lists. Keep their verdicts in
   docs/VERDICTS.md.
Never put emails or other personal data in git. Never copy canon text into prompts or outputs.
```
