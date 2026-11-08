# Implementation map

Where each part of the spec lives in code, and where the code deliberately differs from the spec.
Precedence when documents disagree: master prompt > ARCHITECTURE > PROTOCOL > PRODUCT.

## Spec → code

| Spec | Code |
|---|---|
| ARCHITECTURE §4 data model, PROTOCOL schemas (Synthetic, Calibration, Forecast, MarketTouch, RunManifest) | `src/nmt_engine/schema.py` |
| Append-only store (`store/<type>.jsonl`, highest `rev` per id is current, `supersedes`, `retracted`) | `src/nmt_engine/store.py` |
| Units and periods (pint), formula evaluation without literal multipliers | `src/nmt_engine/units.py` |
| Salted author hashing | `src/nmt_engine/util.py::author_hash` |
| Licence n-gram scan | `src/nmt_engine/licence.py`, `tests/test_licence_src.py` |
| §6 gates 1–14 | `src/nmt_engine/gates/gNN_*.py`, registry in `gates/base.py`, runner/demote in `gates/runner.py` |
| CLI `nmt gates check / demote` | `src/nmt_engine/cli.py` |
| Fixtures (clean + one seeded defect per gate) | `tests/fixtures/make_fixtures.py` → `tests/fixtures/runs/` |
| PROTOCOL §2 log form (μ, σ from median + 80% interval) | `src/nmt_engine/synth/logform.py` |
| PROTOCOL §3.3 per-family calibration (bias, split-conformal q80, LOO coverage, pass rule) | `src/nmt_engine/synth/calibrate.py` |
| PROTOCOL §3.2 triangulation (same-family merge, 1/σ² weights, ρ inflation, pairwise z) | `src/nmt_engine/synth/triangulate.py` |
| PROTOCOL §2 grades S0–S4 | `src/nmt_engine/synth/grade.py`; end-to-end `synth/estimate.py::estimate` |
| PROTOCOL §2 mandatory citation label | `src/nmt_engine/synth/label.py::citation_label` |
| PROTOCOL §3.5 forecast registry + scoring (hit, log error, Brier) | `src/nmt_engine/synth/forecast.py` |
| Leakage guard (as-of T) | `src/nmt_engine/synth/leakage.py` |
| EVPI on method disagreement (go/no-go) | `src/nmt_engine/synth/evpi.py` |
| Collectors: shared plumbing (cache keyed by request + as-of date, per-host rate limit, retries, forbidden-host refusal, secret redaction, PII masking, Source + retrieval log) | `src/nmt_engine/collect/base.py` |
| Trace adapters (HN, Stack Exchange, App Store, GitHub, Reddit, YouTube, Wayback, public web; Google Play disabled) | `src/nmt_engine/collect/<adapter>.py`; access basis + terms URL in each module docstring |
| Official/stats, procurement, search, labour, dataset adapters | `collect/{eurostat,cso,ons,companies_house,sec_edgar,procurement,dataforseo,adzuna,datasets}.py` |
| `nmt collect` orchestration | `src/nmt_engine/collect/run.py`, `cli.py`; VCR cassettes `tests/cassettes/`, tests `tests/test_collect.py` |
| Known-truth worlds | `src/nmt_engine/synth/world.py`; histogram `scripts/coverage_histogram.py` → `docs/img/coverage_histogram.png` |

## Gate → defect → demote action

| # | Gate | Seeded defect (`broken_gNN`) | `nmt gates demote` action |
|---|---|---|---|
| 1 | quote exists | verbatim altered | claim → `HYPOTHESIS`, flagged |
| 2 | voices = distinct author_hash | declared voices > distinct authors | `voices` recomputed; `<2` → single signal |
| 3 | author-stated numbers | Calc input only from one author's post | Calc flagged |
| 4 | Calc recompute | monthly × annual | Calc flagged |
| 5 | geography separation | IE calc uses a UK-geography input | Calc flagged |
| 6 | double-count guard | overlapping segment shares in one geography | Segment flagged |
| 7 | source exists | source missing from retrieval log | source and its claims dropped |
| 8 | validation-language lint | "Customers want …" in report.md | flagged (fix the text) |
| 9 | manifest hash | frozen input edited after freeze | flagged (re-freeze) |
| 10 | licence overlap (outputs + `prompts/`) | 12-word overlap with forbidden corpus | flagged (rewrite) |
| 11 | source-type diversity | segment claim with one source type | single signal, removed from Segment/why_we_win/Job |
| 12 | astroturf | near-duplicate burst within 72 h | voices collapsed |
| 13 | simulation firewall | `why_we_win` cites an S2 synthetic estimate | flagged |
| 14 | access basis | source with disallowed `access_basis` | source and its claims dropped |

Demotion never edits a line: it appends a new revision (`rev + 1`) with a `flags` entry.

## Deliberate differences

- **Gate numbering 5/6.** ARCHITECTURE §6 lists 5 = double-count, 6 = geography. The master prompt
  lists 5 = geography, 6 = double-count. The code follows the master prompt.
- **`access_basis` values.** ARCHITECTURE §4 has `public|consented|licensed|own`; §6 gate 14 and the
  master prompt use `public_api_terms_ok | open_licence | licensed | public_page_terms_ok`. The code uses
  the latter. `Source.access_basis` is a free string so gate 14 (not schema validation) reports bad values.
- **Gate 7 scope.** "Input folder (docs)" sources are supported through the retrieval log entry with
  `kind="doc"`; every source must be logged either way.
- **Gate 8 qualification.** A sentence passes if it carries "synthetic, grade S3"/"S4" or names a stored
  `MarketTouch` id.
