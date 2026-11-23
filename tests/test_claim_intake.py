"""Idempotent intake: POST /claims with an external_ref is safe to retry."""
import logging
import threading

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import models
from app.services import claim_intake
from app.services.claim_intake import create_or_get_claim
from tests.conftest import make_org


def post(client, org_id, headers, ref="ref-1", **overrides):
    body = {"org_id": org_id, "claimant_name": "Jane", "amount": 500.0, "history_notes": "Water damage."}
    if ref is not None:
        body["external_ref"] = ref
    body.update(overrides)
    return client.post("/claims", headers=headers, json=body)


def count(engine, **where):
    with sessionmaker(bind=engine)() as db:
        stmt = select(func.count()).select_from(models.Claim)
        for column, value in where.items():
            stmt = stmt.where(getattr(models.Claim, column) == value)
        return db.execute(stmt).scalar()


def audit_rows(engine):
    with sessionmaker(bind=engine)() as db:
        return db.execute(select(func.count()).select_from(models.AuditEvent)).scalar()


def test_first_call_creates_and_a_repeat_returns_the_same_claim(client, sqlite_engine):
    org, h = make_org(client, "A")
    first = post(client, org, h)
    assert first.status_code == 201
    audit_after_first = audit_rows(sqlite_engine)

    again = post(client, org, h)
    assert again.status_code == 200
    assert again.json() == first.json()  # same id, same updated_at: nothing was touched
    assert count(sqlite_engine, org_id=org) == 1
    assert audit_rows(sqlite_engine) == audit_after_first  # a retry writes nothing


def test_the_same_ref_in_another_org_is_a_separate_claim(client, sqlite_engine):
    a, ha = make_org(client, "A")
    b, hb = make_org(client, "B")
    claim_a = post(client, a, ha)
    claim_b = post(client, b, hb)
    assert claim_a.status_code == claim_b.status_code == 201
    assert claim_a.json()["id"] != claim_b.json()["id"]
    assert claim_b.json()["org_id"] == b
    assert count(sqlite_engine, external_ref="ref-1") == 2


def test_the_retried_claim_is_not_readable_from_another_org(client):
    a, ha = make_org(client, "A")
    _, hb = make_org(client, "B")
    claim = post(client, a, ha).json()
    assert client.get(f"/claims/{claim['id']}", headers=hb).status_code == 404
    # B posting A's ref does not reveal or return A's claim
    b_org = hb["X-Org-Id"]
    mine = post(client, b_org, hb)
    assert mine.status_code == 201 and mine.json()["id"] != claim["id"]


def test_without_a_ref_nothing_changes_from_before(client, sqlite_engine):
    org, h = make_org(client, "A")
    one = post(client, org, h, ref=None)
    two = post(client, org, h, ref=None)  # identical body, still two claims
    assert one.status_code == two.status_code == 201
    assert one.json()["id"] != two.json()["id"]
    assert one.json()["external_ref"] is None
    assert count(sqlite_engine, org_id=org) == 2


def test_a_retry_with_a_different_body_returns_the_stored_claim_and_logs_no_content(client, caplog):
    org, h = make_org(client, "A")
    first = post(client, org, h).json()
    with caplog.at_level(logging.WARNING, logger="app.services.claim_intake"):
        again = post(client, org, h, claimant_name="Someone Else", amount=9999.0, history_notes="Secret details.")
    assert again.status_code == 200
    assert again.json() == first  # unchanged
    assert "differs" in caplog.text and "claimant_name" in caplog.text and "amount" in caplog.text
    for content in ("Someone Else", "9999", "Secret details", "Jane", "Water damage"):
        assert content not in caplog.text


def test_an_identical_retry_does_not_warn(client, caplog):
    org, h = make_org(client, "A")
    post(client, org, h)
    with caplog.at_level(logging.WARNING, logger="app.services.claim_intake"):
        post(client, org, h)
    assert caplog.text == ""


@pytest.mark.parametrize("ref", ["", "   ", "\t\n"])
def test_an_empty_or_blank_ref_is_rejected(client, ref):
    org, h = make_org(client, "A")
    assert post(client, org, h, ref=ref).status_code == 422


