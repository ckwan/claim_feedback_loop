"""GET /claims/{id}/history: the full story of a claim, from creation to a decision."""
from tests.conftest import make_adjuster, make_claim, make_org


def history(client, headers, claim_id):
    res = client.get(f"/claims/{claim_id}/history", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def test_creation_is_recorded(client):
    org, h = make_org(client, "A")
    claim = make_claim(client, org, h)
    events = history(client, h, claim["id"])
    assert [(e["event_type"], e["new_value"]) for e in events] == [("created", "open")]


def test_status_changes_by_patch_record_old_new_and_who(client):
    org, h = make_org(client, "A")
    adjuster = make_adjuster(client, org)
    claim = make_claim(client, org, h)
    client.patch(f"/claims/{claim['id']}/status", headers=h,
                 json={"new_status": "under_review", "adjuster_id": adjuster})
    client.patch(f"/claims/{claim['id']}/status", headers=h, json={"new_status": "approved"})

    changes = [e for e in history(client, h, claim["id"]) if e["event_type"] == "status_change"]
    # newest first
    assert [(e["old_value"], e["new_value"], e["adjuster_id"]) for e in changes] == [
        ("under_review", "approved", None),
        ("open", "under_review", adjuster),
    ]


def test_a_rejected_status_change_leaves_no_trace(client):
    org, h = make_org(client, "A")
    claim = make_claim(client, org, h)
    assert client.patch(f"/claims/{claim['id']}/status", headers=h, json={"new_status": "approved"}).status_code == 409
    assert [e["event_type"] for e in history(client, h, claim["id"])] == ["created"]


def test_an_answered_suggestion_records_the_status_change_and_the_decision(client):
    org, h = make_org(client, "A")
    adjuster = make_adjuster(client, org)
    claim = make_claim(client, org, h)
    suggestion = client.post(f"/claims/{claim['id']}/suggest", headers=h).json()
    client.post(
        f"/suggestions/{suggestion['id']}/feedback", headers=h,
        json={"adjuster_id": adjuster, "action_taken": "overridden", "final_action": "under_review",
              "override_reason": "Prior flag in the file."},
    )
    events = history(client, h, claim["id"])
    decision = next(e for e in events if e["event_type"] == "suggestion_decision")
    assert decision["field"] == "overridden"
    assert decision["old_value"] == suggestion["suggested_action"]
    assert decision["new_value"] == "under_review"
    assert decision["detail"] == "Prior flag in the file."
    assert decision["adjuster_id"] == adjuster
    status = next(e for e in events if e["event_type"] == "status_change")
    assert (status["old_value"], status["new_value"]) == ("open", "under_review")


def test_history_is_scoped_to_the_org(client):
    a, ha = make_org(client, "A")
    b, hb = make_org(client, "B")
    claim_a = make_claim(client, a, ha)
    claim_b = make_claim(client, b, hb)
    assert client.get(f"/claims/{claim_a['id']}/history", headers=hb).status_code == 404
    assert [e["event_type"] for e in history(client, hb, claim_b["id"])] == ["created"]
    assert client.get(f"/claims/{claim_a['id']}/history").status_code == 422


def test_the_status_endpoint_rejects_an_adjuster_from_another_org(client):
    a, ha = make_org(client, "A")
    b, _ = make_org(client, "B")
    stranger = make_adjuster(client, b, "b@example.com")
    claim = make_claim(client, a, ha)
    res = client.patch(f"/claims/{claim['id']}/status", headers=ha,
                       json={"new_status": "under_review", "adjuster_id": stranger})
    assert res.status_code == 422
    assert client.get(f"/claims/{claim['id']}", headers=ha).json()["status"] == "open"