- **Gate 10 scope.** Applies unless `run_manifest.method_module == "A"`. The repo-wide check on `src/`
  runs as a test against `forbidden_corpus/` (git-ignored; set `NMT_FORBIDDEN_CORPUS` to move it).
- **Gate 13 persona-panel monotonicity** is not checked yet: persona panels arrive in PR 9 (calibrated
  synthetic panel), which adds that test.
- **Joint reference classes.** Each calibration case is estimated by every family (`JointCase`), so
  `joint_calibration` fits every family on the same truths and records a `JointCalibration`. From it:
  ρ = max(`DEFAULT_RHO`, clip(mean pairwise correlation of calibrated log errors, 0, 0.95)), and the
  combined half-width is max(analytic, LOO conformal q80 of the combined estimate), where the LOO
  re-fits each family's bias/q80 and ρ without the held-out case. The rank is the standard split-conformal
  ⌈(n+1)·0.8⌉-th *smallest* |log error|. `Synthetic` records `rho`, `combined_conformal_q80` and
  `joint_calibration_id`.
- **Failed calibrations never narrow the combined interval.** A family whose calibration did not pass
  (n < 20 or LOO coverage outside 0.75–0.90) is listed in `Synthetic.methods` with `in_combined=False`
  but left out of triangulation, ρ and the combined conformal width. If no family passed, all are pooled
  with ρ = 1 (combining earns no narrowing). Pooled families still get their fitted bias and q80.
- **S2 needs agreement two ways.** Pairwise z ≤ 1.645 (master prompt) *and* overlapping 80% intervals
  (PROTOCOL §2). Either failing sets `methods_disagree` and caps the grade at S1.
- **Same-family merge** takes the mean μ′ and mean σ′ of that family's calcs, so padding a family never
  narrows the interval beyond its single tightest calc.
- **Brier score.** For a binary forecast, (p − y)² with the given p. For an interval forecast,
  (0.8 − hit)², i.e. the nominal 80% coverage claim scored as a probability.
- **World error model and coverage test.** Family errors share a common market shock with correlation ρ
  (optionally multivariate Student-t), and stated intervals are `stated_sigma_ratio` × the true noise.
  The estimator never receives ρ. Test (a) is a misspecification matrix (`world.MATRIX_CELLS`: true
  ρ ∈ {0, 0.3, 0.6, 0.8} × stated ratio ∈ {0.4, 0.6, 1.0}, plus Student-t df = 3) and the fallback
  cells (`world.FALLBACK_CELLS`); each must reach 75–90% coverage over 200 worlds
  (`scripts/coverage_matrix.py` prints the table). The ρ floor makes the true-ρ = 0 cells
  conservative: with honest stated intervals that cell sits near the 90% ceiling.
- **Collector text is PII-masked.** E-mail addresses and phone numbers in public text are replaced by
  `[email]` / `[phone]` before the source text is stored (and before cassettes are saved), so quotes
  are verified against the masked text. Author ids are salted hashes; `nmt collect` refuses to run
  without `NMT_AUTHOR_SALT` so hashes are reproducible across runs.
  The phone pattern is deliberately broad: any run of 2–5 digit groups with ≥ 9 digits in total is
  masked, so the odd long numeric span (e.g. a spaced-out ID) can become `[phone]`. ISO dates,
  versions and money amounts are not touched. We accept slightly lower quote fidelity in exchange
  for missing fewer phone numbers; quotes are always verified against the masked text, so
  receipts stay valid.
- **Egress control.** Besides the platform denylist, `is_forbidden` refuses loopback, private
  (RFC 1918 / ULA), link-local (incl. `169.254.169.254` metadata), reserved literal IPs and
  `localhost` / `.local` / `.internal` names. It applies to every request, every redirect hop and
  streamed downloads (`Collector.download`). Hostnames are DNS-checked only with
  `NMT_EGRESS_RESOLVE=1` (off by default so tests stay offline); without it a public name that
  resolves to a private address is not caught.
- **Default-deny host list.** A collector only fetches hosts in `base.BUILTIN_HOSTS` (the APIs the
  built-in adapters call) or passed by the operator (`nmt collect --competitors`, each domain plus
  its `www.` form, via `Collector.extra_hosts`); anything else raises `HostNotAllowedError` before
  a request is sent. Redirects are followed only within the same host (plus the one documented
  hand-off `download.ons.gov.uk` → `static.ons.gov.uk`, `base.REDIRECT_PAIRS`); a redirect to any
  other host is refused, for `fetch` and `download`. Competitor pages whose apex redirects
  elsewhere are requested afresh on the `www.` twin (or the apex, for a `www.`
  domain), under that host's robots.txt. So a hostile DNS answer can only repoint one of
  these fixed names, never introduce a new one; the opt-in DNS check stays as defence in depth.
  Cassettes are saved without credential headers,
  `Set-Cookie`, secret query values or contact details, and a test checks this.
- **Google Play is disabled** (`collect/googleplay.py`): no terms-compliant review source exists.
- **Product Hunt** needs `PRODUCTHUNT_TOKEN` *and* `NMT_PRODUCTHUNT_TERMS_OK=1`, because its API terms
  restrict commercial use; the operator confirms the terms before enabling it.
- **ONS CSVs above 50 MB** (e.g. ASHE table 3, ~760 MB) are refused; use `ons.observations()` with
  dimension filters instead.
- **Keyed adapters** (Reddit, YouTube, GitHub discussions, DataForSEO, Companies House, Adzuna,
  Product Hunt) are skipped when their keys are missing and tested against mock transports built from
  the documented response shapes; keyless adapters replay real VCR recordings.
