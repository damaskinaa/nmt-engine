# NMT Next-Move Engine — Architecture & SOP v2

**Supersedes:** `Fresh_NMT_Research_in_Codex_SOP.md` (v1, NailIt folder) for every run started after 7 Nov 2026.
**Pinned methodology:** NMT Canon & Skills **v0.6.18**, upstream commit `f8e87d10255b48d381ebc7fa65172960eb6d483f` (13 Sep 2026), licence CC BY-NC-SA 4.0.
**Inputs to this revision:**
- the v1 SOP
- the upstream repo at that commit (installer, Codex market-research skill, CHANGELOG)
- the "Как делать продукт 2.0" chat analysis (`01_Chat_Hypothesis_Analysis.md`, methodology inputs M1–M12)
- your IP memo (28 Oct 2026)
- the Convr council/gate pattern

---

## 0. What v2 is

v1 was a **wrapper around one run of one skill** (`nmt-market-research`), focused on isolation and integrity. v2 keeps that wrapper. It adds:

1. **A full loop, not one report.** The run follows Zamesin's 7-step business-task algorithm (chat msg 1310) and the canon's 10-step algorithm. It goes from goal challenge through market artefacts, mechanics, data, strategies, ranking and de-risking. The NMT skills are called as *stages*, each in its own clean run.
2. **A persistent evidence and graph model.** Every run writes into one typed store:
   - claims, sources, Jobs and the four graph layers
   - segments, strategies, assumptions and experiments

   One report per stage stays the human-readable view.
3. **Code-enforced gates.** The model writes the words; code checks quotes, counts voices, does arithmetic, checks period compatibility and checks hashes.
4. **Cross-vendor clean-context review** and **human-led continuity** (chat M11).
5. **A licence boundary.** Own-portfolio runs may use the NMT skills and canon. Anything sold to third parties must run on the independently written method module.

v2 remains **not** a reimplementation of NMT. The installed skills and their Producer/Readability Contracts stay the authority *inside* each stage they cover. v2 governs the order of stages, the data passed between them, and the integrity rules.

---

## 1. Changes since v1 (defects found and fixed)

| # | v1 said / did | Problem (verified 7 Nov 2026) | v2 fix |
|---|---|---|---|
| D1 | `$nmt-upgrade` everywhere | Renamed to **`$nmt-update`** in 0.6.18. The installer deletes the old folder | Use `nmt-update` in all bans and checks |
| D2 | Installer `https://nextmovetheory.com/install.sh` | Upstream now installs and updates from GitHub: `raw.githubusercontent.com/zamesin/Next-Move-Theory-Canon-and-Skills/main/install.sh` | Use the pinned-commit route (§9.2) only |
| D3 | "Do not contact an update service" | Since 0.6.18 every skill runs an **end-of-run update check by default**, which sends the skill name and version. The run silently breaks the frozen-run rule | Write `update-check: off` to `.nmt-config` **and** export `NMT_NO_UPDATE_CHECK=1` |
| D4 | `NMT_VERSION="$(sed -n '1p' .nmt-version)"` | `.nmt-version` now starts with 8 comment lines; line 1 is `# Next Move Theory — installed version…`. v1 records a comment as the version | `grep -vE '^\s*#' .nmt-version \| head -1` |
| D5 | Hashes only `SKILL.md` + two contracts | Skills also load `references/glossary.md`. Canon content is not hashed (only its path) → a changed canon passes the gate | Hash a **full manifest** of `.agents/skills/` + `.claude/skills/` + `Next-Move-Theory-Canon/` (§9.3) |
| D6 | "Installer-provided rules block plus small invariant block is sufficient" | In 0.6.18 the injected block shrank to **5 lines** (pointers only). The invariant block now carries all of the integrity rules | Mandatory invariant block (§9.4) |
| D7 | No mention of repo-context reads | 0.6.18 skills **list context files they find and ask before opening**. In a dirty folder, a "yes" imports old context | Gate rule: answer *only* the permitted `inputs/` file; deny all others |
| D8 | Geography in overlay only | 0.6.18 asks **market + language up front** | Answer from the overlay values verbatim; mismatch = stop |
| D9 | Codex-only | You also run Claude Code; the installer installs both | Dual mapping (§9.1) |
| D10 | Market research only; value-prop/PRD/GTM banned in-run | Correct for one run, but no defined hand-off → each downstream run re-derived (or contaminated) context | Stage chain with typed hand-off manifests (§5) |
| D11 | No licence position | Canon/skills are **NonCommercial**. A paid third-party deliverable produced with them is unresolved (IP memo) | Licence gate L-1 (§8) |
| D12 | Claim discipline in prose ("evidence ledger") | Upstream 0.6.18 now defines it: frequency counts, claim status, single-signals list | Align ledger schema with 0.6.18 statuses; enforce in code (§6) |

