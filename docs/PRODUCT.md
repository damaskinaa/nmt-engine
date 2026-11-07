# NMT Project — Desk-and-Simulation Product Ideas Derived from NMT

**Constraint (set by you, 7 Nov 2026):** every idea must work **without customer interviews and without any existing customer's data**. Allowed inputs:
- (a) **public desk data**, lawfully accessed
- (b) **simulation data**: synthetic populations, Monte Carlo and agent simulations

**Sources:**
- The "Как делать продукт 2.0" introduction-module chat (464 messages, 27 Aug – 7 Nov 2026)
- NMT Canon & Skills v0.6.18 (`f8e87d1`, CC BY-NC-SA 4.0)

> **Claim discipline:**
> - **Voices** = independent chat participants who showed the Job themselves.
> - **Status:** `QUOTE` / `DERIVED` / `HYPOTHESIS`.
> - This is a Russian-speaking learner chat, so it is a demand signal and not validation.

---

## 0. The reasoning that shapes everything below

**1. NMT's own rule is "study what people *did*, not what they say they'll do."** Much of the public record is exactly that: traces of past behaviour.

| Public trace | What it is, in NMT terms |
|---|---|
| A product review | A person who **hired a Solution** for a Job and reports outcome vs expectation. Problems (under-delivery) and Aha moments (over-delivery) |
| "Moved from X to Y" posts | **Switching events**, with triggers and fears |
| "X vs Y" / "alternatives to X" searches and threads | The **Consideration Set** at choice time |
| "How do I…" questions in forums, issue trackers and Q&A | **Critical-Chain breaks** and **Tax Jobs** (workarounds) |
| Search query sequences (autocomplete, "people also ask", related searches) | The **order of Jobs**, i.e. edges of the Job graph |
| Search volume | **Frequency × population** proxy |
| Cost-per-click (CPC) | What sellers pay to reach someone mid-Job, so a **lower bound on the Job's commercial value**. It's a budget proxy, not customer budget |
| Pricing pages, public filings, job postings, changelogs | The **business graphs** and **where each competitor is investing** (focus vs sprawl) |

So a large share of the NMT layer can be built from desk data alone:
- market in Job terms
- segment hypotheses
- Job graphs
- Consideration Sets
- Problems, Aha moments, Tax Jobs
- competitors by Job

**2. Simulation is legitimate for some things and illegitimate for others.**

| Legitimate | Illegitimate |
|---|---|
| Monte Carlo over unit economics with ranges taken from desk data | Treating synthetic "customers" as evidence of demand or willingness to pay |
| Ranking strategies | Absolute numbers from personas |
| Computing **which assumption matters most** (value of information) | |
| Stress-testing messaging *relatively*, with a model calibrated on historical public outcomes | |

LLM personas are known to be agreeable, uniform and over-optimistic about paying. Raw, they are `SIMULATED` and never cited.

**Update — `04_Synthetic_Evidence_Protocol.md` supersedes this table.** Synthetic WTP, market size and validation *can* be cited once they reach grade **S3**:
- anchored on real data
- triangulated across ≥ 3 data families
- backtested on ≥ 20 known cases with conformal intervals
- registered as forecasts

They are always cited with their grade, interval and track record.

**3. The honest ceiling.** Desk + simulation produce **ranked, auditable hypotheses and the cheapest next test**. They do not prove demand. The one proof that needs neither interviews nor customer data is **market behaviour**: ad click-through, waitlist sign-ups, prepayments on a fake-door page. Every idea below ends in that kind of test.

**4. Your edge in this space is integrity, not access to data.** Anyone can scrape reviews. Few people produce desk research where every claim has a receipt, numbers recompute, single signals are separated, and simulations are calibrated and labelled. That is the SOP + Convr-gates DNA.

---

## 1. Bottom line

The best NMT project under this constraint is an **"Outside-In Next-Move Engine"**: NMT's chain to profit, built entirely from public evidence and simulation. It is shipped as three products on one core:

