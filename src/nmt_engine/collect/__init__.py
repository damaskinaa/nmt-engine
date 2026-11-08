"""Lawful public-data collectors. Every adapter returns Source records (and tidy DataFrames
for statistics); see each module docstring for its access basis and terms URL."""

from nmt_engine.collect.base import Collector, ForbiddenHostError, MissingKeyError, is_forbidden

__all__ = ["Collector", "ForbiddenHostError", "MissingKeyError", "is_forbidden"]
