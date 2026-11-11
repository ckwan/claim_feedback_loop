"""PATCH /claims/{id}: editing details, the history it writes, and stale suggestions."""
import pytest

from tests.conftest import make_adjuster, make_claim, make_org


def edit(client, headers, claim_id, **body):
    return client.patch(f"/claims/{claim_id}", headers=headers, json=body)


def history(client, headers, claim_id):
    res = client.get(f"/claims/{claim_id}/history", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def to_status(client, headers, claim_id, *steps):
    for step in steps:
        assert client.patch(f"/claims/{claim_id}/status", headers=headers, json={"new_status": step}).status_code == 200


@pytest.fixture()
def world(client):
    org, h = make_org(client, "A")
    adjuster = make_adjuster(client, org)
    claim = make_claim(client, org, h, notes="Water damage in the kitchen.", amount=500, name="Jane")
    return {"org": org, "h": h, "adjuster": adjuster, "claim": claim}


@pytest.mark.parametrize("steps", [[], ["under_review"]])
def test_edit_works_while_open_and_under_review(client, world, steps):
    h, cid = world["h"], world["claim"]["id"]
    to_status(client, h, cid, *steps)
    res = edit(client, h, cid, amount=750, claimant_name="  Jane Roe ", history_notes="Burst pipe.")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["amount"], body["claimant_name"], body["history_notes"]) == (750, "Jane Roe", "Burst pipe.")
    assert client.get(f"/claims/{cid}", headers=h).json()["amount"] == 750


@pytest.mark.parametrize("final", ["approved", "denied"])
def test_a_final_claim_cannot_be_edited(client, world, final):
    h, cid = world["h"], world["claim"]["id"]
    to_status(client, h, cid, "under_review", final)
    before = len(history(client, h, cid))
    res = edit(client, h, cid, amount=1)
    assert res.status_code == 409
    assert final in res.json()["detail"] and "final" in res.json()["detail"]
    assert client.get(f"/claims/{cid}", headers=h).json()["amount"] == 500
    assert len(history(client, h, cid)) == before


def test_another_orgs_claim_looks_missing_and_stays_unchanged(client, world):
    _, hb = make_org(client, "B")
    cid = world["claim"]["id"]
    foreign = edit(client, hb, cid, amount=1)
    missing = edit(client, hb, "00000000-0000-0000-0000-000000000000", amount=1)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["detail"] == missing.json()["detail"]
    assert client.get(f"/claims/{cid}", headers=world["h"]).json()["amount"] == 500
    assert client.get(f"/claims/{cid}/history", headers=hb).status_code == 404


@pytest.mark.parametrize("body", [
    {"status": "approved"},
    {"org_id": "someone-else"},
    {"id": "new-id"},
    {"created_at": "2020-01-01T00:00:00"},
    {"surprise": 1},
])
def test_fields_outside_the_three_editable_ones_are_rejected(client, world, body):
    h, cid = world["h"], world["claim"]["id"]
    assert edit(client, h, cid, amount=900, **body).status_code == 422
    claim = client.get(f"/claims/{cid}", headers=h).json()
    assert claim["amount"] == 500 and claim["status"] == "open" and claim["org_id"] == world["org"]


@pytest.mark.parametrize("body", [
    {"amount": 0}, {"amount": -5}, {"amount": None},
    {"claimant_name": "   "}, {"claimant_name": ""}, {"claimant_name": None},
    {"history_notes": "x" * 5001},
])
def test_invalid_values_are_rejected(client, world, body):
    assert edit(client, world["h"], world["claim"]["id"], **body).status_code == 422


def test_an_adjuster_from_another_org_is_rejected(client, world):
    other_org, _ = make_org(client, "B")
    stranger = make_adjuster(client, other_org, "b@example.com")
    res = edit(client, world["h"], world["claim"]["id"], amount=1, adjuster_id=stranger)
    assert res.status_code == 422


def test_each_changed_field_gets_one_history_row_with_old_and_new(client, world):
    h, cid = world["h"], world["claim"]["id"]
    edit(client, h, cid, amount=750, claimant_name="Jane Roe", history_notes="Water damage in the kitchen.",
         adjuster_id=world["adjuster"])
    edits = [e for e in history(client, h, cid) if e["event_type"] == "field_edit"]
    by_field = {e["field"]: e for e in edits}
    assert set(by_field) == {"amount", "claimant_name"}  # the notes did not change
    assert (by_field["amount"]["old_value"], by_field["amount"]["new_value"]) == ("500.0", "750.0")
    assert (by_field["claimant_name"]["old_value"], by_field["claimant_name"]["new_value"]) == ("Jane", "Jane Roe")
    assert all(e["adjuster_id"] == world["adjuster"] and e["adjuster_name"] == "Adj" for e in edits)
    assert all(e["created_at"] for e in edits)


