"""Append-only JSONL store (`store/<type>.jsonl`) and run-directory loader.

Every write appends a line. The current view of a type keeps the highest `rev` per id and
hides ids that another record `supersedes`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from nmt_engine.schema import (
    RECORD_TYPES,
    Calc,
    Calibration,
    Claim,
    Edge,
    Experiment,
    Forecast,
    Job,
    MarketTouch,
    Record,
    RetrievalLogEntry,
    RunManifest,
    Segment,
    SimRun,
    Source,
    Strategy,
    Synthetic,
)


class SchemaError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def type_name(record: Record) -> str:
    for name, cls in RECORD_TYPES.items():
        if type(record) is cls:
            return name
    raise KeyError(type(record).__name__)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, type_: str) -> Path:
        return self.root / f"{type_}.jsonl"

    def append(self, record: Record) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path(type_name(record)).open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json(exclude_none=True) + "\n")

    def append_many(self, records: Iterable[Record]) -> None:
        for r in records:
            self.append(r)

    def history(self, type_: str) -> list[Record]:
        cls = RECORD_TYPES[type_]
        path = self.path(type_)
        if not path.exists():
            return []
        out: list[Record] = []
        errors: list[str] = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                out.append(cls.model_validate_json(line))
            except ValidationError as exc:
                errors.append(f"{path.name}:{i}: {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}")
        if errors:
            raise SchemaError(errors)
        return out

    def current(self, type_: str) -> dict[str, Record]:
        latest: dict[str, Record] = {}
        conflicts: list[str] = []
        for rec in self.history(type_):
            prev = latest.get(rec.id)
            if prev is None or rec.rev > prev.rev:
                latest[rec.id] = rec
            elif rec.rev == prev.rev and rec != prev:
                conflicts.append(f"{self.path(type_).name}: {rec.id} rev {rec.rev} written twice")
        if conflicts:
            raise SchemaError(conflicts)
        superseded = {r.supersedes for r in latest.values() if r.supersedes}
        return {k: v for k, v in latest.items() if k not in superseded and not v.retracted}


@dataclass
class RunData:
    run_dir: Path
    manifest: RunManifest | None
    retrieval_log: list[RetrievalLogEntry]
    sources: dict[str, Source] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    calcs: dict[str, Calc] = field(default_factory=dict)
    jobs: dict[str, Job] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    segments: dict[str, Segment] = field(default_factory=dict)
    strategies: dict[str, Strategy] = field(default_factory=dict)
    experiments: dict[str, Experiment] = field(default_factory=dict)
    synthetics: dict[str, Synthetic] = field(default_factory=dict)
    calibrations: dict[str, Calibration] = field(default_factory=dict)
    forecasts: dict[str, Forecast] = field(default_factory=dict)
    market_touches: dict[str, MarketTouch] = field(default_factory=dict)
    sim_runs: dict[str, SimRun] = field(default_factory=dict)

    @property
    def store(self) -> Store:
        return Store(self.run_dir / "store")

    def source_text(self, source: Source) -> str | None:
        path = (self.run_dir / source.text_path).resolve()
        if not path.is_relative_to(self.run_dir.resolve()) or not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def claim_sources(self, claim: Claim) -> list[Source]:
        seen: dict[str, Source] = {}
        for ref in claim.source_refs:
            src = self.sources.get(ref.source_id)
            if src is not None:
                seen.setdefault(src.id, src)
        return list(seen.values())


_ATTR = {
    "source": "sources",
    "claim": "claims",
    "calc": "calcs",
    "job": "jobs",
    "edge": "edges",
    "segment": "segments",
    "strategy": "strategies",
    "experiment": "experiments",
    "synthetic": "synthetics",
    "calibration": "calibrations",
    "forecast": "forecasts",
    "market_touch": "market_touches",
    "sim_run": "sim_runs",
}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def load_run(run_dir: Path) -> RunData:
    run_dir = Path(run_dir)
    errors: list[str] = []
    manifest = None
    mpath = run_dir / "run_manifest.json"
    if mpath.exists():
        try:
            manifest = RunManifest.model_validate_json(mpath.read_text(encoding="utf-8"))
        except ValidationError as exc:
            errors.append(f"run_manifest.json: {exc}")
    log: list[RetrievalLogEntry] = []
    for i, raw in enumerate(read_jsonl(run_dir / "retrieval_log.jsonl"), start=1):
        try:
            log.append(RetrievalLogEntry.model_validate(raw))
        except ValidationError as exc:
            errors.append(f"retrieval_log.jsonl:{i}: {exc.errors()[0]['msg']}")
    data = RunData(run_dir=run_dir, manifest=manifest, retrieval_log=log)
    store = data.store
    for type_, attr in _ATTR.items():
        try:
            setattr(data, attr, store.current(type_))
        except SchemaError as exc:
            errors.extend(exc.errors)
    if errors:
        raise SchemaError(errors)
    return data


def read_text_in(run_dir: Path, rel: str) -> str:
    """Read a stored source text, refusing paths that leave run_dir."""
    root = Path(run_dir).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"source text path leaves the run dir: {rel}")
    return path.read_text(encoding="utf-8")