1. **Desk Job-Graph Miner** (the core). Public reviews, forums, Q&A and search sequences → Jobs, success criteria, Problems, Aha moments, Tax Jobs, Consideration Sets and an *economic* Job graph (search frequency and CPC as edge weights). Every item carries verbatim receipts and author/platform counts.
2. **Consideration-Set Radar** (recurring subscription). The real competitive set *per Job* from public co-mentions and switching posts, plus competitor focus/sprawl from public changelogs. Buyers: product marketing and strategy teams, who already pay for competitive intelligence.
3. **Outside-In Chain Diagnostic + Next-Move Simulator** (high-value reports). For any company or category: which link of the chain to profit is weakest (market → segment+Job → value → unit economics → demand), then Monte-Carlo-ranked candidate moves with an **EVPI-ranked riskiest-assumption list** (EVPI = expected value of perfect information, defined below).
   - **Buyers:** investors and corporate development before a deal (they only *have* outside-in data), consultants who need "every step justified by numbers" (chat 1602), and founders at the idea stage with no customers yet (chat 181, 934, 1581, 1604).

Licence: build it all from general concepts, with no canon text at runtime (SOP v2 Module B). Alternatively, test the English-market licence route (N-L below).

---

## 2. Chat evidence relevant to desk-only and simulation-only work

| Signal | Voices | IDs | Why it fits the constraint |
|---|---|---|---|
| People with **no customers yet** who want to pick Jobs/segments or create a product | 4 | 181 (idea stage), 934 ("no product, want to create one"), 1581 (only materials; "how to reach 300M?"), 1604 (product built, no research done) | They *can't* interview their own customers yet. Desk + simulation is their only starting point |
| "Analyse the market and justify each step **with numbers**" | 1 | 1602 | Explicit demand for analytics-backed strategy |
| Strategy needed fast (deadline) | 3 | 1600, 1384, 1602 | Desk + simulation is the fast route; interviews take weeks |
| "Found Jobs in the graph that competitors ignore" | 1 | 1093 | Opportunity finding from graph structure |
| Want to model/draw graphs; graph maths (PageRank, optimal subgraph, P × result − cost) | 3 | 1105/1106, 1111, 1113 (+ owner 1100, 1114) | Graph computation is native to simulation |
| Trained interviewing with a simulated Claude respondent | 1 | 1214 | Simulation is already in use as practice |
| Strategies modelled over segment maps + Job graphs, ranked by ROI; risks as a factor | owner | 1118, 1310, 1373 | The core of the simulator |
| Consideration Set / switching conditions | owner | 315, 691 | The Radar's theory |

---

## 3. The ideas — each tested as a hypothesis

Each idea gets: NMT pillar → data it runs on (desk/sim only) → Job → critique → improved version → riskiest assumption → cheapest test that uses no interviews and no customer data → verdict.

### D1. Desk Job-Graph Miner ★ core

- **Pillars:** Job structure (8 elements), Job graph, types (Tax, Fake, Viral), value (Problem / Aha), segmentation by Job + criteria.
- **Data:**
  - App Store / Google Play reviews (official feeds and APIs)
  - Reddit (official API under its terms)
  - Hacker News (Algolia API)
  - Stack Exchange (API, CC BY-SA)
  - GitHub issues (API)
  - YouTube titles and comments (Data API)
  - Trustpilot, G2 and Capterra **only where licensed or terms allow**
  - Search data via a licensed SEO API (DataForSEO / Semrush): volumes, CPC, autocomplete, "people also ask", related queries
  - Public "alternatives to" pages
- **Output:**
  - Jobs with all 8 elements where evidence exists (`Unknown` otherwise)
  - Problems / Aha moments per Solution
  - Tax-Job list
  - segment hypotheses (clusters of Jobs + criteria priority)
  - an **economic Job graph**: edge order from query sequences, weights = volume (frequency) and CPC (commercial value)
  - importance ranking (weighted PageRank)
  - route value `p × outcome − Σ costs` with *ranges*
