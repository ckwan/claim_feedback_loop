"""One organization must never see or change another's data, on any endpoint.

Org B owns a claim, a suggestion and some feedback. Org A calls every endpoint that
takes one of their ids, and every one must answer exactly as it would for an id that
does not exist, so a caller cannot even learn that the id is real.
"""
import pytest

from tests.conftest import make_adjuster, make_claim, make_org


@pytest.fixture()
def two_orgs(client):
    a_id, ha = make_org(client, "A")
    b_id, hb = make_org(client, "B")
    claim_b = make_claim(client, b_id, hb, "Burst pipe flooded the kitchen.", amount=300, name="B claimant")
    suggestion_b = client.post(f"/claims/{claim_b['id']}/suggest", headers=hb).json()
    adjuster_b = make_adjuster(client, b_id, "b@example.com")
    return {"a": (a_id, ha), "b": (b_id, hb), "claim_b": claim_b, "suggestion_b": suggestion_b, "adjuster_b": adjuster_b}


def calls(world):
    cid, sid, adj = world["claim_b"]["id"], world["suggestion_b"]["id"], world["adjuster_b"]
    return [
        ("get", f"/claims/{cid}", None),
        ("patch", f"/claims/{cid}/status", {"new_status": "under_review"}),
        ("get", f"/claims/{cid}/history-summary", None),
        ("post", f"/claims/{cid}/suggest", None),
        ("get", f"/claims/{cid}/suggestions", None),
        ("post", f"/claims/{cid}/investigate", None),
        ("post", f"/suggestions/{sid}/feedback",
         {"adjuster_id": adj, "action_taken": "accepted", "final_action": "under_review"}),
    ]


def as_missing(path):
    # the same request with an id that exists nowhere
    for real in path.split("/"):
        if len(real) == 36 and real.count("-") == 4:
            path = path.replace(real, "00000000-0000-0000-0000-000000000000")
    return path


def test_every_endpoint_answers_404_for_another_orgs_ids(client, two_orgs):
    _, ha = two_orgs["a"]
    for method, path, body in calls(two_orgs):
        res = getattr(client, method)(path, headers=ha, **({"json": body} if body else {}))
        assert res.status_code == 404, f"{method.upper()} {path} -> {res.status_code}"


def test_a_foreign_id_looks_identical_to_a_missing_id(client, two_orgs):
    _, ha = two_orgs["a"]
    for method, path, body in calls(two_orgs):
        kwargs = {"json": body} if body else {}
        foreign = getattr(client, method)(path, headers=ha, **kwargs)
        missing = getattr(client, method)(as_missing(path), headers=ha, **kwargs)
        assert (foreign.status_code, foreign.json()["detail"].split()[0]) == \
               (missing.status_code, missing.json()["detail"].split()[0]), path


def test_nothing_changed_after_the_attempts(client, two_orgs):
    _, ha = two_orgs["a"]
    _, hb = two_orgs["b"]
    for method, path, body in calls(two_orgs):
        getattr(client, method)(path, headers=ha, **({"json": body} if body else {}))
    claim = client.get(f"/claims/{two_orgs['claim_b']['id']}", headers=hb).json()
    assert claim["status"] == "open"
    assert len(client.get(f"/claims/{claim['id']}/suggestions", headers=hb).json()) == 1
    assert client.get("/feedback/override-rate", headers=hb).json()["total"] == 0


def test_lists_only_contain_the_callers_claims(client, two_orgs):
    a_id, ha = two_orgs["a"]
    assert client.get("/claims", headers=ha).json() == []
    make_claim(client, a_id, ha, "A's own claim")
    listed = client.get("/claims", headers=ha).json()
    assert len(listed) == 1 and listed[0]["org_id"] == a_id
    for status in ("open", "under_review", "approved", "denied"):
        assert all(c["org_id"] == a_id for c in client.get("/claims", headers=ha, params={"status": status}).json())
    assert all(c["org_id"] == a_id for c in client.get("/claims", headers=ha, params={"amount_order": "asc"}).json())


def test_override_rate_counts_only_the_callers_feedback(client, two_orgs):
    a_id, ha = two_orgs["a"]
    b_id, hb = two_orgs["b"]
    adj_b = two_orgs["adjuster_b"]
    sid = two_orgs["suggestion_b"]["id"]
    client.post(f"/suggestions/{sid}/feedback", headers=hb, json={
        "adjuster_id": adj_b, "action_taken": "overridden", "final_action": "under_review", "override_reason": "r"})
    assert client.get("/feedback/override-rate", headers=hb).json()["total"] == 1
    assert client.get("/feedback/override-rate", headers=ha).json() == {"total": 0, "overridden": 0, "override_rate": None}


