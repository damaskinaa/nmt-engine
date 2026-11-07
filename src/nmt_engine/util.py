"""Small shared helpers: hashing, canonical JSON, text normalisation, author hashing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

_WS = re.compile(r"\s+")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_ws(text: str) -> str:
    """NFC-normalise and collapse every whitespace run to one space."""
    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def author_hash(platform: str, author: str, salt: str | None = None) -> str:
    """Salted hash of a public author identifier. The salt comes from NMT_AUTHOR_SALT."""
    salt = salt if salt is not None else os.environ.get("NMT_AUTHOR_SALT", "")
    if not salt:
        raise RuntimeError("NMT_AUTHOR_SALT is not set; refusing to hash author ids unsalted")
    return "a_" + sha256_text(f"{salt}|{platform}|{author}")[:24]
