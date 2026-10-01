import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models
from app.database import Base
from app.routers.claims_route import claim_history_summary
from app.services import suggestions_service


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_history_summary_uses_claim_notes_and_is_org_scoped(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
):
    organization = models.Organization(id="org-a", name="Test Org")
    claim = models.Claim(
        id="claim-a",
        org_id=organization.id,
        claimant_name="Test Claimant",
        amount=3200,
        status=models.ClaimStatus.UNDER_REVIEW,
        history_notes="Back injury with ongoing physical therapy.",
    )
    db_session.add_all([organization, claim])
    db_session.commit()

    prompts = []

    def mock_llm(prompt: str) -> str:
        prompts.append(prompt)
        return (
            '{"summary":"Back injury with ongoing therapy.", '
            '"suggested_next_steps":["Discuss progress with the treating clinician"]}'
        )

    monkeypatch.setattr(suggestions_service, "_call_llm", mock_llm)

    result = claim_history_summary("claim-a", db=db_session, org_id="org-a")

    assert result.summary == "Back injury with ongoing therapy."
    assert result.suggested_next_steps == [
        "Discuss progress with the treating clinician"
    ]
    assert "Back injury with ongoing physical therapy." in prompts[0]
    assert "Do not diagnose" in prompts[0]

    with pytest.raises(HTTPException) as error:
        claim_history_summary("claim-a", db=db_session, org_id="org-b")
    assert error.value.status_code == 404
    assert len(prompts) == 1