"""The SQLite fallback for the history summary. The Postgres version, with citations,
is tested in test_search_postgres.py."""
import pytest
from fastapi import HTTPException

from app import models
from app.rag.retriever import get_history_summary
from app.routers.claims import claim_history_summary


@pytest.fixture()
def prompts(monkeypatch):
    seen = []

    class Client:
        def complete(self, prompt, json_mode=False):
            seen.append(prompt)
            return "Back injuries here usually needed therapy."

    monkeypatch.setattr("app.rag.legacy_retriever.get_llm_client", lambda: Client())
    return seen


def add(db, id_, org, notes):
    db.add(models.Claim(id=id_, org_id=org, claimant_name="x", amount=3200,
                        status=models.ClaimStatus.UNDER_REVIEW, history_notes=notes))


def test_summary_uses_similar_notes_from_the_same_org_only(db_session, prompts):
    db_session.add_all([models.Organization(id="org-a", name="A"), models.Organization(id="org-b", name="B")])
    add(db_session, "current", "org-a", "Back injury with ongoing physical therapy.")
    add(db_session, "similar", "org-a", "Back injury treated with physical therapy last year.")
    add(db_session, "foreign", "org-b", "Back injury and physical therapy at another insurer.")
    db_session.commit()

    summary = get_history_summary(db_session.get(models.Claim, "current"), db_session)
    assert summary == "Back injuries here usually needed therapy."
    assert "last year" in prompts[0]
    assert "another insurer" not in prompts[0]


def test_no_similar_claims_means_no_model_call(db_session, prompts):
    db_session.add(models.Organization(id="org-a", name="A"))
    add(db_session, "only", "org-a", "A lone note about something unique.")
    db_session.commit()
    summary = get_history_summary(db_session.get(models.Claim, "only"), db_session)
    assert "No similar prior claims" in summary
    assert prompts == []


def test_route_is_org_scoped(db_session, prompts):
    db_session.add(models.Organization(id="org-a", name="A"))
    add(db_session, "claim-a", "org-a", "Back injury with ongoing physical therapy.")
    db_session.commit()
    out = claim_history_summary("claim-a", db=db_session, org_id="org-a")
    assert out.claim_id == "claim-a" and out.sources == [] and out.grounded is False
    with pytest.raises(HTTPException) as err:
        claim_history_summary("claim-a", db=db_session, org_id="org-b")
    assert err.value.status_code == 404
