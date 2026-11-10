# Radar scope (invoicing): what B1–B3 can support

T2 failed (PREREG_v3 §5, amendment 3). The product narrows to the **Radar**: problems plus
alternatives. This page covers what a Radar report for the Job "get paid in full and on time for
work I have done for clients" can contain using only what B1–B3 built and measured. It also lists
which later builds it still needs. All precision figures are against model labels (Kimi), not
human-verified, and the human check is NOT DONE.

## Measured inputs

- **Author gate, USER:** 75/77 = 97.4% on test, recall 75/84. PASS.
- **Element tag, problem:** 44/44 on test. PASS.
- **Not measured (fewer than 20 test calls):** trigger, success criterion, alternative, aha,
  supports, contradicts.
- **Customer-voice pool:** 3,343 App Store reviews from 13 listings, dated 2023-01 to 2026-11.
  - By country: US 2,276, GB 1,037, IE 30.
  - Distinct author hashes: 3,330.
  - Also in the pool: 16 HN posts labelled USER.
  - Each review carries the app it was written about and its star rating.

## What the report contains

1. **Problem radar.** The producer runs L3 on the pool and keeps USER posts tagged with a
   problem. Similar problems are grouped together, and each group shows:
   - the number of distinct voices;
   - the number of apps it appears for;
   - a count per year, 2023–2026;
   - its mean star rating;
   - 2–3 masked verbatim quotes with links.

   These counts measure voices in this pool, not market share or prevalence.
2. **Alternatives map.** The alternatives come from two measured or deterministic sources, never
   from the alternative tag, which is NOT MEASURED:
   - the app each review is about (store metadata);
   - other L2 apps and L1 Solutions named in the text, found by a deterministic name match.

   Switching stories ("left X for Y because …") come from USER posts that name a prior Solution,
   which the USER definition covers. The map shows who mentions which alternative and the top
   problem per app, not flows or shares.
3. **Riskiest-assumption list.** The 10 riskiest nodes (J2, J3, C3, C4, J11, P3, J4, J5, S2, J12)
   are all **unknown**:
   - 7 have no public evidence in this harvest;
   - J2, J3 and S2 have a few supports, below the 3-voice, 2-family bar.

   The report presents them as open questions with a suggested check, not as findings.
4. **Method and limits.** This section states that the labels are model labels and that the
   human check is NOT DONE. It also covers:
   - **Bias:** the pool leans to mobile app users and to US/GB.
   - **Wave name collision:** 60 reviews come from two unrelated "Wave" listings (Wave Mobile
     Money, a dating app) and must be dropped by an app-ID allow-list.
   - **What the Radar does not answer:** profitability, sizing or "next move" claims.

## What it cannot contain

- Node support or contradiction.
- Triggers, success criteria or aha moments.
- Simulated respondents.
- Any money figure (EVPI, Monte Carlo, prioritisation by profit).

## Which of B4–B7 it still needs

| Build | Needed for the Radar? | What |
|---|---|---|
| B4 (simulation, SSR, replay) | **No** | SSR gold already failed its gate (stay 78%, switch 77% on test), so the simulation would ship "exploratory, unvalidated". On hold for the user's decision. |
| B5 (L5 wiring, red team) | **Partly** | Needed: L3 over the pool (producer, about $5–10 at about $0.003 a post); problem grouping (Qwen3 embeddings + Kimi naming, under $1; the current build has no clustering code); the name matcher; the app-ID allow-list; and a Kimi red-team read of the draft. Not needed: L7 Monte Carlo and synthetic validation. |
| B6 (report HTML/PDF) | **Yes** | The four sections above, with receipts. |
| B7 (site, demand test) | **Only to publish** | A landing page and demand test for the Radar itself. Not needed for the first report. |
