"""Runtime configuration from environment variables (names only; values never logged)."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(os.environ.get("NMT_ROOT", Path.cwd()))


def forbidden_corpus_dir() -> Path:
    return Path(os.environ.get("NMT_FORBIDDEN_CORPUS", repo_root() / "forbidden_corpus"))
