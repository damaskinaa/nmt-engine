"""Deterministic evidence gates 1-14 (docs/ARCHITECTURE.md section 6)."""

from nmt_engine.gates import (  # noqa: F401  (registration side effects)
    g01_quote_exists,
    g02_voices,
    g03_author_numbers,
    g04_calc_recompute,
    g05_geography,
    g06_double_count,
    g07_source_exists,
    g08_validation_lint,
    g09_manifest,
    g10_licence,
    g11_diversity,
    g12_astroturf,
    g13_sim_firewall,
    g14_access_basis,
)
from nmt_engine.gates.base import REGISTRY, Finding, Gate, GateConfig, GateResult
from nmt_engine.gates.runner import GateReport, demote, run_gates, write_reports

__all__ = [
    "REGISTRY",
    "Finding",
    "Gate",
    "GateConfig",
    "GateReport",
    "GateResult",
    "demote",
    "run_gates",
    "write_reports",
]
