"""Which run artefacts count as human-facing output text (gates 8 and 10)."""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from pathlib import Path

from nmt_engine.store import RunData

OUTPUT_SUFFIXES = {".md", ".html", ".txt"}
_TAG = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S | re.I)


def output_files(run: RunData) -> list[Path]:
    files = [p for p in sorted(run.run_dir.glob("*")) if p.suffix in OUTPUT_SUFFIXES]
    reports = run.run_dir / "reports"
    if reports.is_dir():
        files += [p for p in sorted(reports.rglob("*")) if p.suffix in OUTPUT_SUFFIXES]
    return [p for p in files if p.is_file()]


def prompt_texts(run: RunData) -> Iterator[tuple[str, str, str]]:
    """Yield ("file", path, text) for every prompt sent to a model (run_dir/prompts/)."""
    prompts = run.run_dir / "prompts"
    if prompts.is_dir():
        for p in sorted(prompts.rglob("*")):
            if p.is_file():
                yield "file", str(p.relative_to(run.run_dir)), p.read_text("utf-8", "replace")


def visible_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = html.unescape(_TAG.sub(" ", text))
    return text


def output_texts(run: RunData) -> Iterator[tuple[str, str, str]]:
    """Yield (object_type, object_id, text) for every human-facing text in the run."""
    for p in output_files(run):
        yield "file", str(p.relative_to(run.run_dir)), visible_text(p)
    for c in run.claims.values():
        if c.status != "PUBLIC_VOICE":
            yield "claim", c.id, c.text
    for s in run.strategies.values():
        parts = [s.goal, s.why_we_win.added_value, s.why_we_win.activation]
        parts += [s.positioning or "", s.price or "", s.business_model or ""]
        parts += [a.action for a in s.actions]
        yield "strategy", s.id, "\n".join(parts)
