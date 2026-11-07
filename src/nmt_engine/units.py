"""Pint registry with currencies and countable units as separate dimensions.

Currencies are distinct base dimensions, so adding EUR to GBP fails unless an explicit
conversion Calc exists. A `period` turns a value into a rate: value * unit / period.
"""

from __future__ import annotations

import ast
import operator
from functools import lru_cache

import pint

_EXTRA = """
EUR = [currency_eur]
GBP = [currency_gbp]
USD = [currency_usd]
person = [person] = people
firm = [firm] = firms = enterprise = enterprises
customer = [customer] = customers
user = [user] = users
occurrence = [occurrence] = occurrences = job_occurrence
seat = [seat] = seats
visit = [visit] = visits
lead = [lead] = leads
query = [query] = queries
"""


@lru_cache(maxsize=1)
def ureg() -> pint.UnitRegistry:
    reg = pint.UnitRegistry()
    for line in _EXTRA.strip().splitlines():
        reg.define(line)
    return reg


def quantity(value: float, unit: str | None, period: str | None) -> pint.Quantity:
    reg = ureg()
    q = value * reg(unit or "dimensionless")
    if period:
        q = q / reg(period)
    return q


def target_unit(unit: str | None, period: str | None) -> pint.Unit:
    reg = ureg()
    u = reg(unit or "dimensionless")
    if period:
        u = u / reg(period)
    return u.units if hasattr(u, "units") else u


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class FormulaError(ValueError):
    pass


def evaluate(formula: str, names: dict[str, object]):
    """Evaluate + - * / and integer powers over named quantities. Literal numbers are
    rejected: every multiplier must be a named input with a receipt."""

    def ev(node: ast.AST):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exp = node.right
            if isinstance(exp, ast.Constant) and isinstance(exp.value, int):
                return ev(node.left) ** exp.value
            raise FormulaError("only integer literal exponents are allowed")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise FormulaError(f"unknown name {node.id!r}")
            return names[node.id]
        if isinstance(node, ast.Constant):
            raise FormulaError(f"literal {node.value!r} in formula; use a named input")
        raise FormulaError(f"unsupported expression: {ast.dump(node)[:60]}")

    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(str(exc)) from exc
    return ev(tree)
