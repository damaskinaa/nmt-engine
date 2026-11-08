"""The pre-registration must not drift from the hash recorded when it was committed."""

from pathlib import Path

from nmt_engine.util import sha256_file

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_prereg_v2_matches_recorded_hash():
    recorded = (DOCS / "PREREG_killline_v2.md.sha256").read_text().split()[0]
    assert sha256_file(DOCS / "PREREG_killline_v2.md") == recorded
