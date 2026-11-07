"""Builds the gate fixtures: one clean run and one broken run per gate (exactly one seeded
defect each). All numbers and texts are invented test data, not real evidence.

    python tests/fixtures/make_fixtures.py   # rewrites tests/fixtures/runs/
"""

from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from nmt_engine.gates.g09_manifest import manifest_hash
from nmt_engine.schema import FrozenFile
from nmt_engine.util import sha256_file, sha256_text

HERE = Path(__file__).parent
RUNS = HERE / "runs"
CORPUS = HERE / "forbidden_corpus_sample"
T0 = "2026-10-01T12:00:00Z"

TEXTS = {
    "S-r1": "Great app. I switched from spreadsheets because filing VAT every two months took "
    "me a whole weekend. Now it takes an hour.",
    "S-r2": "Filing VAT returns used to eat my weekend; the bank feed import saves hours every "
    "month. Support is slow though.",
    "S-r5": "Decent value. I pay €30 a month for the standard tier and it covers my invoices.",
    "S-f1": "I'm trying to keep my books tidy so my accountant stops charging extra at year end. "
    "Any tips?",
    "S-q1": "How do I reconcile bank transactions before the VAT deadline without double "
    "entering everything? I run a two-person consultancy.",
    "S-p1": "ExampleBooks pricing. Starter plan €25 per month. Standard plan €40 per month. "
    "Prices exclude VAT.",
    "S-st1": "Fixture table. Enterprises in NACE M69, Ireland, 2022: 12000 enterprises.",
    "S-w1": "Fixture page. VAT returns for this fixture are filed 6 times per year.",
    "S-w2": "Fixture benchmark. Outsourced bookkeeping costs €50 per VAT return in this fixture.",
}


def _src(sid, kind, platform, author=None, geo="IE", published=None, basis="public_api_terms_ok"):
    return {
        "id": sid,
        "kind": kind,
        "platform": platform,
        "url": f"https://example.org/{platform}/{sid}",
        "author_hash": author,
        "retrieved_at": T0,
        "published_at": published,
        "as_of_date": "2026-10-01",
        "geography": geo,
        "access_basis": basis,
        "terms_url": f"https://example.org/{platform}/terms",
        "text_path": f"sources/{sid}.txt",
        "sha256": "",
    }


def _ref(sid, verbatim):
    return {"source_id": sid, "verbatim": verbatim, "locator": "p1"}


