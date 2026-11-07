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
| 10 | licence overlap | 12-word overlap with forbidden corpus | flagged (rewrite) |
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
- **Gate 13 persona-panel monotonicity** is not checked yet: persona panels don't exist until the
  synth core (PR 2) adds them.
