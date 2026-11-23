import itertools

import pytest

from app.models import VALID_TRANSITIONS, ClaimStatus
from tests.conftest import make_adjuster, make_claim, make_org

ORDER = [ClaimStatus.OPEN, ClaimStatus.UNDER_REVIEW, ClaimStatus.APPROVED, ClaimStatus.DENIED]
PATH = {  # the shortest legal way to reach each status
    ClaimStatus.OPEN: [],
    ClaimStatus.UNDER_REVIEW: [ClaimStatus.UNDER_REVIEW],
    ClaimStatus.APPROVED: [ClaimStatus.UNDER_REVIEW, ClaimStatus.APPROVED],
    ClaimStatus.DENIED: [ClaimStatus.UNDER_REVIEW, ClaimStatus.DENIED],
}


def claim_in(client, status):
    org_id, h = make_org(client)
    claim = make_claim(client, org_id, h)
    for step in PATH[status]:
        assert client.patch(f"/claims/{claim['id']}/status", headers=h, json={"new_status": step.value}).status_code == 200
    return claim["id"], h


def test_the_transition_table_is_what_the_readme_says():
    assert VALID_TRANSITIONS == {
        ClaimStatus.OPEN: {ClaimStatus.UNDER_REVIEW},
        ClaimStatus.UNDER_REVIEW: {ClaimStatus.APPROVED, ClaimStatus.DENIED},
        ClaimStatus.APPROVED: set(),
        ClaimStatus.DENIED: set(),
    }


@pytest.mark.parametrize(("src", "dst"), list(itertools.product(ORDER, ORDER)))
def test_every_pair_of_statuses_over_the_api(client, src, dst):
    claim_id, h = claim_in(client, src)
    res = client.patch(f"/claims/{claim_id}/status", headers=h, json={"new_status": dst.value})
    if dst in VALID_TRANSITIONS[src]:
        assert res.status_code == 200 and res.json()["status"] == dst.value
    else:
        assert res.status_code == 409
        assert client.get(f"/claims/{claim_id}", headers=h).json()["status"] == src.value  # unchanged


def test_the_409_message_lists_what_is_allowed(client):
    claim_id, h = claim_in(client, ClaimStatus.APPROVED)
    detail = client.patch(f"/claims/{claim_id}/status", headers=h, json={"new_status": "open"}).json()["detail"]
    assert "terminal" in detail


def test_an_unknown_status_is_a_validation_error(client):
    claim_id, h = claim_in(client, ClaimStatus.OPEN)
    assert client.patch(f"/claims/{claim_id}/status", headers=h, json={"new_status": "pending"}).status_code == 422


def test_new_claims_start_open(client):
    org_id, h = make_org(client)
    assert make_claim(client, org_id, h)["status"] == "open"


# --- the feedback step moves the status through the same rules --------------------------


def suggestion_for(client, claim_id, h):
    return client.post(f"/claims/{claim_id}/suggest", headers=h).json()["id"]


def test_accepting_a_suggestion_applies_the_decision_to_the_claim(client):
    org_id, h = make_org(client)
    adj = make_adjuster(client, org_id)
    claim = make_claim(client, org_id, h)
    sid = suggestion_for(client, claim["id"], h)
    res = client.post(f"/suggestions/{sid}/feedback", headers=h, json={
        "adjuster_id": adj, "action_taken": "accepted", "final_action": "under_review"})
    assert res.status_code == 200
    assert client.get(f"/claims/{claim['id']}", headers=h).json()["status"] == "under_review"


def test_feedback_cannot_skip_the_state_machine(client):
    org_id, h = make_org(client)
    adj = make_adjuster(client, org_id)
    claim = make_claim(client, org_id, h)
    sid = suggestion_for(client, claim["id"], h)
    res = client.post(f"/suggestions/{sid}/feedback", headers=h, json={
        "adjuster_id": adj, "action_taken": "overridden", "final_action": "approved", "override_reason": "fast"})
    assert res.status_code == 409  # open -> approved is not allowed
    assert client.get(f"/claims/{claim['id']}", headers=h).json()["status"] == "open"
    assert client.get("/feedback/override-rate", headers=h).json()["total"] == 0  # nothing was recorded


def test_feedback_with_an_invalid_final_action_is_rejected(client):
    org_id, h = make_org(client)
    adj = make_adjuster(client, org_id)
    claim = make_claim(client, org_id, h)
    sid = suggestion_for(client, claim["id"], h)
    res = client.post(f"/suggestions/{sid}/feedback", headers=h, json={
        "adjuster_id": adj, "action_taken": "accepted", "final_action": "fly_to_moon"})
    assert res.status_code == 422


def test_an_override_needs_a_reason(client):
    org_id, h = make_org(client)
    adj = make_adjuster(client, org_id)
    claim = make_claim(client, org_id, h)
    sid = suggestion_for(client, claim["id"], h)
    res = client.post(f"/suggestions/{sid}/feedback", headers=h, json={
        "adjuster_id": adj, "action_taken": "overridden", "final_action": "under_review"})
    assert res.status_code == 422


def test_a_suggestion_takes_feedback_only_once(client):
    org_id, h = make_org(client)
    adj = make_adjuster(client, org_id)
    claim = make_claim(client, org_id, h)
    sid = suggestion_for(client, claim["id"], h)
    body = {"adjuster_id": adj, "action_taken": "accepted", "final_action": "under_review"}
    assert client.post(f"/suggestions/{sid}/feedback", headers=h, json=body).status_code == 200
    assert client.post(f"/suggestions/{sid}/feedback", headers=h, json=body).status_code == 409


def test_a_finished_claim_gets_no_action_suggestion(client):
    claim_id, h = claim_in(client, ClaimStatus.APPROVED)
    body = client.post(f"/claims/{claim_id}/suggest", headers=h).json()
    assert body["suggested_action"] == "no_action"