def clean() -> dict:
    sources = [
        _src("S-r1", "review", "app_store", "a_01", published="2026-03-01T09:00:00Z"),
        _src("S-r2", "review", "app_store", "a_02", published="2026-05-11T09:00:00Z"),
        _src("S-r5", "review", "app_store", "a_05", published="2026-06-02T09:00:00Z"),
        _src("S-f1", "forum", "reddit", "a_03", published="2026-04-07T09:00:00Z"),
        _src("S-q1", "qa", "stackexchange", "a_04", published="2026-02-20T09:00:00Z"),
        _src("S-p1", "pricing", "web", basis="public_page_terms_ok"),
        _src("S-st1", "stats", "cso", basis="open_licence"),
        _src("S-w1", "web", "revenue", basis="public_page_terms_ok"),
        _src("S-w2", "web", "benchmarks", basis="public_page_terms_ok"),
    ]
    pv = "PUBLIC_VOICE"
    claims = [
        {
            "id": "C1",
            "status": pv,
            "geography": "IE",
            "voices": 2,
            "text": "VAT filing deadlines cost small firms whole weekends",
            "source_types": ["review", "qa"],
            "single_signal": False,
            "source_refs": [
                _ref("S-r1", "filing VAT every two months took me a whole weekend"),
                _ref("S-q1", "before the VAT deadline"),
            ],
        },
        {
            "id": "C2",
            "status": pv,
            "geography": "IE",
            "voices": 2,
            "text": "Small firms want bank transactions reconciled without double entry",
            "source_types": ["qa", "review"],
            "single_signal": False,
            "source_refs": [
                _ref(
                    "S-q1",
                    "reconcile bank transactions before the VAT deadline without "
                    "double entering everything",
                ),
                _ref("S-r2", "the bank feed import saves hours every month"),
            ],
        },
        {
            "id": "C3",
            "status": pv,
            "geography": "IE",
            "voices": 1,
            "text": "Accountants charge extra when books are untidy at year end",
            "source_types": ["forum"],
            "single_signal": True,
            "source_refs": [_ref("S-f1", "my accountant stops charging extra at year end")],
        },
        {
            "id": "C4",
            "status": pv,
            "geography": "IE",
            "voices": 0,
            "text": "ExampleBooks Starter costs EUR 25 per month",
            "source_types": ["pricing"],
            "single_signal": True,
            "source_refs": [_ref("S-p1", "Starter plan €25 per month")],
        },
        {
            "id": "C5",
            "status": pv,
            "geography": "IE",
            "voices": 0,
            "text": "12000 enterprises in NACE M69 in Ireland (2022, fixture)",
            "source_types": ["stats"],
            "single_signal": True,
            "source_refs": [_ref("S-st1", "Enterprises in NACE M69, Ireland, 2022: 12000")],
        },
        {
            "id": "C6",
            "status": pv,
            "geography": "IE",
            "voices": 1,
            "text": "One reviewer pays EUR 30 per month",
            "source_types": ["review"],
            "single_signal": True,
            "source_refs": [_ref("S-r5", "I pay €30 a month")],
        },
        {
            "id": "C9",
            "status": pv,
            "geography": "IE",
            "voices": 0,
            "text": "VAT returns are filed 6 times per year (fixture)",
            "source_types": ["web"],
            "single_signal": True,
            "source_refs": [_ref("S-w1", "filed 6 times per year")],
        },
        {
            "id": "C10",
            "status": pv,
            "geography": "IE",
            "voices": 0,
            "text": "Outsourced bookkeeping costs EUR 50 per VAT return (fixture)",
            "source_types": ["web"],
            "single_signal": True,
            "source_refs": [_ref("S-w2", "€50 per VAT return")],
        },
        {
            "id": "C7",
            "status": "SYNTHETIC_ESTIMATE",
            "grade": "S3",
            "geography": "IE",
            "synthetic_id": "Y1",
            "voices": 0,
            "single_signal": True,
            "text": "Q4 WTP for IE micro firms: EUR 20-35 per month (synthetic S3, fixture)",
        },
        {
            "id": "C8",
            "status": "SIMULATED",
            "geography": "IE",
            "voices": 0,
            "single_signal": True,
            "text": "Brainstorm number: firms would pay EUR 60 (S0)",
        },
    ]
    calcs = [
        {
            "id": "K1",
            "quantity": "Q3",
            "method_family": "statistical",
            "formula": "firms * price",
            "geography": "IE",
            "unit": "EUR",
            "period": "month",
            "median": 300000.0,
            "interval_80": [250000.0, 350000.0],
            "inputs": [
                {"name": "firms", "value": 12000, "unit": "firm", "claim_id": "C5"},
                {
                    "name": "price",
                    "value": 25,
                    "unit": "EUR/firm",
                    "period": "month",
                    "claim_id": "C4",
                },
            ],
        },
        {
            "id": "K2",
            "quantity": "Q3",
            "method_family": "revealed_price",
            "formula": "firms * stated_price",
            "geography": "IE",
            "unit": "EUR",
            "period": "year",
            "median": 4320000.0,
            "inputs": [
                {"name": "firms", "value": 12000, "unit": "firm", "claim_id": "C5"},
                {
                    "name": "stated_price",
                    "value": 30,
                    "unit": "EUR/firm",
                    "period": "month",
                    "claim_id": "C6",
                    "corroborated_by": ["C4"],
                },
            ],
        },
        {
            "id": "K3",
            "quantity": "Q3",
            "method_family": "behavioural",
            "formula": "cost_per_return * returns",
            "geography": "IE",
            "unit": "EUR",
            "period": "year",
            "median": 300.0,
            "inputs": [
                {
                    "name": "cost_per_return",
                    "value": 50,
                    "unit": "EUR/occurrence",
                    "claim_id": "C10",
                },
                {
                    "name": "returns",
                    "value": 6,
                    "unit": "occurrence",
                    "period": "year",
                    "claim_id": "C9",
                },
            ],
        },
    ]
    jobs = [
        {
            "id": "J1",
            "statement": "I want to file VAT returns on time without losing a weekend",
            "level": "core",
            "trigger": "VAT deadline",
            "claim_ids": ["C1"],
        },
        {
            "id": "J2",
            "statement": "I want to reconcile bank transactions without double entry",
            "level": "small",
            "higher_job_id": "J1",
            "claim_ids": ["C2"],
        },
    ]
    edges = [{"id": "E1", "from_job": "J2", "to_job": "J1", "kind": "hierarchy"}]
    segments = [
        {
            "id": "SEG1",
            "name": "IE micro firms filing their own VAT",
            "core_job_ids": ["J1"],
            "claim_ids": ["C1", "C2"],
            "size": "Y1",
            "population": {"geography": "IE", "base_claim_id": "C5", "share": [0.4, 0.5]},
        },
        {
            "id": "SEG2",
            "name": "IE firms reconciling banks before handing to accountants",
            "core_job_ids": ["J2"],
            "claim_ids": ["C2"],
            "population": {"geography": "IE", "base_claim_id": "C5", "share": [0.3, 0.4]},
        },
    ]
    strategies = [
        {
            "id": "ST1",
            "goal": "First 50 paying IE micro firms",
            "horizon": "6 months",
            "compete_for": [{"segment_id": "SEG1", "job_ids": ["J1"]}],
            "not_compete_for": ["firms with an in-house bookkeeper"],
            "why_we_win": {
                "added_value": "Bank-feed reconciliation removes the VAT weekend",
                "activation": "VAT-deadline reminders",
                "claim_ids": ["C2", "C7"],
            },
        },
    ]
    synthetics = [
        {
            "id": "Y1",
            "quantity": "Q4",
            "segment_id": "SEG1",
            "geography": "IE",
            "grade": "S3",
            "unit": "EUR/month",
            "methods": [
                {"family": "statistical", "calc_id": "K1", "interval_80": [18, 34]},
                {"family": "supply", "calc_id": "K2", "interval_80": [21, 38]},
                {"family": "revealed_price", "calc_id": "K3", "interval_80": [20, 33]},
            ],
            "combined": {"median": 27, "interval_80": [20, 35]},
            "calibration_ids": ["CAL1"],
            "forecast_id": "F1",
        },
    ]
    calibrations = [
        {
            "id": "CAL1",
            "method_family": "revealed_price",
            "reference_class": "fixture class",
            "as_of_rule": "inputs dated <= T-3y",
            "n": 24,
            "coverage_80": 0.79,
            "bias_log_ratio": -0.05,
            "conformal_q80": 0.31,
            "passed": True,
        },
    ]
    forecasts = [
        {
            "id": "F1",
            "synthetic_id": "Y1",
            "resolution_rule": "median paid price at launch+90d",
            "resolve_by": "2027-06-30",
        },
    ]
    sim_runs = [
        {"id": "SIM1", "model": "montecarlo", "inputs": ["C7"], "n_runs": 10000, "seed": 7},
    ]
    report = (
        "# Fixture report\n\n"
        "Q4 WTP, segment SEG1: EUR 20-35/month (80% conformal interval), median EUR 27 · "
        "SYNTHETIC S3 · fixture data.\n\n"
        "Demand is not validated; this is a synthetic, grade S3 estimate only.\n\n"
        "Small firms describe losing weekends to VAT filing.\n"
    )
    return {
        "sources": sources,
        "texts": dict(TEXTS),
        "claims": claims,
        "calcs": calcs,
        "jobs": jobs,
        "edges": edges,
        "segments": segments,
        "strategies": strategies,
        "synthetics": synthetics,
        "calibrations": calibrations,
        "forecasts": forecasts,
        "sim_runs": sim_runs,
        "files": {"report.md": report, "inputs/brief.md": "Brief: IE SMB bookkeeping fixture.\n"},
        "frozen": ["inputs/brief.md"],
        "skip_log": set(),
        "post": [],
    }