def test_ref_length_limit_and_whitespace_trimming(client):
    org, h = make_org(client, "A")
    assert post(client, org, h, ref="x" * 129).status_code == 422
    assert post(client, org, h, ref="x" * 128).status_code == 201
    trimmed = post(client, org, h, ref="  abc  ")
    assert trimmed.status_code == 201 and trimmed.json()["external_ref"] == "abc"
    assert post(client, org, h, ref="abc").status_code == 200  # same reference


def test_the_body_org_check_is_unchanged(client):
    a, ha = make_org(client, "A")
    b, _ = make_org(client, "B")
    assert post(client, b, ha).status_code == 403


def test_get_returns_id_status_external_ref_and_updated_at(client):
    org, h = make_org(client, "A")
    created = post(client, org, h).json()
    body = client.get(f"/claims/{created['id']}", headers=h).json()
    assert {"id", "status", "external_ref", "updated_at"} <= set(body)
    assert body["external_ref"] == "ref-1" and body["status"] == "open"


def test_losing_the_insert_race_returns_the_winners_claim(client, sqlite_engine, monkeypatch):
    """Both callers pass the lookup, then one INSERT hits the unique index."""
    org, h = make_org(client, "A")
    winner = post(client, org, h).json()

    real_find = claim_intake._find
    lookups = []

    def blind_first_lookup(db, org_id, ref):
        lookups.append(ref)
        return None if len(lookups) == 1 else real_find(db, org_id, ref)

    monkeypatch.setattr(claim_intake, "_find", blind_first_lookup)
    with sessionmaker(bind=sqlite_engine)() as db:
        claim, created = create_or_get_claim(
            db, org, claimant_name="Jane", amount=500.0, history_notes="Water damage.", external_ref="ref-1"
        )
    assert created is False and claim.id == winner["id"]
    assert len(lookups) == 2  # the loser re-read after the violation
    assert count(sqlite_engine, org_id=org) == 1
    assert audit_rows(sqlite_engine) == 1  # the loser's history row was rolled back with its claim


def test_an_integrity_error_that_is_not_our_race_is_not_swallowed(sqlite_engine, monkeypatch):
    def boom(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("some other constraint"))

    monkeypatch.setattr(claim_intake, "record_event", boom)
    with sessionmaker(bind=sqlite_engine)() as db:
        with pytest.raises(IntegrityError):
            # no external_ref, so there is nothing to re-read: the error must surface
            create_or_get_claim(db, "org", claimant_name="x", amount=1, history_notes=None, external_ref=None)


# --- the real race, on Postgres ------------------------------------------------------------


def test_concurrent_duplicate_inserts_yield_one_row(pg_engine, pg_db):
    org = models.Organization(name="Race")
    pg_db.add(org)
    pg_db.commit()
    org_id = org.id

    workers = 8
    barrier = threading.Barrier(workers)
    results, errors = [], []

    def submit():
        try:
            with sessionmaker(bind=pg_engine)() as db:
                barrier.wait()  # release every thread at once
                claim, created = create_or_get_claim(
                    db, org_id, claimant_name="Jane", amount=500.0, history_notes="n", external_ref="same"
                )
                results.append((claim.id, created))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert errors == []
    assert len({claim_id for claim_id, _ in results}) == 1  # everyone got the same claim
    assert sum(1 for _, created in results if created) == 1  # exactly one actually created it
    assert count(pg_engine, org_id=org_id, external_ref="same") == 1
    assert audit_rows(pg_engine) == 1


def test_the_unique_index_is_per_org_and_ignores_missing_refs(pg_engine, pg_db):
    a, b = models.Organization(name="A"), models.Organization(name="B")
    pg_db.add_all([a, b])
    pg_db.commit()
    with sessionmaker(bind=pg_engine)() as db:
        for org_id, ref in [(a.id, "x"), (b.id, "x"), (a.id, None), (a.id, None)]:
            create_or_get_claim(db, org_id, claimant_name="n", amount=1, history_notes=None, external_ref=ref)
    assert count(pg_engine) == 4