def test_a_body_org_id_must_match_the_header(client, two_orgs):
    a_id, ha = two_orgs["a"]
    b_id, _ = two_orgs["b"]
    res = client.post("/claims", headers=ha, json={"org_id": b_id, "claimant_name": "x", "amount": 1})
    assert res.status_code == 403


def test_the_org_header_is_required(client, two_orgs):
    assert client.get("/claims").status_code == 422
    assert client.get(f"/claims/{two_orgs['claim_b']['id']}").status_code == 422


def test_an_unknown_org_header_sees_nothing(client, two_orgs):
    assert client.get("/claims", headers={"X-Org-Id": "no-such-org"}).json() == []
    assert client.get(f"/claims/{two_orgs['claim_b']['id']}", headers={"X-Org-Id": "no-such-org"}).status_code == 404


# --- search (Postgres) ---------------------------------------------------------------


def test_search_never_returns_another_orgs_claims(pg_client):
    a_id, ha = make_org(pg_client, "A")
    b_id, hb = make_org(pg_client, "B")
    same = "Burst pipe flooded the kitchen."  # identical text in both tenants
    claim_a = make_claim(pg_client, a_id, ha, same)
    claim_b = make_claim(pg_client, b_id, hb, same)
    for mode in ("hybrid", "vector", "keyword"):
        for who, h, expected in (("A", ha, claim_a["id"]), ("B", hb, claim_b["id"])):
            res = pg_client.get("/claims/search", headers=h, params={"q": "pipe flooded kitchen", "mode": mode, "top_k": 10})
            ids = [r["claim_id"] for r in res.json()["results"]]
            assert ids == [expected], f"{mode} for {who}: {ids}"


def test_reindex_touches_only_the_callers_claims(pg_client):
    a_id, ha = make_org(pg_client, "A")
    b_id, hb = make_org(pg_client, "B")
    make_claim(pg_client, a_id, ha, "A note.")
    make_claim(pg_client, b_id, hb, "B note.")
    assert pg_client.post("/claims/reindex", headers=ha).json()["claims"] == 1


def test_history_summary_never_cites_another_orgs_claims(pg_client):
    a_id, ha = make_org(pg_client, "A")
    b_id, hb = make_org(pg_client, "B")
    mine = make_claim(pg_client, a_id, ha, "Pipe leak flooded the bathroom.")
    theirs = make_claim(pg_client, b_id, hb, "Pipe leak flooded the bathroom and the kitchen.")
    body = pg_client.get(f"/claims/{mine['id']}/history-summary", headers=ha).json()
    assert theirs["id"] not in [s["claim_id"] for s in body["sources"]]


# --- the SQL layer on its own ---------------------------------------------------------
# The retrieval pipeline filters by org again after the query, which would hide a
# missing filter in the SQL. These call the SQL functions directly.


def test_each_search_query_filters_by_org_by_itself(pg_db):
    from app import models
    from app.rag import search
    from app.rag.embeddings import HashEmbedder
    from app.rag.indexing import index_claim

    e = HashEmbedder()
    orgs = [models.Organization(name="A"), models.Organization(name="B")]
    pg_db.add_all(orgs)
    pg_db.commit()
    own = {}
    for org in orgs:
        claim = models.Claim(org_id=org.id, claimant_name="x", amount=1,
                             history_notes="Burst pipe flooded the kitchen.")
        pg_db.add(claim)
        pg_db.commit()
        index_claim(pg_db, claim, e)
        own[org.id] = claim.id
    a, b = orgs
    q = "pipe flooded kitchen"
    qv = e.embed_query(q)

    for hits in (
        search.search_vector(pg_db, a.id, qv, e.name, 10),
        search.search_keyword(pg_db, a.id, q, 10),
        search.search_hybrid(pg_db, a.id, q, qv, e.name, 10),
    ):
        assert [h.claim_id for h in hits] == [own[a.id]]
    assert search.search_vector(pg_db, "no-such-org", qv, e.name, 10) == []
    assert search.search_keyword(pg_db, "no-such-org", q, 10) == []
    assert search.search_hybrid(pg_db, "no-such-org", q, qv, e.name, 10) == []
