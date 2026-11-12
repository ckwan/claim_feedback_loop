"""GET /claims/queue: oldest first, optional status, latest suggestion per claim, one query."""
from datetime import datetime

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app import models
from tests.conftest import make_adjuster, make_claim, make_org


def age(sqlite_engine, claim_id, day):
    with sessionmaker(bind=sqlite_engine)() as db:
        db.get(models.Claim, claim_id).created_at = datetime(2026, 1, day)
        db.commit()


def add_suggestion(sqlite_engine, claim_id, action, created_at):
    with sessionmaker(bind=sqlite_engine)() as db:
        s = models.Suggestion(
            claim_id=claim_id, suggested_action=action, confidence=0.8,
            model_version="m", created_at=created_at,
        )
        db.add(s)
        db.commit()
        return s.id


def queue(client, headers, **params):
    res = client.get("/claims/queue", headers=headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_oldest_first_and_status_filter(client, sqlite_engine):
    org, h = make_org(client, "A")
    new = make_claim(client, org, h, name="new")
    old = make_claim(client, org, h, name="old")
    mid = make_claim(client, org, h, name="mid")
    for claim, day in [(old, 1), (mid, 2), (new, 3)]:
        age(sqlite_engine, claim["id"], day)
    client.patch(f"/claims/{mid['id']}/status", headers=h, json={"new_status": "under_review"})

    assert [c["claimant_name"] for c in queue(client, h)] == ["old", "mid", "new"]
    assert [c["claimant_name"] for c in queue(client, h, status="under_review")] == ["mid"]
    assert queue(client, h, status="approved") == []


def test_returns_the_latest_suggestion_or_none(client, sqlite_engine):
    org, h = make_org(client, "A")
    with_two = make_claim(client, org, h, name="two")
    without = make_claim(client, org, h, name="none")
    age(sqlite_engine, with_two["id"], 1)
    age(sqlite_engine, without["id"], 2)
    add_suggestion(sqlite_engine, with_two["id"], "approved", datetime(2026, 2, 1))
    newest = add_suggestion(sqlite_engine, with_two["id"], "under_review", datetime(2026, 2, 2))

    rows = queue(client, h)
    assert rows[0]["latest_suggestion"]["id"] == newest
    assert rows[0]["latest_suggestion"]["suggested_action"] == "under_review"
    assert rows[0]["latest_suggestion"]["has_feedback"] is False
    assert rows[1]["latest_suggestion"] is None


def test_has_feedback_is_true_once_an_adjuster_answered(client):
    org, h = make_org(client, "A")
    adjuster = make_adjuster(client, org)
    claim = make_claim(client, org, h)
    suggestion = client.post(f"/claims/{claim['id']}/suggest", headers=h).json()
    assert queue(client, h)[0]["latest_suggestion"]["has_feedback"] is False

    res = client.post(
        f"/suggestions/{suggestion['id']}/feedback", headers=h,
        json={"adjuster_id": adjuster, "action_taken": "accepted", "final_action": "under_review"},
    )
    assert res.status_code == 200, res.text
    row = queue(client, h)[0]
    assert row["status"] == "under_review"
    assert row["latest_suggestion"]["has_feedback"] is True


def test_another_orgs_claims_and_suggestions_never_appear(client, sqlite_engine):
    a, ha = make_org(client, "A")
    b, hb = make_org(client, "B")
    claim_a = make_claim(client, a, ha, name="A claim")
    claim_b = make_claim(client, b, hb, name="B claim")
    add_suggestion(sqlite_engine, claim_a["id"], "approved", datetime(2026, 2, 1))
    sid_b = add_suggestion(sqlite_engine, claim_b["id"], "denied", datetime(2026, 2, 2))

    rows_a = queue(client, ha)
    assert [r["claimant_name"] for r in rows_a] == ["A claim"]
    assert rows_a[0]["latest_suggestion"]["suggested_action"] == "approved"
    rows_b = queue(client, hb)
    assert [r["claimant_name"] for r in rows_b] == ["B claim"]
    assert rows_b[0]["latest_suggestion"]["id"] == sid_b
    # org with no claims sees nothing, even with the status filter
    _, hc = make_org(client, "C")
    assert queue(client, hc) == [] and queue(client, hc, status="open") == []


def test_one_select_regardless_of_how_many_claims(client, sqlite_engine):
    org, h = make_org(client, "A")
    for i in range(6):
        claim = make_claim(client, org, h, name=f"c{i}")
        add_suggestion(sqlite_engine, claim["id"], "approved", datetime(2026, 2, 1))

    selects = []

    @event.listens_for(sqlite_engine, "before_cursor_execute")
    def count(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    assert len(queue(client, h)) == 6
    event.remove(sqlite_engine, "before_cursor_execute", count)
    assert len(selects) == 1, selects


def test_missing_org_header_and_bad_status_are_rejected(client):
    assert client.get("/claims/queue").status_code == 422
    org, h = make_org(client, "A")
    assert client.get("/claims/queue", headers=h, params={"status": "pending"}).status_code == 422
