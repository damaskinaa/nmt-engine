"""Long n-gram overlap detection against a local forbidden corpus (gate 10)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
TEXT_SUFFIXES = {".md", ".txt", ".py", ".html", ".json", ".jsonl", ".yaml", ".yml", ".j2", ".sh"}


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def shingles(text: str, n: int) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i : i + n]) for i in range(len(w) - n + 1)}


def iter_text_files(root: Path) -> Iterable[Path]:
    root = Path(root)
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts:
            yield p


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def corpus_shingles(corpus: Path | None, n: int) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    if corpus is None:
        return out
    for p in iter_text_files(corpus):
        out |= shingles(_read(p), n)
    return out


def find_overlaps(
    texts: Iterable[tuple[str, str]], corpus: set[tuple[str, ...]], n: int
) -> list[tuple[str, str]]:
    """Return (label, first overlapping n-gram) for each text sharing an n-gram."""
    hits: list[tuple[str, str]] = []
    if not corpus:
        return hits
    for label, text in texts:
        common = shingles(text, n) & corpus
        if common:
            hits.append((label, " ".join(sorted(common)[0])))
    return hits


def scan_paths(paths: Iterable[Path], corpus_dir: Path | None, n: int = 12):
    corpus = corpus_shingles(corpus_dir, n)
    texts = (
        (str(p), _read(p))
        for root in paths
        for p in iter_text_files(root)
        if p.suffix in TEXT_SUFFIXES
    )
    return find_overlaps(texts, corpus, n)
