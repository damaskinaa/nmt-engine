# nmt-engine

Outside-in product-strategy engine: given a category, company or idea, answer
"what is the most profitable next move, and what is the riskiest assumption behind it?"
from lawful public data and graded synthetic evidence, without customer interviews or
private customer data.

Spec: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/PROTOCOL.md`](docs/PROTOCOL.md),
[`docs/PRODUCT.md`](docs/PRODUCT.md). Spec-to-code map: [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).

## Setup

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in only what you need; tests need none
```

## Gates

```bash
nmt gates check tests/fixtures/runs/clean --forbidden-corpus tests/fixtures/forbidden_corpus_sample
nmt gates check tests/fixtures/runs/broken_g04 --forbidden-corpus tests/fixtures/forbidden_corpus_sample  # exit 1
nmt gates demote <run_dir>   # appends demoted/dropped/collapsed revisions to store/*.jsonl
```

`check` writes `gate_report.json` and `gate_report.md` (to the run dir, or `--out`).

## Synthetic evidence (`nmt_engine.synth`)

Calibrate each method family on a reference class, triangulate across families, grade S0–S4, and
generate the citation label (docs/PROTOCOL.md §2–§3). `synth/world.py` generates seeded markets with
known truth to test the maths:

```bash
python scripts/coverage_histogram.py   # 200 worlds -> docs/img/coverage_histogram.png
```

## Collect (`nmt collect`)

Lawful public traces and official data only (no LinkedIn, Glassdoor, logged-in pages, G2/Capterra/
Trustpilot scraping). Adapters missing an optional key (see `.env.example`) are skipped.

```bash
export NMT_AUTHOR_SALT=...   # required: author ids are stored only as salted hashes
nmt collect --category "invoicing" --competitors freshbooks.com,invoiceninja.com --geo IE --since 2023-01-01
```

This writes `sources/`, `store/source.jsonl`, `retrieval_log.jsonl`, an HTTP `cache/` and
`collect_summary.json` (per-adapter status and trace-source counts). Official-data adapters
(`eurostat`, `cso`, `ons`, `sec_edgar`, `companies_house`) return pandas frames with a `source_id`
column pointing at the stored raw payload.

## Run directory layout

```
<run_dir>/
  run_manifest.json        # frozen-input hashes + manifest hash (gate 9)
  retrieval_log.jsonl      # every fetch and stored source (gate 7)
  sources/<id>.txt         # stored source text, quotes are checked against this (gate 1)
  store/<type>.jsonl       # append-only typed objects; highest rev per id is current
  report.md / *.html       # rendered outputs (gates 8, 10)
```

## Tests

```bash
pytest --cov=nmt_engine.gates --cov=nmt_engine.synth   # never touches the network
ruff check . && ruff format --check .
python tests/fixtures/make_fixtures.py   # regenerate fixtures (a test checks they are in sync)
NMT_VCR_RECORD=1 pytest tests/test_collect.py   # re-record collector cassettes (delete old ones first)
```

`forbidden_corpus/` (git-ignored) holds text that must not appear in `src/`; a test fails on any
12-word overlap. Point `NMT_FORBIDDEN_CORPUS` elsewhere if you keep it outside the repo.
