from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # Who did it, for the claim history. Optional because auth is only an org header.
    adjuster_id: str | None = None


MAX_NOTES_CHARS = 5000


class ClaimEdit(BaseModel):
    """The only fields an edit may touch. Anything else, status and org_id included, is a 422."""

    model_config = ConfigDict(extra="forbid")
    claimant_name: str | None = Field(default=None, max_length=255)
    amount: float | None = Field(default=None, gt=0)
    history_notes: str | None = Field(default=None, max_length=MAX_NOTES_CHARS)
    adjuster_id: str | None = None

    @field_validator("claimant_name")
    @classmethod
    def _name_not_blank(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("claimant_name must not be empty")
        return v

    @model_validator(mode="after")
    def _required_fields_not_null(self):
        # history_notes may be set to null to clear it. The other two may not.
        for name in ("claimant_name", "amount"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class AuditEventOut(BaseModel):
    id: int
    event_type: str
    field: str | None
    old_value: str | None
    new_value: str | None
    detail: str | None
    adjuster_id: str | None
    adjuster_name: str | None
    created_at: datetime


class DecisionStatsOut(BaseModel):
    accepted: int
    overridden: int
    override_rate: float | None


class ClaimStatsOut(BaseModel):
    by_status: dict[ClaimStatus, int]
    total: int
    decisions: DecisionStatsOut
    approval_rate: float | None


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
    is_stale: bool = False
    created_at: datetime


class QueueSuggestionOut(SuggestionOut):
    # Whether an adjuster has already answered it. A suggestion takes feedback once.
    has_feedback: bool


class ClaimQueueItemOut(ClaimOut):
    latest_suggestion: QueueSuggestionOut | None


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
