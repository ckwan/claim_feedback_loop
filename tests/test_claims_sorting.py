from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models
from app.database import Base
from app.routers.claims_route import list_claims


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.mark.parametrize(
    ("amount_order", "expected_amount"),
    [("asc", 300), ("desc", 100)],
)
def test_list_claims_sorts_amount_before_pagination_and_keeps_filters(
    db_session: Session, amount_order: str, expected_amount: float
):
    db_session.add_all(
        [
            models.Claim(
                id="org-a-open-low",
                org_id="org-a",
                claimant_name="Open low",
                amount=100,
                status=models.ClaimStatus.OPEN,
                created_at=datetime(2026, 1, 3),
                updated_at=datetime(2026, 1, 3),
            ),
            models.Claim(
                id="org-a-open-high",
                org_id="org-a",
                claimant_name="Open high",
                amount=300,
                status=models.ClaimStatus.OPEN,
                created_at=datetime(2026, 1, 2),
                updated_at=datetime(2026, 1, 2),
            ),
            models.Claim(
                id="org-a-review",
                org_id="org-a",
                claimant_name="Under review",
                amount=200,
                status=models.ClaimStatus.UNDER_REVIEW,
                created_at=datetime(2026, 1, 4),
                updated_at=datetime(2026, 1, 4),
            ),
            models.Claim(
                id="org-b-open",
                org_id="org-b",
                claimant_name="Other organization",
                amount=50,
                status=models.ClaimStatus.OPEN,
                created_at=datetime(2026, 1, 5),
                updated_at=datetime(2026, 1, 5),
            ),
        ]
    )
    db_session.commit()

    claims = list_claims(
        db=db_session,
        org_id="org-a",
        status_filter=models.ClaimStatus.OPEN,
        amount_order=amount_order,
        limit=1,
        offset=1,
    )

    assert [claim.amount for claim in claims] == [expected_amount]