def test_an_edit_that_changes_nothing_writes_nothing(client, world):
    h, cid = world["h"], world["claim"]["id"]
    suggestion = client.post(f"/claims/{cid}/suggest", headers=h).json()
    before = history(client, h, cid)
    res = edit(client, h, cid, amount=500, claimant_name="Jane", history_notes="Water damage in the kitchen.")
    assert res.status_code == 200
    assert edit(client, h, cid).status_code == 200  # an empty body is also a no-op
    assert history(client, h, cid) == before
    assert client.get(f"/claims/{cid}/suggestions", headers=h).json()[0]["is_stale"] is False
    assert suggestion["is_stale"] is False


def test_notes_are_cleaned_like_other_untrusted_text(client, world):
    h, cid = world["h"], world["claim"]["id"]
    res = edit(client, h, cid, history_notes="  clean\x00 me\x07  ")
    assert res.json()["history_notes"] == "clean me"


def test_editing_amount_or_notes_marks_suggestions_stale_but_the_name_does_not(client, world):
    h, cid = world["h"], world["claim"]["id"]
    client.post(f"/claims/{cid}/suggest", headers=h)
    client.post(f"/claims/{cid}/suggest", headers=h)

    edit(client, h, cid, claimant_name="Jane Roe")
    assert [s["is_stale"] for s in client.get(f"/claims/{cid}/suggestions", headers=h).json()] == [False, False]

    edit(client, h, cid, amount=900)
    assert [s["is_stale"] for s in client.get(f"/claims/{cid}/suggestions", headers=h).json()] == [True, True]
    stale_events = [e for e in history(client, h, cid) if e["event_type"] == "suggestions_stale"]
    assert [e["new_value"] for e in stale_events] == ["marked stale (2)"]


def test_a_stale_suggestion_cannot_be_accepted_or_overridden(client, world):
    h, cid, adj = world["h"], world["claim"]["id"], world["adjuster"]
    old = client.post(f"/claims/{cid}/suggest", headers=h).json()
    edit(client, h, cid, history_notes="New facts: the claimant also has a prior flag.")

    for body in (
        {"adjuster_id": adj, "action_taken": "accepted", "final_action": "under_review"},
        {"adjuster_id": adj, "action_taken": "overridden", "final_action": "under_review", "override_reason": "r"},
    ):
        res = client.post(f"/suggestions/{old['id']}/feedback", headers=h, json=body)
        assert res.status_code == 409
        assert "Request a new suggestion" in res.json()["detail"]
    assert client.get(f"/claims/{cid}", headers=h).json()["status"] == "open"
    assert client.get("/feedback/override-rate", headers=h).json()["total"] == 0

    fresh = client.post(f"/claims/{cid}/suggest", headers=h).json()
    assert fresh["is_stale"] is False
    ok = client.post(
        f"/suggestions/{fresh['id']}/feedback", headers=h,
        json={"adjuster_id": adj, "action_taken": "accepted", "final_action": "under_review"},
    )
    assert ok.status_code == 200, ok.text


def test_the_search_index_is_refreshed_only_when_the_notes_change(client, world, monkeypatch):
    from app.routers import claims as claims_router

    calls = []
    monkeypatch.setattr(claims_router, "session_is_postgres", lambda db: True)
    monkeypatch.setattr(claims_router, "try_index_claim", lambda db, claim, embedder: calls.append(claim.id))
    h, cid = world["h"], world["claim"]["id"]

    edit(client, h, cid, amount=800)
    assert calls == []
    edit(client, h, cid, history_notes="Different notes.")
    assert calls == [cid]
    edit(client, h, cid, history_notes="Different notes.")  # unchanged
    assert calls == [cid]


def test_an_indexing_failure_does_not_fail_the_edit(client, world, monkeypatch):
    from app.routers import claims as claims_router

    monkeypatch.setattr(claims_router, "session_is_postgres", lambda db: True)

    # try_index_claim swallows embedder errors, so a failing embedder is enough.
    class Broken:
        name = "broken"

        def embed_documents(self, texts):
            raise RuntimeError("Ollama is down")

    monkeypatch.setattr(claims_router, "get_embedder", lambda: Broken())
    res = edit(client, world["h"], world["claim"]["id"], history_notes="Other notes.")
    assert res.status_code == 200
    assert res.json()["history_notes"] == "Other notes."
