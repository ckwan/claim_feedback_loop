from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models import ClaimStatus, FeedbackAction


# ---- Organizations / Adjusters (minimal, just enough to satisfy FKs) ----


class OrganizationCreate(BaseModel):
    name: str


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str


class AdjusterCreate(BaseModel):
    org_id: str
    name: str
    email: str


class AdjusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    org_id: str
    name: str
    email: str


# ---- Claims ----


class ClaimCreate(BaseModel):
    org_id: str
    claimant_name: str
    amount: float
    history_notes: str | None = None


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    org_id: str
    claimant_name: str
    amount: float
    status: ClaimStatus
    history_notes: str | None
    created_at: datetime
    updated_at: datetime


class ClaimStatusUpdate(BaseModel):
    new_status: ClaimStatus


# ---- Suggestions (the AI half of the feedback loop) ----


class SuggestionOut(BaseModel):
    # protected_namespaces=() silences Pydantic's warning about the
    # model_version field name colliding with its reserved "model_" prefix
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: str
    claim_id: str
    suggested_action: str
    rationale: str | None
    confidence: float
    model_version: str
    created_at: datetime


# ---- Feedback (the human half of the feedback loop) ----


class FeedbackCreate(BaseModel):
    adjuster_id: str
    action_taken: FeedbackAction
    final_action: str
    override_reason: str | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    suggestion_id: str
    adjuster_id: str
    action_taken: FeedbackAction
    final_action: str
    override_reason: str | None
    created_at: datetime


# ---- Search and retrieval ----


class SearchHitOut(BaseModel):
    claim_id: str
    claimant_name: str
    amount: float
    status: ClaimStatus
    snippet: str
    score: float
    # Where this result ranked in each list before they were merged. None means the
    # other method did not find it.
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None


class SearchOut(BaseModel):
    query: str
    mode: Literal["hybrid", "vector", "keyword"]
    reranked: bool
    embedding_model: str
    results: list[SearchHitOut]
    timings_ms: dict[str, float]


class ReindexOut(BaseModel):
    claims: int
    indexed: int
    unchanged: int
    failed: int


class HistorySummaryOut(BaseModel):
    claim_id: str
    summary: str
    sources: list[SearchHitOut] = []
    # True when the summary cites at least one real source.
    grounded: bool = False


# ---- Investigator agent ----


class InvestigationStep(BaseModel):
    step: int
    thought: str
    action: str
    args: dict
    observation: str


class InvestigationOut(BaseModel):
    claim_id: str
    answer: str
    cited_claim_ids: list[str]
    steps: list[InvestigationStep]
    # finished, step_limit, repeated_action or error
    stopped_because: str
