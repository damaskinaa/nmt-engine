"""Schema of the L1 hypothesis Job Graph. The model writes words and picks tiers; code computes
every number (RAT priority, PageRank importance)."""

from __future__ import annotations

import re
from typing import Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal["job", "solution", "criterion", "segment", "problem"]
Level = Literal["big", "core", "small", "micro"]
SolutionKind = Literal["product", "service", "spreadsheet", "manual", "diy"]
Tier = Literal["low", "medium", "high"]

# C3: the model picks a tier with a reason; these fixed maps turn tiers into numbers.
P_WRONG = {"low": 0.2, "medium": 0.5, "high": 0.8}
COST = {"low": 1.0, "medium": 3.0, "high": 9.0}
PARENT_LEVEL = {"core": "big", "small": "core", "micro": "small"}
PREFIX = {"job": "J", "solution": "S", "criterion": "C", "segment": "G", "problem": "P"}
N_SEGMENTS = (3, 6)
N_CORE = (3, 5)
MIN_CRITERIA = 2  # per Core Job, as the draft prompt says
# no invented quantities: a number is a digit run not glued to a preceding letter ("B2B" and
# "Q1" are words, "3 weeks" and "£20" are numbers). Solution names may contain any digits.
# Best effort, not a proof: \d also matches non-ASCII digits, but spelled-out numerals ("three")
# and digits glued to a letter ("x3") pass. Numbers used downstream come from code, never text.
_NUMBER = re.compile(r"(?<![A-Za-z])\d[\d.,]*%?")


class Rat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p_wrong: Tier
    cost_if_wrong: Tier
    cost_to_check: Tier
    reason: str = Field(min_length=5)

    @property
    def priority(self) -> float:
        """RAT priority = (P wrong x cost if wrong) / cost to check."""
        return round(P_WRONG[self.p_wrong] * COST[self.cost_if_wrong] / COST[self.cost_to_check], 4)


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    text: str = Field(min_length=3)
    rationale: str = Field(min_length=5)
    status: Literal["assumed"] = "assumed"
    rat: Rat
    level: Level | None = None  # job
    parent: str | None = None  # job (all but big)
    kind: SolutionKind | None = None  # solution
    serves: list[str] = Field(default_factory=list)  # solution -> jobs
    job: str | None = None  # criterion, problem -> job
    solution: str | None = None  # problem -> solution
    criteria: list[str] = Field(default_factory=list)  # problem: criteria it fails
    core_jobs: list[str] = Field(default_factory=list)  # segment
    criteria_order: list[str] = Field(default_factory=list)  # segment: most important first

    @model_validator(mode="after")
    def _shape(self) -> Node:
        if not self.id.startswith(PREFIX[self.type]) or not self.id[1:].isdigit():
            raise ValueError(f"{self.id}: id must be {PREFIX[self.type]}<number>")
        need = {
            "job": ["level"],
            "solution": ["kind", "serves"],
            "criterion": ["job"],
            "segment": ["core_jobs", "criteria_order"],
            "problem": ["job", "solution", "criteria"],
        }[self.type]
        for f in need:
            if not getattr(self, f):
                raise ValueError(f"{self.id}: {self.type} needs {f}")
        if self.type == "job":
            if not self.text.lower().startswith("i want to "):
                raise ValueError(f"{self.id}: {self.text!r} must start 'I want to <verb>'")
            if (self.level == "big") != (self.parent is None):
                raise ValueError(f"{self.id}: only the Big Job has no parent")
        if self.type == "segment" and len(self.criteria_order) < 2:
            raise ValueError(f"{self.id}: a segment orders at least 2 criteria")
        if self.type != "solution":
            m = _NUMBER.search(self.text + " " + self.rationale)
            if m:
                raise ValueError(f"{self.id}: number {m.group()!r}: no numbers in L1 text")
        return self


class HypothesisGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str
    nodes: list[Node]

    @model_validator(mode="after")
    def _links(self) -> HypothesisGraph:
        """Every link problem at once, so one regeneration can fix them all."""
        by: dict[str, Node] = {}
        errs: list[str] = []
        for n in self.nodes:
            if n.id in by:
                errs.append(f"duplicate id {n.id}")
            by[n.id] = n

        def ref(src: Node, rid: str, want: str, level: str | None = None) -> bool:
            t = by.get(rid)
            if t is None or t.type != want or (level and t.level != level):
                what = f"{level} {want}" if level else want
                errs.append(f"{src.id}: {rid} is not a {what}")
                return False
            return True

        bigs = [n for n in self.nodes if n.type == "job" and n.level == "big"]
        if len(bigs) != 1:
            errs.append(f"exactly one Big Job, got {len(bigs)}")
        cores = [n for n in self.nodes if n.type == "job" and n.level == "core"]
        if not N_CORE[0] <= len(cores) <= N_CORE[1]:
            errs.append(f"{len(cores)} Core Jobs; need {N_CORE[0]}-{N_CORE[1]}")
        for n in self.nodes:
            if n.type == "job" and n.parent:
                ref(n, n.parent, "job", PARENT_LEVEL[n.level])
            for j in n.serves:
                ref(n, j, "job")
            for c in n.criteria + n.criteria_order:
                ref(n, c, "criterion")
            for j in n.core_jobs:
                ref(n, j, "job", "core")
            if n.job:
                ref(n, n.job, "job")
            if n.solution:
                ref(n, n.solution, "solution")
        segs = self.of("segment")
        if not N_SEGMENTS[0] <= len(segs) <= N_SEGMENTS[1]:
            errs.append(f"{len(segs)} segments; need {N_SEGMENTS[0]}-{N_SEGMENTS[1]}")
        orders = [tuple(s.criteria_order) for s in segs]
        if len(set(orders)) != len(orders):
            errs.append("two segments share the same criteria order")
        for core in (n for n in self.nodes if n.level == "core"):
            if sum(c.job == core.id for c in self.of("criterion")) < MIN_CRITERIA:
                errs.append(f"{core.id}: a Core Job needs at least {MIN_CRITERIA} success criteria")
            if not any(core.id in s.serves for s in self.of("solution")):
                errs.append(
                    f"{core.id}: a Core Job needs at least one Solution hired today; fix: add "
                    f"{core.id} to the serves list of a solution people use for it, or add one"
                )
        if errs:
            raise ValueError("\n- ".join(errs))
        return self

    def of(self, kind: str) -> list[Node]:
        return [n for n in self.nodes if n.type == kind]

    def node(self, nid: str) -> Node:
        return next(n for n in self.nodes if n.id == nid)

    def edges(self) -> list[tuple[str, str, str]]:
        """(source, target, relation) for every link in the graph."""
        out = []
        for n in self.nodes:
            if n.parent:
                out.append((n.id, n.parent, "part_of"))
            out += [(n.id, j, "serves") for j in n.serves]
            if n.job:
                out.append((n.id, n.job, "judges" if n.type == "criterion" else "hurts"))
            if n.solution:
                out.append((n.id, n.solution, "caused_by"))
            out += [(n.id, c, "fails") for c in n.criteria]
            out += [(n.id, j, "does") for j in n.core_jobs]
            out += [(n.id, c, f"ranks_{i + 1}") for i, c in enumerate(n.criteria_order)]
        return out

    def importance(self) -> dict[str, float]:
        """Graph importance: PageRank over the links (fixed damping, deterministic)."""
        g = nx.DiGraph()
        g.add_nodes_from(n.id for n in self.nodes)
        g.add_edges_from((s, t) for s, t, _ in self.edges())
        return {k: round(v, 5) for k, v in nx.pagerank(g, alpha=0.85).items()}

    def riskiest(self, k: int = 10) -> list[dict]:
        """Top-k testable nodes by RAT priority, ties broken by importance, then id.
        The Big Job (the brief itself) and segments (tested in L6) are not desk-testable nodes."""
        imp = self.importance()
        pool = [n for n in self.nodes if n.type != "segment" and n.level != "big"]
        pool.sort(key=lambda n: (-n.rat.priority, -imp[n.id], n.id))
        return [
            {
                "id": n.id,
                "type": n.type,
                "text": n.text,
                "priority": n.rat.priority,
                "importance": imp[n.id],
            }
            for n in pool[:k]
        ]