---

## 2. Design principles

1. **Diagnosis before solutions; goal before diagnosis.** Stage 1 always challenges the goal (canon Step 1; chat M1-1, M9).
2. **Segment + Job is one entity.** Every downstream object references a `segment_id` and `job_id`s.
3. **AIs write words, math writes numbers.** Every number in a report comes from a formula over stored inputs with units and periods.
4. **Every claim has a receipt.** Each claim gets one status: `PUBLIC_VOICE` (verbatim from a public trace) / `DERIVED` / `HYPOTHESIS` / `SIMULATED` / `PROXY_METRIC` (search volume, CPC, traffic estimates), plus voices (distinct authors) and source types. A claim with one voice or one source type can't be promoted to the segment level.
5. **Desk research and simulation ≠ validation.** Only market behaviour counts as validation: ad click-through, waitlist sign-ups, prepayment, purchase. **This pipeline runs in Desk-and-Simulation Mode (§5a): no customer interviews, no existing customers' data.**
6. **Freeze, fingerprint, isolate** (from v1, kept in full).
7. **Subtract first.** At every stage, ask what can be removed: an assumption, a segment, a feature, a stage.
8. **Clean context beats iterative patching.** Fixes are made by re-planning and re-running the stage from clean, not by asking the same session to patch itself (chat M11).
9. **The first tool change must pay its operator immediately** (chat M10).
10. **The loop never ends.** Each experiment writes back into the store, and the next pass starts from Stage 1.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ L7  CONTINUITY      human-led handoff Q&A · session cap · run manifest   │
├──────────────────────────────────────────────────────────────────────────┤
│ L6  REVIEW          clean-context auditor (other vendor) · fusion · gates│
├──────────────────────────────────────────────────────────────────────────┤
│ L5  DE-RISKING      assumption ledger · RAT priority · experiments       │
├──────────────────────────────────────────────────────────────────────────┤
│ L4  STRATEGY        mechanics shortlist · strategy objects · ROI ranking │
├──────────────────────────────────────────────────────────────────────────┤
│ L3  GRAPH MODEL     customer Job graph · intermediary graph ·            │
│                     our business graph · product graph · segment map     │
├──────────────────────────────────────────────────────────────────────────┤
│ L2  EVIDENCE        sources · claims (status, voices, refs) · calcs      │
├──────────────────────────────────────────────────────────────────────────┤
│ L1  METHOD MODULE   [A] pinned NMT skills+canon (own-portfolio only)     │
│                     [B] independent method pack (anything sold)          │
├──────────────────────────────────────────────────────────────────────────┤
│ L0  ENVIRONMENT     fresh folder · trust · memory off · instruction chain│
│                     · provider census · freeze manifest   (= v1 SOP)     │
└──────────────────────────────────────────────────────────────────────────┘
```

### L0 Environment
v1 Parts 2–9 apply unchanged, except for the fixes in §1 and §9. One business idea = one fresh folder = one project.

### L1 Method module
This is a swappable interface. Stage prompts call `method.<stage>()`.
- **Module A** binds to the installed NMT skills. Use it for decisions about *your own* products (README own-company use).
- **Module B** is your own independently written instructions and schemas, built from general concepts, with no copied canon or skill text. It is required for any paid output to a third party (D2 Radar, D3 diagnostics, D9 sprints) unless a licence is obtained (N-L). Module B keeps an authorship log: date, author, and which sources were *not* consulted while writing.

### L2 Evidence store
- **Files, not a database, to start:** JSON Lines under `store/`, one file per object type, append-only with `supersedes` links. Git-tracked in a *separate* repo from any research folder. v1 forbids reading Git history inside a research run; the store is attached only at hand-off.
- **Write rule:** only stage outputs that passed the gates are written to the store. Raw model output goes to `runs/<run_id>/scratch/` and is never read by a later stage.

### L3 Graph model ("graph on graph", chat M3)
Four layers share one node schema:
1. **customer Job graph**, per segment
2. **intermediary business graph**, for marketplaces, channels and resellers (Job chains, M8)
3. **our business graph**: the Jobs *we* perform to extract value, i.e. our acquisition → activation → delivery → retention chain
4. **product graph**: the union of the customer graphs of all the segments we compete for

The cross-layer edges are the bets. They record which of our Jobs performs which customer Job.

### L4 Strategy
- A strategy is the 6-part object from M2, extended with the long form from 1138.
- Strategies are **generated** by applying shortlisted mechanics to the *real* graph, never the hypothetical one.
- They are **ranked** by modelled ROI on the goal's horizon, including opportunity cost (M5; canon Step 7 RICE + unit-economics gate).

### L5 De-risking
- One ledger of assumptions per strategy, positively stated and concrete: named segment, product, price, channel and geography.
- `priority = (p_wrong × cost_if_wrong) / cost_to_test` orders the work.
- Survival of the strategy = ∏(1 − p_wrong).

### L6 Review
- After each stage, an auditor of a **different vendor** runs in a **fresh context**. If Claude Code produced the stage, the auditor runs through `codex exec`, and vice versa.
- The auditor receives *only*: the stage output, the stage contract, the claim ledger slice, and the producer's own list of "questions I want checked". It never receives the producing session's transcript.
- Findings go to a **planner**, which rewrites the stage brief. A **fresh executor** re-runs the stage one-shot. Optionally, N executors run and the auditor fuses the results. The producer is never asked to "fix" its own output.

### L7 Continuity
- A run is capped at about 150k tokens of context, or at the end of a stage, whichever comes first.
- Handover is a **human-led Q&A** (§7.2), not auto-compaction.
- Each run writes a `run_manifest.json`.

---

## 4. Data model (minimum viable schemas)

```yaml
Source:      {id, kind: review|forum|qa|issue|search|filing|pricing|changelog|stats|news|web,
              platform, author_hash?, uri_or_path, retrieved_at, geography,
              sha256, access_basis: public|consented|licensed|own, provider_route}
