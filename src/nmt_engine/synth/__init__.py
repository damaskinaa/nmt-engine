"""Synthetic evidence core (docs/PROTOCOL.md §2-§3): calibrate, triangulate, grade, label."""

from nmt_engine.synth.calibrate import (
    CalibrationStats,
    calibrate,
    calibrated_interval,
    combined_stats,
    joint_calibration,
)
from nmt_engine.synth.estimate import MethodInput, estimate
from nmt_engine.synth.evpi import evpi_go_no_go
from nmt_engine.synth.forecast import ForecastRegistry
from nmt_engine.synth.grade import GradeInputs, grade
from nmt_engine.synth.label import citation_label
from nmt_engine.synth.leakage import LeakageError, assert_no_leakage
from nmt_engine.synth.logform import Z80, from_log, to_log
from nmt_engine.synth.triangulate import MethodEstimate, Triangulation, triangulate

__all__ = [
    "Z80",
    "CalibrationStats",
    "ForecastRegistry",
    "MethodInput",
    "GradeInputs",
    "LeakageError",
    "MethodEstimate",
    "Triangulation",
    "assert_no_leakage",
    "calibrate",
    "calibrated_interval",
    "citation_label",
    "combined_stats",
    "estimate",
    "evpi_go_no_go",
    "from_log",
    "grade",
    "joint_calibration",
    "to_log",
    "triangulate",
]