- **Job it performs:** *I want a defensible first map of who does what Jobs in this category, and where current Solutions under-deliver, in order to choose where to compete before I have customers.* Chat 181, 915, 934, 1093, 1604.
- **Critique:**
  - **Biases:** reviews skew towards extremes, platform demographics and astroturfing; search ≠ purchase; CPC reflects advertiser competition. These need explicit corrections:
    - author de-duplication
    - bot/astroturf filters
    - **source-type diversity**: a claim needs ≥ 2 independent source *types*
    - review-extremity weighting
  - **Competition:** review analytics (Kimola, Revuze, Enterpret, Viable) mostly analyse *your own* feedback, or sentiment, not a Job graph. None output NMT-structured Jobs with receipts and search-economics weights.
- **Improved version:** the output is explicitly a *hypothesis map* with a confidence per node. It names the **3 nodes whose uncertainty matters most** (that list comes from D4's value-of-information calculation), so the user knows what to test first.
- **Riskiest assumption:** public traces contain enough Job-level detail (context, trigger, criteria) in a typical B2B or B2C category to cluster segments meaningfully. The risk is that they only contain feature complaints.
- **Cheapest test (desk only):** run the miner on 3 categories with very different public footprints:
  1. a consumer app category
  2. a developer tool
  3. an SMB SaaS category

  Measure the share of extracted Jobs with ≥ 4 of the 8 elements evidenced and ≥ 2 source types. **Kill line: < 30% in 2 of 3 categories** → reposition as "Problems & Consideration Sets" only.
- **Verdict:** **BUILD FIRST** (everything else depends on it).

### D2. Consideration-Set Radar ★ recurring revenue

- **Pillars:** Consideration Set, Consideration Activators, competitors defined by Jobs, behaviour change (switching), focus/subtraction (applied to competitors).
- **Data:**
  - co-mentions in recommendation threads and comparison queries
  - "moved from X to Y" posts (triggers, fears, reasons)
  - "X vs Y" search volumes over time
  - G2-style "compared with" data, where licensed
  - competitors' **public changelogs, release notes, job postings and pricing-page history** (Wayback Machine). These are classified by Job and segment → a **focus/sprawl score** and "which Jobs each rival is moving into"
- **Job:** *I want to know who my buyers actually compare us with for each Job, and what makes them switch, in order to position against the real alternative and see rivals' moves early.*
- **Critique:**
  - The buyer is product marketing / competitive-intelligence teams, a budget that already exists (Crayon, Klue: tens of thousands per year).
  - Incumbents track *named competitors and news*. They don't build the Job-based set, which includes non-obvious substitutes ("spreadsheet", "hire an agency", "do nothing").
  - Monitoring gives a natural subscription (weekly deltas), unlike one-off reports.
  - Risk: co-mention ≠ consideration. Mitigation: weight mentions found inside choice contexts ("should I use…", "switched from…") above casual mentions.
- **Riskiest assumption:** the Job-based set differs materially from the set a company tracks today, i.e. it surfaces ≥ 2 non-obvious substitutes that matter.
- **Cheapest test (desk only + market behaviour):**
  - Produce Radar snapshots for 5 public companies.
  - Compare them with the competitors each company names on its own comparison pages.
  - Publish 2 snapshots as free content and add a waitlist with a stated price.
  - **Kill line:** < 2 non-obvious substitutes in 3 of 5 snapshots, or < 1% waitlist conversion from the content traffic.
- **Verdict:** **BUILD SECOND** (first subscription product).

### D3. Outside-In Chain Diagnostic ★ high-value report

- **Pillars:** chain to profit (top-down diagnosis), "why isn't it selling" (12 mistakes), NMT as an investment lens (canon §12), local vs global optimum.
- **Data:** D1 + D2 outputs, plus:
  - **market in Job terms** (D5)
  - public pricing
  - CPC/SEO-derived acquisition-cost proxies
  - public traffic estimates
  - hiring velocity (job postings, via lawful sources only)
  - funding data
  - app-store rank history
- **Output:** for a named company or idea, each chain node is rated *strong / weak / unknown* with receipts:
  - market with money
  - segment + Job fit (does the messaging target a coherent Job graph?)
  - value gap vs the Consideration Set (Problems/Aha balance vs rivals)
  - unit-economics plausibility (price vs acquisition-cost proxy vs Job frequency)
  - demand creation (search share, community presence)
  - barriers

  It then names the **upstream-most weak node**. That's the diagnosis.
- **Job:**
  - *investor:* "decide whether to take the next meeting / where diligence should dig"
  - *consultant:* "walk in with an analytics-backed view" (chat 1602)
  - *founder with no customers:* "know which link of my idea is weakest before spending" (934, 1581)
- **Critique:**
  - Investors have the highest budget and a recurring trigger (deal flow).
  - Outside-in is all they have before a term sheet, so the constraint matches how they already work.
  - Competition: analysts + ChatGPT, CB Insights / Harmonic / Similarweb (data, not diagnosis), expert networks (interviews, so excluded by your constraint and expensive).
  - Credibility risk: "a JTBD framework says this startup's segment is weak" must be backed by receipts and numbers, never by method authority.
- **Riskiest assumption:** early-stage investors will pay for a structured outside-in diagnosis, rather than having an analyst do it with ChatGPT.
- **Cheapest test (desk + market behaviour):**
  - Backtest first: run the diagnostic on 10 companies **as of 2–3 years ago** (Wayback snapshots, archived reviews), with known outcomes since (shut down, raised, acquired).
  - If the weak-node diagnosis separates winners from failures better than chance, publish the backtest as content to investor communities. Offer 10 paid diagnostics through a payment link.
  - **Kill line:** backtest no better than chance → stop. < 3 paid of 10 → reposition to consultants.
- **Verdict:** **BUILD THIRD**, backtest first.

### D4. Next-Move Simulator (strategy Monte Carlo + EVPI-ranked RAT)

- **Pillars:** the algorithm Steps 5–8 / chat 1310 steps 5–7, strategy object (1373), unit economics, RAT, opportunity cost, local vs global optimum.
- **Data:** simulation over ranges taken from D1/D2/D5:
  - segment size
  - Job frequency
  - Job budget proxy
  - price
  - conversion and acquisition-cost ranges (public benchmarks + CPC)
  - churn ranges
  - competitive pressure

  No customer data.
- **What it does:**
  1. Generates candidate strategies as 6-part objects. They are created by applying value mechanics to the D1 graph: move up a level, kill a Job, take the Job off the customer, fix a chain break, lower a cost, remove a negative emotion.
  2. Simulates each strategy's profit distribution over the goal horizon (10k runs), plus opportunity cost against the best alternative.
  3. **Ranks risky assumptions by EVPI (expected value of perfect information).** EVPI asks how much better the decision would be if this one uncertainty were resolved. The assumption with the highest EVPI is, by definition, the riskiest *for this decision*. This replaces subjective `p_wrong × cost_if_wrong` scoring with something computed, which is a real methodological advance on the RAT ordering rule.
  4. Outputs a ranked list of the cheapest market-behaviour tests for the top-EVPI assumptions.
- **Critique:** garbage in, garbage out. The ranges must carry receipts (D1/D5), and the simulator must show how sensitive the ranking is. It is the core of the "AI CPO" category (chat 1118, 1228), built on maths instead of methodology text, so licence risk is low.
- **Riskiest assumption:** strategy rankings are stable enough under realistic input ranges to be decision-useful, i.e. not dominated by noise.
- **Cheapest test (simulation only):** for 3 desk-built cases, check whether the top strategy remains top in ≥ 70% of runs with inputs perturbed ±30%. If not, the product shows "undecidable without resolving X" (the EVPI output), which is still useful.
- **Verdict:** **BUILD with D3** (D3 is its sellable wrapper).

### D5. Market-in-Job-Terms Sizer

- **Pillar:** "market with money" defined in Job terms (chain node 1).
- **Data:**
  - official statistics (CSO, Eurostat, ONS, Census)
  - public company filings and pricing pages
  - industry associations
  - search volumes

  Formulas are auditable, with units, periods, ranges and geography separation. The double-count guard is code (`evidence-gates`).
- **Critique:** top-down market sizing is a commodity (ChatGPT does it, badly). The value is **auditability** plus sizing "the money spent to get Job X done" across all Solutions, including non-consumption and DIY.
- **Verdict:** **FEATURE** of D3/D4. Not standalone.

### D6. Calibrated Synthetic Panel (persona simulation, with receipts)

- **Pillars:** Consideration Activators / five switching conditions (chat 315), communication, behaviour change.
- **Data:** LLM personas conditioned *only* on D1 receipts (real public quotes per segment). They react to positioning, landing copy and offers. A cross-vendor council (Convr pattern) records disagreement as uncertainty.
- **Critique:**
  - Crowded and controversial: Synthetic Users, Evidenza, Aaru, Electric Twin.
  - Known failure modes: sycophancy, low variance, inflated willingness to pay.
  - **Allowed only with calibration:** take public A/B outcomes, or known market outcomes of competing positionings (archived landing pages + later traction), and measure whether the panel *ranks* them correctly.
  - Outputs are always `SIMULATED`, relative and never priced.
- **Riskiest assumption:** a receipt-grounded panel ranks messaging variants better than chance on historical public cases.
- **Cheapest test (simulation only):** a backtest on 20 historical pairs of positionings with known relative outcomes. **Kill line: ≤ 60% correct ordering.**
- **Verdict:** **FEATURE**, gated by a passed backtest. Never a headline claim.

### D7. Opportunity Finder (Tax Jobs and chain breaks → "kill this Job" product ideas)

- **Pillars:** value-creation mechanics (kill a Job, fix a chain break, move up a level), Tax Jobs, Fake-Job filter.
- **Data:** D1 output across many categories:
  - recurring workaround threads
  - unanswered "how do I" questions with high search volume and CPC
  - Jobs that every incumbent under-delivers (chat 1093)

  A **Fake-Job filter** keeps only Jobs with evidence of *past spending*: paid tools mentioned, hired help, time spent.
- **Job:** *I want an evidence-backed product idea in a Job people already pay to get done badly.* Chat 934, 943, 181.
- **Critique:** builders without products have low willingness to pay. Better used as a **content/lead engine** ("10 under-served Jobs in X, with receipts") feeding D2/D3, and as your own idea pipeline.
- **Verdict:** **CONTENT ENGINE + internal use.**

### D8. Simulated AJTBD Interview Trainer (respondent personas from public receipts)

- **Source:** 1209, 1214 (already trains with a simulated Claude), 1224.
- **Critique:** fits the constraint (pure simulation) but serves a small, captive learner market that the method owner will serve (1224). Low frequency (3–10 interviews to learn).
- **Verdict:** **PARK.** Only as a free demo of D6's grounding.

### D9. Desk Strategy Sprint (72-hour service)

- **Source:** 1600, 1602, 1384, 1597.
- **What it does:** D1 → D5 → D4 → D3 run as a concierge service, delivering the 6-part strategy object with receipts, simulation results and the EVPI test plan in 72 hours. It replaces last version's interview-based sprint.
- **Critique:** best trigger (deadline), fastest revenue, and it funds building the tools. The licence matters: write it from general concepts (Module B).
- **Verdict:** **RUN as the first revenue route** while D1–D4 are built.

### N-L. English-market licence/partnership with the method owner

- **Rationale:** the method owner's commercial machine is Russian-language (the whole chat). The repo and its 444 stars are English. A licence removes the NonCommercial barrier and would allow canon-faithful outputs.
- **Test:** one written proposal. **Kill line: no reply in 30 days.**
- **Verdict:** **TEST in parallel.** No build depends on it.

---

## 4. Dropped because they violate the constraint

| Previous idea | Why dropped | What replaced it |
|---|---|---|
| ABCDX + Focus Analyser | Needs existing customers' billing/satisfaction data | D2 focus/sprawl score on *competitors* from public changelogs; D4 simulation |
| Research Evidence QA (interviews) | Needs interviews | The same receipt gates applied to public reviews and forums (D1) |
| Off-strategy ticket detector | Needs internal tickets | D2 competitor focus score |
| Interview-based 7-day sprint | Needs interviews | D9 desk sprint |
| Respondent recruiting planner | Exists to enable interviews | — |

---

## 5. Ranking

Scores run 1–5, where 5 is best.

| # | Idea | Data availability (public, lawful) | Value gap | Budget / trigger | Competition (5 = weak) | Licence safety | Simulation-honesty risk (5 = low) | Asset fit | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **D1** | Desk Job-Graph Miner | 4 | 4 | 2 alone | 4 | 5 | 5 | 5 | **BUILD 1st (core)** |
| **D2** | Consideration-Set Radar | 4 | 4 | 4 (CI budgets, recurring) | 3 | 5 | 5 | 4 | **BUILD 2nd** |
| **D3+D4** | Outside-In Diagnostic + Next-Move Simulator | 3 | 5 | 5 (deals, deadlines) | 4 | 5 | 3 | 4 | **BUILD 3rd, backtest first** |
| **D9** | Desk Strategy Sprint (service) | 4 | 4 | 5 | 3 | 3 | 4 | 5 | **RUN now (revenue)** |
| D5 | Market-in-Job-terms sizer | 4 | 3 | 2 | 2 | 5 | 5 | 4 | FEATURE |
| D6 | Calibrated synthetic panel | 4 | 3 | 3 | 2 | 5 | **1** until backtested | 4 | FEATURE (gated) |
| D7 | Opportunity Finder | 4 | 3 | 1 | 3 | 5 | 5 | 4 | CONTENT ENGINE |
| N-L | Licence/partnership | — | 5 | — | — | 5 if yes | — | — | TEST (1 day) |
| D8 | Simulated interview trainer | 5 | 2 | 1 | 2 | 4 | 3 | 3 | PARK |

**The single riskiest assumption right now (D1):** *public traces contain enough Job-level detail to build segment-grade Job graphs.* Everything else is built on it, and it costs only a desk run on 3 categories to test.

---

## 6. Methodology inputs from the chat (used in SOP v2)

| ID | Insight | Source |
|---|---|---|
| M1 | 7-step business-task algorithm (goal → artefacts → mechanics → data → strategies → ROI ranking → RAT) | 1310 |
| M2 | 6-part strategy object (+ long form) | 1373, 1138 |
| M3 | Graph on graph: customer → intermediary → our business → product | 1227, 1096 |
| M4 | Value = P(result) × result − costs | 1100–1101 |
| M5 | Strategies modelled over segment maps + Job graphs, ranked by ROI factors | 1118, 1130 |
| M6 | Five switching conditions | 315 |
| M7 | B2B owner-operators: business + personal Jobs | 1085–1087 |
| M8 | Marketplaces = Job chains | 1092 |
| M9 | Goal-selection algorithm exists, not public | 1310 |
| M10 | First change must pay its operator immediately | 718 |
| M11 | Clean-context auditor, planner/executor split, human-led compaction | 285–304 |
| M12 | Public skills = incomplete methodology | 1217 |

## 7. Limits

- No willingness-to-pay evidence exists for any idea. Every verdict means "worth testing next".
- Desk + simulation can rank hypotheses and design tests; only market behaviour can confirm demand.
- Platform terms change. Re-check every source's terms before each production use.
