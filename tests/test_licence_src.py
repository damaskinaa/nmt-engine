"""Gate 10 on the codebase: nothing under src/ may share a 12-word run with forbidden_corpus/."""

import os
from pathlib import Path

from nmt_engine.licence import find_overlaps, scan_paths, shingles

ROOT = Path(__file__).resolve().parents[1]


def test_src_has_no_forbidden_ngrams():
    corpus = Path(os.environ.get("NMT_FORBIDDEN_CORPUS", ROOT / "forbidden_corpus"))
    hits = scan_paths([ROOT / "src"], corpus, n=12)
    assert hits == [], hits


def test_detector_finds_a_planted_overlap(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.txt").write_text("one two three four five six seven eight nine ten eleven twelve")
    code = tmp_path / "src"
    code.mkdir()
    (code / "x.py").write_text("# One two three four five six seven eight nine ten eleven twelve!")
    (code / "y.py").write_text("# one two three four five six seven eight nine ten eleven")
    hits = scan_paths([code], corpus, n=12)
    assert [Path(h[0]).name for h in hits] == ["x.py"]
    assert find_overlaps([("t", "a b")], set(), 12) == []
    assert len(shingles("a b c", 2)) == 2
