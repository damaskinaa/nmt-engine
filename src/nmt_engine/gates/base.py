"""Gate framework: each gate is a pure function RunData -> list[Finding]."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from nmt_engine.store import RunData

Action = Literal["demote", "drop", "flag", "single_signal", "collapse"]


@dataclass(frozen=True)
class Finding:
    object_type: str
    object_id: str
    message: str
    action: Action = "flag"

    def as_dict(self) -> dict[str, str]:
        return {
            "object_type": self.object_type,
            "object_id": self.object_id,
            "message": self.message,
            "action": self.action,
        }


@dataclass
class GateConfig:
    forbidden_corpus: Path | None = None
    ngram: int = 12
    minhash_threshold: float = 0.8
    astroturf_window_hours: float = 72.0
    calc_rel_tol: float = 1e-6
    forbidden_hosts: tuple[str, ...] = (
        "linkedin.com",
        "glassdoor.",
        "g2.com",
        "capterra.",
        "trustpilot.",
    )


GateFn = Callable[[RunData, GateConfig], list[Finding]]


@dataclass(frozen=True)
class Gate:
    number: int
    key: str
    title: str
    fn: GateFn

    @property
    def id(self) -> str:
        return f"g{self.number:02d}_{self.key}"


@dataclass
class GateResult:
    gate: Gate
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict:
        return {
            "id": self.gate.id,
            "number": self.gate.number,
            "title": self.gate.title,
            "passed": self.passed,
            "findings": [f.as_dict() for f in self.findings],
        }


REGISTRY: dict[int, Gate] = {}


def gate(number: int, key: str, title: str) -> Callable[[GateFn], GateFn]:
    def deco(fn: GateFn) -> GateFn:
        REGISTRY[number] = Gate(number, key, title, fn)
        return fn

    return deco
