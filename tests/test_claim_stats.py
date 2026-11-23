"""GET /claims/stats: counts by status, decision totals and rates for one organization."""
from tests.conftest import make_adjuster, make_claim, make_org


def claim_in_status(client, org_id, headers, status):
    claim = make_claim(client, org_id, headers)
    if status != "open":
        res = client.patch(f"/claims/{claim['id']}/status", headers=headers, json={"new_status": "under_review"})
        assert res.status_code == 200, res.text
    if status in ("approved", "denied"):
        res = client.patch(f"/claims/{claim['id']}/status", headers=headers, json={"new_status": status})
        assert res.status_code == 200, res.text
    return claim


def decide(client, org_id, headers, adjuster_id, action_taken):
    """Record feedback on a fresh claim, moving it open -> under_review."""
    claim = make_claim(client, org_id, headers)
    suggestion = client.post(f"/claims/{claim['id']}/suggest", headers=headers).json()
    res = client.post(
        f"/suggestions/{suggestion['id']}/feedback", headers=headers,
        json={
            "adjuster_id": adjuster_id, "action_taken": action_taken,
            "final_action": "under_review",
            "override_reason": "adjuster disagreed" if action_taken == "overridden" else None,
        },
    )
    assert res.status_code == 200, res.text


def test_counts_across_a_mix_of_statuses(client):
    org, headers = make_org(client, "A")
    for status, n in [("open", 2), ("under_review", 1), ("approved", 3), ("denied", 1)]:
        for _ in range(n):
            claim_in_status(client, org, headers, status)

    body = client.get("/claims/stats", headers=headers).json()
    assert body["by_status"] == {"open": 2, "under_review": 1, "approved": 3, "denied": 1}
    assert body["total"] == 7
    assert body["approval_rate"] == 0.75  # 3 approved of 4 decided; open and under_review do not count


def test_decision_counts_and_override_rate(client):
    org, headers = make_org(client, "A")
    adjuster = make_adjuster(client, org)
    decide(client, org, headers, adjuster, "accepted")
    decide(client, org, headers, adjuster, "overridden")
    decide(client, org, headers, adjuster, "overridden")

    decisions = client.get("/claims/stats", headers=headers).json()["decisions"]
    assert decisions == {"accepted": 1, "overridden": 2, "override_rate": 0.667}
    # the same figure the existing endpoint reports
    assert client.get("/feedback/override-rate", headers=headers).json()["override_rate"] == 0.667


def test_empty_org_has_zeros_and_null_rates(client):
    _, headers = make_org(client, "Empty")
    res = client.get("/claims/stats", headers=headers)
    assert res.status_code == 200
    assert res.json() == {
        "by_status": {"open": 0, "under_review": 0, "approved": 0, "denied": 0},
        "total": 0,
        "decisions": {"accepted": 0, "overridden": 0, "override_rate": None},
        "approval_rate": None,
    }


def test_no_decided_claims_gives_null_approval_rate(client):
    org, headers = make_org(client, "A")
    claim_in_status(client, org, headers, "open")
    claim_in_status(client, org, headers, "under_review")
    body = client.get("/claims/stats", headers=headers).json()
    assert body["total"] == 2
    assert body["approval_rate"] is None


def test_all_denied_is_a_zero_approval_rate_not_null(client):
    org, headers = make_org(client, "A")
    claim_in_status(client, org, headers, "denied")
    assert client.get("/claims/stats", headers=headers).json()["approval_rate"] == 0.0


def test_another_orgs_claims_are_never_counted(client):
    a_id, ha = make_org(client, "A")
    b_id, hb = make_org(client, "B")
    adjuster_a = make_adjuster(client, a_id, "a@example.com")
    for _ in range(3):
        claim_in_status(client, a_id, ha, "approved")
    decide(client, a_id, ha, adjuster_a, "overridden")

    # B has nothing, so everything A owns must be invisible to it
    body_b = client.get("/claims/stats", headers=hb).json()
    assert body_b["total"] == 0
    assert body_b["by_status"] == {"open": 0, "under_review": 0, "approved": 0, "denied": 0}
    assert body_b["decisions"] == {"accepted": 0, "overridden": 0, "override_rate": None}
    assert body_b["approval_rate"] is None

    # and B's own claim shows up only for B
    claim_in_status(client, b_id, hb, "denied")
    assert client.get("/claims/stats", headers=hb).json()["by_status"]["denied"] == 1
    assert client.get("/claims/stats", headers=ha).json()["by_status"]["denied"] == 0
    assert client.get("/claims/stats", headers=ha).json()["total"] == 4


def test_missing_org_header_is_rejected_like_the_other_endpoints(client):
    stats = client.get("/claims/stats")
    other = client.get("/claims")
    assert stats.status_code == other.status_code == 422
    assert client.get("/feedback/override-rate").status_code == 422
