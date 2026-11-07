"""Gate 10: no run output shares a 12-word sequence with the local forbidden corpus."""

from nmt_engine.gates.base import Finding, GateConfig, gate
from nmt_engine.gates.outputs import output_texts
from nmt_engine.licence import corpus_shingles, find_overlaps
from nmt_engine.store import RunData


@gate(10, "licence", "Licence n-gram overlap vs forbidden_corpus/")
def check(run: RunData, cfg: GateConfig) -> list[Finding]:
    if run.manifest is not None and run.manifest.method_module == "A":
        return []
    corpus = corpus_shingles(cfg.forbidden_corpus, cfg.ngram)
    if not corpus:
        return []
    items = list(output_texts(run))
    labelled = [(f"{t}\x00{i}", text) for t, i, text in items]
    return [
        Finding(*label.split("\x00", 1), f"shares {cfg.ngram}-gram: {gram!r}")
        for label, gram in find_overlaps(labelled, corpus, cfg.ngram)
    ]
