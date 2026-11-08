"""Leakage guard: a backtest as of date T may not see anything dated after T."""

from collections.abc import Iterable, Mapping
from datetime import date, datetime

from nmt_engine.schema import CalcInput, Source


class LeakageError(ValueError):
    """An input dated after the backtest's as-of date was used."""


def _d(x: date | datetime | None) -> date | None:
    return x.date() if isinstance(x, datetime) else x


def assert_no_leakage(
    inputs: Iterable[CalcInput], as_of: date, sources: Mapping[str, Source] | None = None
) -> None:
    """Raise LeakageError if any input's as_of_date, or its source's as_of_date / retrieval
    date, is later than `as_of`."""
    late: list[str] = []
    for inp in inputs:
        dates = [inp.as_of_date]
        src = (sources or {}).get(inp.source_id or "")
        if src is not None:
            dates += [_d(src.as_of_date), _d(src.retrieved_at)]
        if any(d is not None and _d(d) > as_of for d in dates):
            late.append(inp.name)
    if late:
        raise LeakageError(f"inputs dated after {as_of}: {late}")
