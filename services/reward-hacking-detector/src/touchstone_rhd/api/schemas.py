"""API request/response schemas for the reward-hacking-detector."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class SeedCaseIn(BaseModel):
    artifact: Any
    should_pass: bool
    label: str = "seed"


class LaunchEvaluationRequest(BaseModel):
    verifier_id: uuid.UUID
    seed_cases: list[SeedCaseIn] = Field(default_factory=list)
    seed: int | None = None
    max_attacks: int | None = None
    enable_model_attacks: bool = False


class EvaluationAccepted(BaseModel):
    evaluation_id: uuid.UUID
    status: str


class ConfidenceIntervalOut(BaseModel):
    low: float
    high: float


class EvaluationOut(BaseModel):
    id: uuid.UUID
    verifier_id: uuid.UUID
    verifier_version: int
    status: str
    seed: int
    total_attacks: int
    executed: int
    errored: int
    exploits_found: int
    robustness_score: float | None = None
    weighted_robustness_score: float | None = None
    ci: ConfidenceIntervalOut | None = None
    error: str | None = None


class ExploitOut(BaseModel):
    signature: str
    verifier_id: uuid.UUID
    verifier_version: int
    category: str
    strategy: str
    severity: str
    verifier_score: float
    description: str
    failure_reason: str
    occurrences: int
    artifact: Any


class CompareRequest(BaseModel):
    baseline_evaluation_id: uuid.UUID
    candidate_evaluation_id: uuid.UUID


class CompareOut(BaseModel):
    baseline_robustness: float
    candidate_robustness: float
    delta: float
    is_regression: bool
    is_improvement: bool
    overlapping_ci: bool
    detail: str


class TrendOut(BaseModel):
    verifier_id: uuid.UUID
    direction: str
    history: list[float]


class ReportOut(BaseModel):
    """A reproducible evaluation report — everything needed to re-run + audit."""

    evaluation: EvaluationOut
    seed: int
    config: dict
    category_counts: dict[str, int]
    exploits: list[ExploitOut]
