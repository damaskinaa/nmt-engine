"""Shared typed schema (pydantic v2) used by every module.

Field lists follow the master prompt section 2 and docs/ARCHITECTURE.md section 4 /
docs/PROTOCOL.md. Additions are listed in docs/IMPLEMENTATION.md.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceKind = Literal[
    "review",
    "forum",
    "qa",
    "issue",
    "search",
    "filing",
    "pricing",
    "changelog",
    "stats",
    "procurement",
    "dataset",
    "paper",
    "news",
    "web",
]
ClaimStatus = Literal[
    "PUBLIC_VOICE", "DERIVED", "HYPOTHESIS", "SIMULATED", "PROXY_METRIC", "SYNTHETIC_ESTIMATE"
]
Grade = Literal["S0", "S1", "S2", "S3", "S4"]
GRADES: tuple[str, ...] = ("S0", "S1", "S2", "S3", "S4")
Quantity = Literal["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9"]
MethodFamily = Literal[
    "statistical", "supply", "revealed_price", "behavioural", "simulated_respondents"
]
AccessBasis = Literal["public_api_terms_ok", "open_licence", "licensed", "public_page_terms_ok"]
ALLOWED_ACCESS_BASIS: frozenset[str] = frozenset(AccessBasis.__args__)  # type: ignore[attr-defined]


def grade_rank(grade: str | None) -> int:
    """S0 -> 0 ... S4 -> 4; None/unknown -> -1."""
    return GRADES.index(grade) if grade in GRADES else -1


class Record(BaseModel):
    """Base for every stored object. The store is append-only: a later line with the same
    id is a new revision; `supersedes` links a record that replaces a different id."""

    model_config = ConfigDict(extra="forbid")

    id: str
    rev: int = 0
    supersedes: str | None = None
    retracted: bool = False
    flags: list[str] = Field(default_factory=list)


class Source(Record):
    kind: SourceKind
    platform: str
    publisher: str | None = None
    url: str
    author_hash: str | None = None
    retrieved_at: datetime
    published_at: datetime | None = None
    as_of_date: date
    geography: str
    # Typed as str so that a missing or forbidden value is reported by gate 14
    # instead of crashing the loader. Allowed values: ALLOWED_ACCESS_BASIS.
    access_basis: str | None = None
    terms_url: str | None = None
    text_path: str
    sha256: str


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    verbatim: str
    locator: str | None = None


class Claim(Record):
    text: str
    status: ClaimStatus
    grade: Grade | None = None
    voices: int = 0
    source_types: list[SourceKind] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    geography: str
    single_signal: bool = True
    stage: str = "S4"
    synthetic_id: str | None = None

    @model_validator(mode="after")
    def _grade_required_for_synthetic(self) -> Claim:
        if self.status == "SYNTHETIC_ESTIMATE" and self.grade is None:
            raise ValueError("grade is required when status is SYNTHETIC_ESTIMATE")
        return self


class CalcInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    unit: str = "dimensionless"
    period: str | None = None
    claim_id: str | None = None
    source_id: str | None = None
    corroborated_by: list[str] = Field(default_factory=list)
    as_of_date: date | None = None


class Calc(Record):
    quantity: Quantity | None = None
    method_family: MethodFamily | None = None
    method_id: str | None = None
    formula: str
    inputs: list[CalcInput]
    median: float
    interval_80: tuple[float, float] | None = None
    unit: str = "dimensionless"
    period: str | None = None
    geography: str
    geo_conversion: bool = False


class SuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    measure: str | None = None
    priority_rank: int | None = None


class Job(Record):
    statement: str
    level: Literal["big", "core", "small", "micro"]
    context: str | None = None
    trigger: str | None = None
    negative_emotions: list[str] = Field(default_factory=list)
    consideration_set: list[str] = Field(default_factory=list)
    expected_outcome: str | None = None
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    positive_emotions: list[str] = Field(default_factory=list)
    higher_job_id: str | None = None
    type: Literal["regular", "orientation", "tax", "fake", "emotional", "viral"] = "regular"
    claim_ids: list[str] = Field(default_factory=list)
    thin: bool = False


Range = tuple[float, float]


class EdgeCosts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    money: Range = (0.0, 0.0)
    time: Range = (0.0, 0.0)
    effort: Range = (0.0, 0.0)
    cognitive: Range = (0.0, 0.0)
    negative_emotion: Range = (0.0, 0.0)
    tax_jobs: Range = (0.0, 0.0)


class Edge(Record):
    from_job: str
    to_job: str
    kind: Literal["hierarchy", "sequence", "chain_handoff", "performs"]
    layer: Literal["customer", "intermediary", "business", "product"] = "customer"
    freq_weight: float | None = None
    value_weight: float | None = None
    p_success: Range | None = None
    costs: EdgeCosts | None = None
    claim_ids: list[str] = Field(default_factory=list)


class SegmentOverlap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    share: float


class SegmentPopulation(BaseModel):
    """Share of a base population (a count claim) that the segment covers."""

    model_config = ConfigDict(extra="forbid")

    geography: str
    base_claim_id: str
    share: Range
    declared_overlaps: list[SegmentOverlap] = Field(default_factory=list)


class Segment(Record):
    name: str
    core_job_ids: list[str] = Field(default_factory=list)
    criteria_priority_order: list[str] = Field(default_factory=list)
    causal_criteria: list[str] = Field(default_factory=list)
    qualification_questions: list[str] = Field(default_factory=list)
    size: str | None = Field(default=None, description="synthetic_id or calc_id of the size")
    population: SegmentPopulation | None = None
    claim_ids: list[str] = Field(default_factory=list)
    thin: bool = False


class WhyWeWin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    added_value: str
    activation: str
    claim_ids: list[str] = Field(default_factory=list)


class StrategyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function: str
    action: str
    due: str | None = None


class CompeteFor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    job_ids: list[str] = Field(default_factory=list)


class Strategy(Record):
    goal: str
    horizon: str
    compete_for: list[CompeteFor] = Field(default_factory=list)
    not_compete_for: list[str] = Field(default_factory=list)
    why_we_win: WhyWeWin
    resources: list[str] = Field(default_factory=list)
    actions: list[StrategyAction] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    business_model: str | None = None
    price: str | None = None
    positioning: str | None = None
    assumption_ids: list[str] = Field(default_factory=list)
    go_no_go_claim_ids: list[str] = Field(default_factory=list)
    score: dict[str, Any] | None = None


class Assumption(Record):
    strategy_id: str
    statement_positive: str
    segment: str | None = None
    product: str | None = None
    price: str | None = None
    channel: str | None = None
    geography: str | None = None
    input_ref: str | None = None
    evpi: float | None = None
    cost_to_test: float | None = None
    priority: float | None = None
    status: Literal["open", "confirmed", "killed", "unknown"] = "open"


class Experiment(Record):
    assumption_id: str
    kind: Literal["fake_door", "priced_waitlist", "preorder", "desk_backtest"]
    design: str
    kill_line: str
    result: str | None = None


class SyntheticMethod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: MethodFamily
    calc_id: str
    interval_80: Range


class Combined(BaseModel):
    model_config = ConfigDict(extra="forbid")

    median: float
    interval_80: Range


class Synthetic(Record):
    quantity: Quantity
    segment_id: str | None = None
    job_id: str | None = None
    geography: str
    grade: Grade
    methods: list[SyntheticMethod] = Field(default_factory=list)
    combined: Combined | None = None
    unit: str | None = None
    calibration_ids: list[str] = Field(default_factory=list)
    redteam_findings: list[str] = Field(default_factory=list)
    forecast_id: str | None = None
    market_touch_id: str | None = None
    methods_disagree: bool = False
    citation_label: str | None = None


class BacktestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: str
    as_of: date
    known_outcome: float
    predicted: float


class Calibration(Record):
    sim_kind: str | None = None
    method_family: MethodFamily
    method_id: str | None = None
    quantity: Quantity | None = None
    reference_class: str
    as_of_rule: str
    backtest_cases: list[BacktestCase] = Field(default_factory=list)
    bias_log_ratio: float | None = None
    conformal_q80: float | None = None
    coverage_80: float | None = None
    n: int = 0
    passed: bool = False


class ForecastScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hit: bool | None = None
    log_error: float | None = None
    brier: float | None = None


class Forecast(Record):
    synthetic_id: str
    resolution_rule: str
    resolve_by: date
    outcome: float | None = None
    score: ForecastScore | None = None


class MarketTouch(Record):
    kind: Literal["fake_door", "priced_waitlist", "preorder"]
    synthetic_id: str | None = None
    metric: str
    value: float
    n: int
    price: str | None = None
    started: date
    ended: date | None = None


class SimRun(Record):
    model: Literal["montecarlo", "persona_panel", "agent"]
    inputs: list[str] = Field(default_factory=list)
    n_runs: int
    seed: int
    calibration_id: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    status: Literal["SIMULATED"] = "SIMULATED"


class FrozenFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    stage: str
    purpose: Literal["own_portfolio", "third_party_output"] = "third_party_output"
    method_module: Literal["A", "B"] = "B"
    seed: int | None = None
    created_at: datetime | None = None
    frozen: list[FrozenFile] = Field(default_factory=list)
    manifest_sha256: str | None = None
    model_vendor: str | None = None
    reviewer_vendor: str | None = None
    gates: dict[str, str] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)


class RetrievalLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    url: str
    host: str
    retrieved_at: datetime
    adapter: str
    status_code: int | None = None
    sha256: str | None = None
    cache_key: str | None = None


RECORD_TYPES: dict[str, type[Record]] = {
    "source": Source,
    "claim": Claim,
    "calc": Calc,
    "job": Job,
    "edge": Edge,
    "segment": Segment,
    "strategy": Strategy,
    "assumption": Assumption,
    "experiment": Experiment,
    "synthetic": Synthetic,
    "calibration": Calibration,
    "forecast": Forecast,
    "market_touch": MarketTouch,
    "sim_run": SimRun,
}
