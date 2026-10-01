from datetime import datetime

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


class ClaimHistorySummaryOut(BaseModel):
    summary: str
    suggested_next_steps: list[str]


# ---- Suggestions (the AI half of the feedback loop) ----


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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