Claim:       {id, text, status: PUBLIC_VOICE|DERIVED|HYPOTHESIS|SIMULATED|PROXY_METRIC|SYNTHETIC_ESTIMATE,
              grade?: S0..S4 (required when SYNTHETIC_ESTIMATE),
              voices: int (distinct authors), source_types: [review|forum|qa|issue|search|filing|
              pricing|changelog|stats|news], source_refs: [{source_id, locator, verbatim}],
              geography, stage, supersedes?, single_signal: bool}
              # single_signal = voices < 2 OR len(source_types) < 2
SimRun:      {id, model: montecarlo|persona_panel|agent, inputs: [Calc|Claim ids], n_runs, seed,
              calibration_id?, outputs, status: SIMULATED}
Calibration: {id, sim_kind, method_family, reference_class, as_of_rule,
              backtest_cases: [{case, as_of, known_outcome, predicted}], bias_log_ratio,
              conformal_q80, coverage_80, n, passed: bool}
Synthetic:   {id, quantity: Q1..Q9, segment_id, job_id, geography, grade: S0..S4,
              methods: [{family, calc_id, interval_80}], combined: {median, interval_80},
              calibration_ids, redteam_findings, forecast_id, citation_label}
Forecast:    {id, synthetic_id, resolution_rule, resolve_by, outcome?, score?: {hit, log_error, brier}}
Job:         {id, verb_phrase: "I want to …", level: big|core|small|micro (relative to product_id),
              context, trigger, negative_emotions, consideration_set: [solution_id],
              expected_outcome, success_criteria: [{criterion, measure, priority_rank}],
              positive_emotions, higher_job_id, type: regular|orientation|tax|fake|emotional|viral,
              frequency_per_year?, budget_per_job?, claim_ids: [..]}
Edge:        {from_job, to_job, kind: hierarchy|sequence|chain_handoff|performs,
              layer: customer|intermediary|business|product, freq_weight?, p_success?,
              costs: {money, time, effort, cognitive, negative_emotion, tax_jobs}}
Segment:     {id, core_job_ids, criteria_priority_order, causal_criteria: [..],
              qualification_questions: [..], size_estimate: Calc, abcdx_class?, claim_ids}
Calc:        {id, formula, inputs: [{name, value, unit, period, claim_id}], result, unit,
              period, range?: [lo, hi]}   # code recomputes; mismatched periods = gate fail
Mechanic:    {id, name, family: move_up|kill_job|take_off|fix_chain|lower_cost|remove_emotion|…,
              target_job_ids, rationale}
Strategy:    {id, goal_id, roi_horizon, compete_for: [segment_id+job_ids], not_compete_for,
              why_we_win: {added_value, activation}, resources, actions: [{function, action, due}],
              channels, awareness, business_model, price, positioning,
              assumption_ids, score: {roi: Calc, opportunity_cost: Calc, rice?}}
Assumption:  {id, strategy_id, statement_positive, segment, product, price, channel, geography,
              p_wrong, cost_if_wrong, cost_to_test, priority (computed), status: open|confirmed|killed,
              experiment_ids}
