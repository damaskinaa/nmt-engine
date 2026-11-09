"""L0 brief (ARCHITECTURE_v3 §3 L0): goal plus a market stated in Job terms, not a category.

Multi-market screening (quick Q1-Q4 over 3-5 candidates) is out of scope for the first build,
which covers invoicing only; `candidates` is recorded so screening can be added later."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nmt_engine.util import canonical_json, sha256_text


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    goal: str = Field(min_length=10)
    market_job: str
    geography: str
    product_reach: str = Field(min_length=10)  # what the new product could cover; sets levels
    category_hint: str  # the vendor-side category word; never used as the market definition
    candidates: list[str] = Field(default_factory=list)

    @field_validator("market_job")
    @classmethod
    def _job_terms(cls, v: str) -> str:
        if not v.lower().startswith("i want to ") or len(v.split()) < 6:
            raise ValueError("market_job must be a Job: 'I want to <verb> ...', at least 6 words")
        return v

    @property
    def hash(self) -> str:
        return sha256_text(canonical_json(self.model_dump()))[:16]


def load_brief(path: Path) -> Brief:
    return Brief.model_validate(json.loads(path.read_text("utf-8")))
