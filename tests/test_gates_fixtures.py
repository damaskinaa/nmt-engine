import filecmp
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nmt_engine.cli import app
from nmt_engine.gates import REGISTRY, GateConfig, demote, run_gates
from tests.fixtures.make_fixtures import CORPUS, DEFECTS, RUNS, build_all

CFG = GateConfig(forbidden_corpus=CORPUS)


def test_fourteen_gates_registered():
    assert sorted(REGISTRY) == list(range(1, 15))
    assert sorted(DEFECTS) == list(range(1, 15))


def test_clean_run_passes():
    report = run_gates(RUNS / "clean", CFG)
    assert report.passed, report.to_markdown()


@pytest.mark.parametrize("num", sorted(DEFECTS))
def test_each_gate_catches_exactly_its_defect(num):
    report = run_gates(RUNS / f"broken_g{num:02d}", CFG)
    assert report.failed_gates() == [num], report.to_markdown()


def test_committed_fixtures_match_builder(tmp_path):
    build_all(tmp_path)
    for name in ["clean"] + [f"broken_g{n:02d}" for n in DEFECTS]:
        cmp = filecmp.dircmp(RUNS / name, tmp_path / name)
        stack = [cmp]
        while stack:
            c = stack.pop()
            assert not (c.diff_files or c.left_only or c.right_only), (name, c.diff_files)
            stack.extend(c.subdirs.values())


def test_cli_check_exit_codes_and_reports(tmp_path):
    runner = CliRunner()
    ok = runner.invoke(
        app,
        [
            "gates",
            "check",
            str(RUNS / "clean"),
            "--forbidden-corpus",
            str(CORPUS),
            "--out",
            str(tmp_path / "ok"),
        ],
    )
    assert ok.exit_code == 0, ok.output
    data = json.loads((tmp_path / "ok" / "gate_report.json").read_text())
    assert data["passed"] is True and len(data["gates"]) == 14
    assert (tmp_path / "ok" / "gate_report.md").read_text().startswith("# Gate report")
    bad = runner.invoke(
        app,
        [
            "gates",
            "check",
            str(RUNS / "broken_g04"),
            "--forbidden-corpus",
            str(CORPUS),
            "--out",
            str(tmp_path / "bad"),
        ],
    )
    assert bad.exit_code == 1 and "failed gates: 4" in bad.output


def _copy(name: str, tmp_path: Path) -> Path:
    dst = tmp_path / name
    shutil.copytree(RUNS / name, dst)
    return dst


def test_demote_quote_failure_becomes_hypothesis(tmp_path):
    run = _copy("broken_g01", tmp_path)
    summary = demote(run, CFG)
    assert summary["demote"] == ["claim:C1"]
    from nmt_engine.store import load_run

    assert load_run(run).claims["C1"].status == "HYPOTHESIS"
    assert run_gates(run, CFG).failed_gates() == []


def test_demote_drops_forbidden_source_and_its_claims(tmp_path):
    run = _copy("broken_g14", tmp_path)
    demote(run, CFG)
    from nmt_engine.store import load_run

    data = load_run(run)
    assert "S-f1" not in data.sources and "C3" not in data.claims
    assert run_gates(run, CFG).passed


def test_demote_collapses_astroturf_and_single_signals(tmp_path):
    run = _copy("broken_g12", tmp_path)
    demote(run, CFG)
    from nmt_engine.store import load_run

    assert load_run(run).claims["C1"].voices == 3
    assert run_gates(run, CFG).passed
    run11 = _copy("broken_g11", tmp_path)
    demote(run11, CFG)
    d = load_run(run11)
    assert d.claims["C2"].single_signal
    assert "C2" not in d.segments["SEG1"].claim_ids and d.jobs["J2"].thin
    assert "C2" not in d.strategies["ST1"].why_we_win.claim_ids


def test_demote_flags_unfixable(tmp_path):
    run = _copy("broken_g04", tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["gates", "demote", str(run), "--forbidden-corpus", str(CORPUS)])
    assert res.exit_code == 0 and "calc:K3" in res.output
    from nmt_engine.store import load_run

    assert "g04_calc_recompute" in load_run(run).calcs["K3"].flags


def test_demote_recounts_overstated_voices(tmp_path):
    run = _copy("broken_g02", tmp_path)
    demote(run, CFG)
    assert run_gates(run, CFG).passed


def test_demote_retracts_calcs_on_dropped_sources(tmp_path):
    run = _copy("broken_g07", tmp_path)
    demote(run, CFG)
    from nmt_engine.store import load_run

    data = load_run(run)
    assert "S-f1" not in data.sources
    assert all(i.source_id != "S-f1" for c in data.calcs.values() for i in c.inputs)
    assert 7 not in run_gates(run, CFG).failed_gates()


def test_demote_composes_simultaneous_defects(tmp_path):
    import copy

    from tests.fixtures.make_fixtures import clean, d01, d12, d14, write

    fx = copy.deepcopy(clean())
    for defect in (d01, d12, d14):
        defect(fx)
    run = write(fx, tmp_path / "multi", "multi")
    assert set(run_gates(run, CFG).failed_gates()) >= {1, 12, 14}
    demote(run, CFG)
    assert run_gates(run, CFG).passed, run_gates(run, CFG).to_markdown()