def _by_id(items: list[dict], oid: str) -> dict:
    return next(x for x in items if x["id"] == oid)


# ---- one seeded defect per gate -------------------------------------------------------
def d01(fx):  # quote altered so it is not in the source text
    _by_id(fx["claims"], "C1")["source_refs"][0]["verbatim"] = (
        "filing VAT every two months took me an entire weekend"
    )


def d02(fx):  # voices overstated
    _by_id(fx["claims"], "C1")["voices"] = 3


def d03(fx):  # author-stated price used without corroboration
    _by_id(fx["calcs"], "K2")["inputs"][1]["corroborated_by"] = []


def d04(fx):  # monthly x annual period mismatch
    _by_id(fx["calcs"], "K3")["inputs"][0]["period"] = "month"


def d05(fx):  # UK input inside an IE calc
    _by_id(fx["claims"], "C10")["geography"] = "UK"


def d06(fx):  # segment shares exceed the base population
    _by_id(fx["segments"], "SEG2")["population"]["share"] = [0.6, 0.7]


def d07(fx):  # source missing from the retrieval log
    fx["skip_log"].add("S-f1")


def d08(fx):  # unqualified validation language
    fx["files"]["report.md"] += "\nCustomers want automated VAT filing.\n"


def d09(fx):  # frozen input changed after freeze
    fx["post"].append(lambda d: (d / "inputs/brief.md").write_text("Brief: edited later.\n"))


def d10(fx):  # report copies a 12-word run from the forbidden corpus sample
    fx["files"]["report.md"] += (
        "\nNote: the lighthouse keeper counted seventeen grey gulls on the northern rail "
        "before dawn.\n"
    )


