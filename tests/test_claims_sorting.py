from datetime import datetime

import pytest

from app import models
from app.routers.claims import list_claims


def seed(db):
    def claim(id_, org, name, amount, status, day):
        return models.Claim(id=id_, org_id=org, claimant_name=name, amount=amount, status=status,
                            created_at=datetime(2026, 1, day), updated_at=datetime(2026, 1, day))

    db.add_all([
        claim("org-a-open-low", "org-a", "Open low", 100, models.ClaimStatus.OPEN, 3),
        claim("org-a-open-high", "org-a", "Open high", 300, models.ClaimStatus.OPEN, 2),
        claim("org-a-review", "org-a", "Under review", 200, models.ClaimStatus.UNDER_REVIEW, 4),
        claim("org-b-open", "org-b", "Other organization", 50, models.ClaimStatus.OPEN, 5),
    ])
    db.commit()


def page(db, **kw):
    args = dict(db=db, org_id="org-a", status_filter=None, amount_order=None, limit=20, offset=0)
    args.update(kw)
    return list_claims(**args)


@pytest.mark.parametrize(("amount_order", "expected_amount"), [("asc", 300), ("desc", 100)])
def test_list_claims_sorts_amount_before_pagination_and_keeps_filters(db_session, amount_order, expected_amount):
    seed(db_session)
    claims = page(db_session, status_filter=models.ClaimStatus.OPEN, amount_order=amount_order, limit=1, offset=1)
    assert [c.amount for c in claims] == [expected_amount]


def test_default_order_is_newest_first(db_session):
    seed(db_session)
    assert [c.id for c in page(db_session)] == ["org-a-review", "org-a-open-low", "org-a-open-high"]


def test_amount_order_covers_the_whole_result_not_just_a_page(db_session):
    seed(db_session)
    assert [c.amount for c in page(db_session, amount_order="asc")] == [100, 200, 300]
    assert [c.amount for c in page(db_session, amount_order="desc", limit=2)] == [300, 200]


def test_another_orgs_claims_never_appear_in_any_variant(db_session):
    seed(db_session)
    for order in (None, "asc", "desc"):
        for status in (None, models.ClaimStatus.OPEN, models.ClaimStatus.UNDER_REVIEW):
            assert all(c.org_id == "org-a" for c in page(db_session, status_filter=status, amount_order=order))


def test_offset_past_the_end_is_empty(db_session):
    seed(db_session)
    assert page(db_session, offset=50) == []


def test_amount_order_over_http(client):
    from tests.conftest import make_claim, make_org

    org_id, h = make_org(client)
    for amount in (30, 10, 20):
        make_claim(client, org_id, h, amount=amount)
    res = client.get("/claims", headers=h, params={"amount_order": "asc", "limit": 2})
    assert [c["amount"] for c in res.json()] == [10, 20]
    assert client.get("/claims", headers=h, params={"amount_order": "sideways"}).status_code == 422
    assert client.get("/claims", headers=h, params={"limit": 0}).status_code == 422
