from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models
from app.database import Base
from app.routers.suggestions_route import create_suggestion
from app.services import suggestions_service


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_create_suggestion_includes_recent_overrides_in_prompt(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
):
    organization = models.Organization(name="Test Org")
    db_session.add(organization)
    db_session.flush()

    adjuster = models.Adjuster(
        org_id=organization.id,
        name="Test Adjuster",
        email="adjuster@example.com",
    )
    claim = models.Claim(
        org_id=organization.id,
        claimant_name="Current Claim",
        amount=3200,
        status=models.ClaimStatus.UNDER_REVIEW,
        history_notes="Ongoing physical therapy.",
    )
    db_session.add_all([adjuster, claim])
    db_session.flush()

    corrections = [
        ("under_review", "approved", "Treatment completed", datetime(2026, 1, 1)),
        ("approved", "denied", "Required documents missing", datetime(2026, 1, 2)),
    ]
    for suggested_action, final_action, reason, created_at in corrections:
        suggestion = models.Suggestion(
            claim_id=claim.id,
            suggested_action=suggested_action,
            rationale="Prior recommendation",
            confidence=0.7,
            model_version="test-model",
        )
        db_session.add(suggestion)
        db_session.flush()
        db_session.add(
            models.Feedback(
                suggestion_id=suggestion.id,
                adjuster_id=adjuster.id,
                action_taken=models.FeedbackAction.OVERRIDDEN,
                final_action=final_action,
                override_reason=reason,
                created_at=created_at,
            )
        )
    db_session.commit()

    captured_prompt = ""

    def mock_llm(prompt: str) -> str:
        nonlocal captured_prompt
        captured_prompt = prompt
        return '{"action":"approved","rationale":"Reviewed","confidence":0.8}'

    monkeypatch.setattr(suggestions_service, "_call_llm", mock_llm)

    create_suggestion(claim.id, db=db_session, org_id=organization.id)

    assert "Recent corrections:" in captured_prompt
    assert "approved -> denied; reason: Required documents missing" in captured_prompt
    assert "under_review -> approved; reason: Treatment completed" in captured_prompt
    assert captured_prompt.index("approved -> denied") < captured_prompt.index(
        "under_review -> approved"
    )