def d11(fx):  # graph-node claim backed by one source type only
    c2 = _by_id(fx["claims"], "C2")
    c2["source_refs"] = [
        _ref("S-r1", "I switched from spreadsheets"),
        _ref("S-r2", "the bank feed import saves hours every month"),
    ]
    c2["source_types"] = ["review"]


def d12(fx):  # near-duplicate burst from two new authors counted as two voices
    burst = (
        "Best VAT tool ever, filing VAT returns is now effortless and quick, five stars, "
        "highly recommend to every small business owner in Ireland"
    )
    for sid, author, hour in (("S-r6", "a_06", "09"), ("S-r7", "a_07", "11")):
        fx["sources"].append(
            _src(sid, "review", "app_store", author, published=f"2026-07-01T{hour}:00:00Z")
        )
        fx["texts"][sid] = burst + ("!" if sid == "S-r7" else ".")
    c1 = _by_id(fx["claims"], "C1")
    c1["source_refs"] += [
        _ref("S-r6", "filing VAT returns is now effortless"),
        _ref("S-r7", "filing VAT returns is now effortless"),
    ]
    c1["voices"] = 4


def d13(fx):  # why_we_win cites a synthetic estimate below S3
    _by_id(fx["synthetics"], "Y1")["grade"] = "S2"
    _by_id(fx["claims"], "C7")["grade"] = "S2"


def d14(fx):  # forbidden access basis
    _by_id(fx["sources"], "S-f1")["access_basis"] = "scraped"


DEFECTS: dict[int, Callable[[dict], None]] = {
    1: d01,
    2: d02,
    3: d03,
    4: d04,
    5: d05,
    6: d06,
    7: d07,
    8: d08,
    9: d09,
    10: d10,
    11: d11,
    12: d12,
    13: d13,
    14: d14,
}


def _clean_none(obj):
    if isinstance(obj, dict):
        return {k: _clean_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_clean_none(v) for v in obj]
    return obj


def write(fx: dict, run_dir: Path, run_id: str) -> Path:
    if run_dir.exists():
        shutil.rmtree(run_dir)
    (run_dir / "sources").mkdir(parents=True)
    (run_dir / "store").mkdir()
    for sid, text in sorted(fx["texts"].items()):
        (run_dir / "sources" / f"{sid}.txt").write_text(text, "utf-8")
    for src in fx["sources"]:
        src["sha256"] = sha256_text(fx["texts"][src["id"]])
    for rel, text in fx["files"].items():
        (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / rel).write_text(text, "utf-8")
    log = [
        {
            "source_id": s["id"],
            "url": s["url"],
            "host": "example.org",
            "retrieved_at": T0,
            "adapter": "fixture",
            "status_code": 200,
            "sha256": s["sha256"],
        }
        for s in fx["sources"]
        if s["id"] not in fx["skip_log"]
    ]
    (run_dir / "retrieval_log.jsonl").write_text(
        "".join(json.dumps(x, sort_keys=True) + "\n" for x in log), "utf-8"
    )
    for key in (
        "sources",
        "claims",
        "calcs",
        "jobs",
        "edges",
        "segments",
        "strategies",
        "synthetics",
        "calibrations",
        "forecasts",
        "sim_runs",
    ):
        name = {
            "sources": "source",
            "claims": "claim",
            "calcs": "calc",
            "jobs": "job",
            "edges": "edge",
            "segments": "segment",
            "strategies": "strategy",
            "synthetics": "synthetic",
            "calibrations": "calibration",
            "forecasts": "forecast",
            "sim_runs": "sim_run",
        }[key]
        lines = [json.dumps(_clean_none(r), sort_keys=True, ensure_ascii=False) for r in fx[key]]
        (run_dir / "store" / f"{name}.jsonl").write_text("".join(x + "\n" for x in lines), "utf-8")
    frozen = [FrozenFile(path=p, sha256=sha256_file(run_dir / p)) for p in fx["frozen"]]
    manifest = {
        "run_id": run_id,
        "stage": "S4",
        "purpose": "third_party_output",
        "method_module": "B",
        "seed": 7,
        "frozen": [f.model_dump() for f in frozen],
        "manifest_sha256": manifest_hash(frozen),
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    for fn in fx["post"]:
        fn(run_dir)
    return run_dir


def build_all(root: Path = RUNS) -> dict[str, Path]:
    out = {"clean": write(clean(), root / "clean", "clean")}
    for num, fn in DEFECTS.items():
        fx = copy.deepcopy(clean())
        fn(fx)
        name = f"broken_g{num:02d}"
        out[name] = write(fx, root / name, name)
    return out


if __name__ == "__main__":
    for name, path in build_all().items():
        print(name, path)