Experiment:  {id, assumption_id, design, kill_line, started, ended, result_behavioural, claim_ids}
RunManifest: {run_id, stage, method_module: A|B, nmt_version, manifest_sha256, inputs_sha256,
              provider_census, model_vendor, reviewer_vendor, gates: {name: pass|fail}, outputs}
```

**Path value (chat M4 + canon value):** for a route through a customer graph,
`V(route) = Π p_success(edges) × outcome_value − Σ costs(edges)`.
**Added value** = `V(our route) − V(best current solution in Consideration Set)`. The switching signal is that delta compared with the customer's *predicted* value, not its absolute size.
**Job importance (chat 1111):** a weighted PageRank over the sequence and hierarchy edges, weighted by frequency × budget. It is labelled `DERIVED` and used only to *order* research. It is never evidence.

---

## 5. Pipeline — stages, gates, hand-offs

Each stage runs in its own fresh run (L7) and is audited (L6). It hands off only through the store plus a manifest.

| Stage | Algorithm step (1310 / canon) | Method call (Module A) | Output to store | Gate to pass |
|---|---|---|---|---|
| S0 Setup | — | install, freeze | `RunManifest`, `.nmt-manifest` | Preparation Gate (v1 Part 9 + §9.5) |
| S1 Goal challenge | 1 / Step 1 | `$nmt-diagnose` (live product) or `$nmt-chat` (idea) | `Goal {statement, roi_horizon, 5-whys chain, rejected_goals}` | G1: goal stated as a business outcome with a horizon; at least one higher-level alternative considered |
| S2 Market artefacts (hypothetical) | 2 / Steps 2–3 | `$nmt-market-research` (Deep) | Segment map, hypothetical Job graphs, Consideration Sets, competitor-by-Job list, initial assumptions | G2: v1 final audit + §6 gates; every segment has causal criteria; verdict GO/NARROW/PIVOT recorded |
| S3 Mechanics shortlist | 3 / Step 4 | `$nmt-chat` with goal + S2 slice | `Mechanic[]` (5–12) with the data each needs | G3: each mechanic maps to a node of the chain to profit; the data needs list is concrete |
| S4 Desk evidence + simulation (§5a) | 4 / Step 5 | Public-trace mining → Job extraction with receipts; Monte Carlo; calibrated panel (optional) | Evidence-backed Job graph, revised segments, `SimRun`s, `Calibration`s | G4: every graph node ≥ 2 voices AND ≥ 2 source types (or marked thin); access basis recorded per source; no `SIMULATED` claim used as evidence |
| S5 Strategy generation | 5 / Step 6 | `$nmt-craft-value-proposition` per candidate | `Strategy[]` (3–7) | G5: each strategy fills all 6 core parts; "not compete for" is non-empty |
| S6 Ranking | 6 / Step 7 | code (`Calc`) + `$nmt-chat` critique | Scored strategies, chosen + runner-up, opportunity cost | G6: all numbers recompute; periods compatible; no double counting |
| S7 De-risk plan | 7 / Step 8 | EVPI from the S6 simulation (§5a.3) + RAT | `Assumption[]` ranked by EVPI, `Experiment[]` with kill lines | G7: top-EVPI assumption has a market-behaviour test (no interviews) with a numeric kill line |
| S8 GTM / message test | Step 9 | `$nmt-craft-go-to-market`; calibrated panel pre-screen (optional) | Landing/offer/ad variants as *experiment artefacts* | G8: copy promises only what S5 shows can be delivered; panel used only if its `Calibration.passed` |
| S9 Execute + loop | Step 10 | human | `Experiment.result_behavioural` (CTR, sign-ups, prepayments) | Loop: new claims → back to S1 |

## 5a. Desk-and-Simulation Mode (no interviews, no customer data)

### 5a.1 Desk trace → NMT element mapping

| NMT element | Public trace | Notes / bias control |
|---|---|---|
| Problem / Aha moment (value vs prediction) | Reviews ("expected… but", "surprised", "game changer") | Weight against review extremity; de-duplicate authors; filter suspected astroturf (burst timing, templated text) |
| Job context, trigger, negative emotions | Forum and Q&A posts ("I'm trying to… because…", "my boss needs…") | Keep the verbatim span; tag the platform's demographic skew |
| Consideration Set | "X vs Y" queries, "alternatives to X" SERPs, recommendation threads, "switched from" posts | Count only co-mentions inside choice contexts |
| Switching triggers, fears, barriers | "Moved from X to Y" posts, migration guides, cancellation complaints | Separate fears from objective barriers |
| Tax Jobs / Critical-Chain breaks | Workaround threads, unanswered "how do I" questions, GitHub issues, integration requests | Must show repeated occurrence across ≥ 2 platforms |
| Job order (graph edges) | Search query sequences: autocomplete, "people also ask", related searches | `DERIVED`; an edge is a hypothesis of sequence, not proof |
| Frequency × population | Search volume, community size | `PROXY_METRIC`, with seasonality shown |
| Job commercial value | CPC, pricing pages of Solutions in the Consideration Set, service-provider rates | CPC = seller-side lower bound, not customer budget |
| Market with money | Official statistics, filings, pricing × penetration estimates | Ranges; geography-separated; double-count guard |
| Competitor business graph / focus | Changelogs, release notes, job postings, pricing-page history (Wayback) | Classify each shipped item by Job + segment |

**Excluded sources:** LinkedIn and Glassdoor extraction, logged-in pages, and anything whose terms forbid automated access. Record `access_basis` per source.

### 5a.2 Simulation rules

1. **Monte Carlo** (unit economics, strategy ROI): every input is a range with a receipt (`Claim`/`Calc`). Use triangular or log-normal distributions, a fixed seed, ≥ 10k runs. Report distributions, not points.
2. **Persona panels / agent simulations** may only *rank* alternatives (messages, offers, positions). They are conditioned only on `PUBLIC_VOICE` receipts and are used only after a `Calibration` passes: a backtest on ≥ 20 historical cases with known relative outcomes, threshold > 60% correct ordering. Cross-vendor disagreement is reported as uncertainty.
3. **Synthetic WTP, market size and "validation" follow `04_Synthetic_Evidence_Protocol.md`.** They carry status `SYNTHETIC_ESTIMATE` with grade S0–S4. Only **S3+** (anchored, triangulated across ≥ 3 data families, backtested with conformal intervals, registered as forecasts) may be cited as evidence, always with the code-generated citation label. Raw `SIMULATED` outputs (S0) are never cited.

### 5a.3 Risk ranking by EVPI (replaces subjective RAT scoring when a simulation exists)

For decision *d* among strategies, with uncertain inputs θ:

`EVPI(θᵢ) = E_θᵢ[ max_d E[Profit | d, θᵢ] ] − max_d E[Profit | d]`

The assumption with the highest EVPI is the riskiest one *for this decision*. Rank tests by `EVPI / cost_to_test`. If EVPI ≈ 0 for every assumption, the decision is robust: act without testing. Computed by sampling: an inner loop over the remaining θ, an outer loop over θᵢ.

### 5a.4 Backtesting (how desk and simulation outputs earn trust)

Run the same pipeline **as of a past date**: Wayback snapshots, archived reviews, historical search data. Use companies or positionings whose outcomes are known now. Record hit rate in a `Calibration`. Publish nothing as "predictive" without a passed backtest.

**Stage independence rule:** a stage reads only the store objects named in its brief. It never reads another stage's report prose. Reports are for humans.

---

## 6. Deterministic gates (code, not prompts)

Implemented as `gates/*.py`. A stage cannot be written to the store until all its gates pass.

1. **Quote existence.** Every `PUBLIC_VOICE` claim's `verbatim` must appear in the captured source text (normalised whitespace, exact characters). Missing → status demoted to `HYPOTHESIS` and flagged.
2. **Voice count.** `voices` is recomputed from distinct `author_hash` values across sources. A claim with `voices < 2` cannot be referenced by a `Segment` or `Strategy.why_we_win`; it goes to the *Single signals* list.
3. **Author-stated numbers.** Any number inside a `PUBLIC_VOICE` claim (e.g. "we pay $400/month") is one person's statement. It can't feed a `Calc` without a second source of a different type (e.g. a pricing page).
4. **Calc recomputation.** Every `Calc.result` is recomputed. Units must chain, and periods must match (monthly × annual = fail). Every multiplier needs a `claim_id`.
5. **Double-count guard.** Segment population sizes within one geography must not overlap. A declared overlap must be subtracted.
6. **Geography separation.** No `Calc` mixes inputs from different geographies unless it is an explicit conversion step.
7. **Hallucinated source.** Every `uri_or_path` must exist in the run's retrieval log (web) or the input folder (docs). Not found → the claim is dropped. This is Convr's `pageUrl` rule.
8. **Validation-language lint.** Reject report sentences that pair the words *validated / proven / confirmed / customers want* with only desk or intent evidence.
9. **Freeze check.** The manifest hash at stage end = the manifest hash at the Preparation Gate.
10. **Licence check.** If `method_module = B`, the output and prompts are scanned for long n-gram overlap (≥ 12 tokens) with the canon/skills. A hit fails the gate.
11. **Source-type diversity.** Segment-level and Job-graph-node claims need ≥ 2 distinct `source_types` and ≥ 2 distinct authors. Otherwise → single signal.
12. **Author de-duplication and astroturf filter.** Collapse the same author across posts. Drop bursts of near-duplicate texts (MinHash similarity ≥ 0.8 within 72 h).
13. **Simulation firewall (graded).**
    - `SIMULATED` (S0) claims may not be referenced by `Segment`, `Strategy.why_we_win` or any `Calc` input.
    - `SYNTHETIC_ESTIMATE` claims may feed Monte Carlo inputs at ≥ S2, and may be referenced by `Segment` / `why_we_win` / go-no-go only at ≥ S3.
    - S3 requires: ≥ 3 method families with overlapping 80% intervals, a linked `Calibration` (n ≥ 20, as-of dated, conformal coverage ≥ 75%), and a registered `Forecast`.
    - Persona-panel outputs also need a passed monotonicity test.
14. **Access basis.** Every `Source` has `access_basis` ∈ {public_api_terms_ok, open_licence, licensed, public_page_terms_ok}. Missing or forbidden → the source and its claims are dropped.

---

## 7. Review and continuity protocols

### 7.1 Clean-context review (L6)

Producer, at the end of a stage, appends:

```text
SELF-REFLECTION FOR AUDITOR
1. The 5 claims I am least sure of, with why.
2. Decisions I made between alternatives, and the alternative I rejected.
3. Questions I want an independent auditor to answer.
Do not restate the work. Do not defend it.
```

Auditor (other vendor, fresh session, given only: stage output, stage contract, the ledger slice, the reflection):

```text
You are auditing one stage of a research pipeline. You have not seen how it was produced.
Check: (1) every gate in the contract, (2) each question in the reflection,
(3) any claim whose status is stronger than its evidence, (4) any upstream assumption the
output silently depends on. Return a findings list: {severity, claim_or_section, problem,
what evidence would resolve it}. Do not rewrite the output.
```

The planner turns findings into a revised stage brief, and a fresh executor re-runs the stage. Iterate at most 2 times. After that, mark the remaining findings as `Unknown` and move on. This matches Convr's `maxRegen: 2`.

### 7.2 Human-led handoff (L7)

Before ending any run:

```text
HANDOFF INTERVIEW — ask me, one at a time, until I say "done":
1. Which decisions in this run must the next run not re-open, and why?
2. Which user preferences/constraints were stated (wording, geography, price anchors, exclusions)?
3. Which files/objects are authoritative now, and which are superseded?
4. What did we try that failed, and why?
5. What is the single next action?
Then write handoff.md as Q/A pairs, citing store object ids. Record intent and reasons, not mechanics.
```

The next run reads `handoff.md` plus the named store objects, and nothing else from earlier runs.

---

## 8. Licence and commercial boundary

| Gate | Rule |
|---|---|
| **L-1 Purpose** | Each run declares `purpose: own_portfolio` or `purpose: third_party_output`. |
| **L-2 Module** | `own_portfolio` → Module A allowed. `third_party_output` → Module B only. No canon or skill text in prompts, retrieval or outputs. |
| **L-3 Branding** | Never use "Next Move Theory", "AJTBD" or Zamesin's name as product branding or implied endorsement. A factual "influenced by" note is allowed only after trademark checks (open item in the IP memo). |
| **L-4 Data** | Public sources need an access basis recorded in `Source.access_basis` (gate 14). Store author identifiers only as salted hashes. Quote short excerpts in deliverables, never bulk re-publish third-party text. |
| **L-5 Change** | A new upstream version, a new corpus, or a model fine-tune on any NMT material → re-run the IP check before use. |

This is an engineering control, not legal advice. It does not grant rights. Before you take money for Module-B output, get the review your IP memo recommends.

---

## 9. Runbook (corrected setup)

### 9.1 Codex ↔ Claude Code mapping

| Concern | Codex | Claude Code |
|---|---|---|
| Skills location | `.agents/skills/` (`$nmt-…`) | `.claude/skills/` (`/nmt-…`) |
| Rules file | `AGENTS.md` | `CLAUDE.md` |
| Project memory off | `.codex/config.toml` (v1 Part 4) + Desktop setting | Run from a fresh folder. Don't add memory files. Check `~/.claude/CLAUDE.md` and any `MEMORY.md` index that loads for this path; your global file has business-neutral rules only |
| Isolated home | `CODEX_HOME=…` | Separate OS user or a container (Claude Code reads `~/.claude`) |
| Fresh-context reviewer | `codex exec` in a new process | A new session, or a subagent given only the audit packet |

**Recommended pairing:** produce in Claude Code, audit with `codex exec`, or swap per stage. Never use the same vendor for both roles.

### 9.2 Install pinned 0.6.18

```bash
NMT_PROJECT="/Users/asia/Downloads/<Fresh_Idea_Folder>"
NMT_UPSTREAM_SHA="f8e87d10255b48d381ebc7fa65172960eb6d483f"
NMT_SOURCE="$(mktemp -d /private/tmp/nmt-source.XXXXXX)"

mkdir -p "$NMT_PROJECT/inputs"
git clone --filter=blob:none --no-checkout \
  https://github.com/zamesin/Next-Move-Theory-Canon-and-Skills.git "$NMT_SOURCE"
git -C "$NMT_SOURCE" fetch --depth 1 origin "$NMT_UPSTREAM_SHA"
git -C "$NMT_SOURCE" checkout --detach "$NMT_UPSTREAM_SHA"
test "$(git -C "$NMT_SOURCE" rev-parse HEAD)" = "$NMT_UPSTREAM_SHA"
sed -n '1,240p' "$NMT_SOURCE/install.sh"     # read it before running it
bash "$NMT_SOURCE/install.sh" --target "$NMT_PROJECT" --keep-clone

# D3: disable the end-of-run update check (frozen run)
printf 'update-check: off\n' >> "$NMT_PROJECT/.nmt-config"
```

Also launch every research session with `NMT_NO_UPDATE_CHECK=1` in the environment (belt and braces).

### 9.3 Fingerprint (D4, D5)

```bash
cd "$NMT_PROJECT"
NMT_VERSION="$(grep -vE '^[[:space:]]*#' .nmt-version | grep -m1 .)"
find .agents/skills .claude/skills Next-Move-Theory-Canon -type f -print0 \
  | sort -z | xargs -0 shasum -a 256 > .nmt-manifest
{
  printf 'upstream_commit=%s\n' "$NMT_UPSTREAM_SHA"
  printf 'nmt_version=%s\n' "$NMT_VERSION"
  printf 'manifest_sha256=%s\n' "$(shasum -a 256 .nmt-manifest | awk '{print $1}')"
  printf 'canon_realpath=%s\n' "$(cd Next-Move-Theory-Canon && pwd -P)"
  printf 'update_check=%s\n' "$(grep -q '^update-check: off' .nmt-config && echo off || echo ON-FAIL)"
} > .nmt-provenance
cat .nmt-provenance        # nmt_version must read 0.6.18; update_check must read off
```

Re-verify at every gate with `shasum -a 256 -c .nmt-manifest --quiet`. Any output = fail.

### 9.4 Invariant block

Append below the installer's markers in `AGENTS.md` and `CLAUDE.md`, keeping it short:

```text
## Research invariants (this folder)
- NMT repo/site = methodology reference, never business evidence. Business input = inputs/<FILE> only.
- NMT is frozen at the version in .nmt-provenance. Never run $nmt-update / /nmt-update or the installer.
- If a skill lists context files and asks to open them: allow inputs/<FILE> only; deny all others.
- Memories off. No previous runs, folders, chats, Git history or connectors.
- Every claim carries status + voice count; single signals never become segment conclusions.
- Desk research is not validation. Numbers come from shown formulas.
- purpose = <own_portfolio | third_party_output>; third_party_output forbids NMT text at runtime.
```

### 9.5 Preparation Gate additions (append to v1 Part 9 prompt)

```text
17. Read .nmt-provenance. Confirm nmt_version = 0.6.18 and update_check = off.
    Confirm .nmt-config contains "update-check: off" and report whether NMT_NO_UPDATE_CHECK is set.
18. Run: shasum -a 256 -c .nmt-manifest --quiet. Any output = FAIL.
19. Confirm the run's declared purpose and method module (A/B) per section 8.
20. Confirm the producer vendor and the planned auditor vendor differ.
```

### 9.6 Overlay additions (append to v1 Part 10 overlay)

```text
STAGE AND STORE
This run is stage <S#> of the v2 pipeline. Read only these store objects: <ids>.
Write outputs as the stage's schema objects plus the one human report the skill requires.
Mode: Desk-and-Simulation (no interviews, no customer data). Claim statuses:
PUBLIC_VOICE | DERIVED | HYPOTHESIS | SIMULATED | PROXY_METRIC, each with
voices and source refs. When the skill asks market and language, answer exactly:
<LAUNCH GEOGRAPHY> / <LANGUAGE>. At the end, produce the SELF-REFLECTION FOR AUDITOR block.
Do not run any update check.
```

### 9.7 New stage prompt — S1 Goal Challenge

```text
GOAL CHALLENGE (stage S1). Do not research the market yet.
Given the stated goal "<GOAL>", climb 3–5 levels with "why does this matter / what outcome is it for".
At each level, propose one more effective way to reach the higher outcome than the one handed down.
Name the ROI horizon. Distinguish local-optimum and global-optimum options and say which this is.
Output: Goal object, the why-chain, rejected goals with one-line reasons, and the first question
whose answer would most change the goal. Stop.
```

### 9.8 New stage prompt — S6 Ranking

```text
RANKING (stage S6). For each Strategy, build Calc objects for: people in segment (geography-specific),
Job budget per period, frequency per period, expected conversion, CAC, margin per unit, ROI on the
goal horizon, and opportunity cost versus the runner-up. Every input is a range citing claim_ids
(public benchmarks, pricing pages, CPC, official statistics); author-stated numbers cannot be sole
inputs. Run a seeded Monte Carlo (≥ 10k runs) per strategy, report profit distributions and the
probability each strategy is best, then compute EVPI per uncertain input (§5a.3). Do not choose by
prose; the ordering must follow from the computed values, and any override must be written as an
explicit judgment with reason.
```

---

## 10. Acceptance checklist — v2 additions

All v1 Part 15 rows still apply, plus:

| Check | Owner |
|---|---|
| `nmt_version = 0.6.18`, `update_check = off`, manifest verifies at start and end | Code |
| Purpose and method module declared; licence gate L-1…L-5 passed | Code + you |
| Stage read only the store objects in its brief | Run manifest |
| All §6 gates 1–14 passed (quote, voices, author numbers, calcs, double count, geography, sources, lint, freeze, licence, source-type diversity, astroturf, simulation firewall, access basis) | Code |
| Every persona-panel result links to a passed `Calibration`; Monte Carlo runs record seed and n | Code |
| Auditor vendor ≠ producer vendor; auditor had no transcript | Run manifest |
| At most 2 re-runs; remaining findings marked `Unknown` | Run manifest |
| `handoff.md` written via the human Q&A | You |
| Store written only from gated outputs | Code |

---

## 11. First application — run the pipeline on the NMT tool idea itself

Eat your own cooking. The first full pass of this pipeline chooses which NMT tool to build (file 01).

| Stage | Concrete run |
|---|---|
| S1 | Stated goal: "launch an NMT product". Challenge it upward: is the real goal revenue, a portfolio engine for your own products, or a licensed position in the English market? Pick a horizon (e.g. first paid customer within 8 weeks) |
| S2 | `own_portfolio`, Module A. Input: a one-page description of the **Outside-In Next-Move Engine** (D1 + D2 + D3/D4), *not* this chat analysis (isolation: independent discovery before founder examples). Launch geography Ireland/UK, expansion EU English-speaking |
| S3 | Candidate mechanics: take the research Job off the customer (D1/D9), lower time cost (desk in 72 h vs interview cycles of weeks), remove the negative emotion "my strategy isn't backed by numbers" (D3/D4), move up a level (next move, not just a report) |
| S4 | Desk only (§5a): mine public traces for the Jobs of the candidate buyers (product marketing / competitive-intelligence teams, early-stage investors, strategy consultants). Sources: reviews of Crayon/Klue/CB Insights/Similarweb-type tools, PMM and VC community threads, job postings for CI analysts, search volume and CPC for "competitor analysis", "market map", "due diligence template" |
| S5–S6 | Strategy objects for D2-first (Radar subscription), D3-first (diagnostic reports), D9-first (sprint service). Monte Carlo ROI on the horizon + opportunity cost |
| S7 | EVPI ranking. Expected top assumptions: "public traces carry Job-level detail" (D1 desk test) and "investors pay for outside-in diagnostics" (D3 backtest + payment-link test). Parallel: the licence proposal (N-L), kill line "no answer in 30 days" |
| Delivery to buyers | **Module B** unless N-L yields a licence |

---

## 12. Open items

- **M9** (Zamesin's goal-selection algorithm, 19 Sep) isn't public. S1 uses the canon's Step 1 until you have a legitimate source.
- The expert claims in M11 (session length, vendor comparisons, cited arXiv paper) are untested. Measure audit-finding rates per vendor pairing over your first 5 stages before relying on them.
- Trademark/patent searches from the IP memo are still incomplete. L-3 stays strict until they're done.
- The store format (JSONL) should move to a graph DB only when queries need it. Expect that once there are more than 3 products or more than 500 Jobs.
