"""
LEGACY: the original in-memory retriever (word count vectors), kept only as the
fallback when the app runs on SQLite, which has no pgvector. On Postgres the app uses
app/rag/retriever.py instead.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import models
from app.agents.llm_client import get_llm_client
from app.rag.ingestion import ingest_org_claim_history
from app.rag.vectorstore import InMemoryVectorStore


def get_history_summary(claim: "models.Claim", db: Session) -> str:
    """
    Builds an index fresh on every call. Fine at this project's scale (a
    handful of claims); at production scale the index would be built once
    and incrementally updated, not rebuilt per request.
    """
    store = InMemoryVectorStore()
    ingest_org_claim_history(db, org_id=claim.org_id, store=store)

    query = claim.history_notes or ""
    similar = store.search(query=query, org_id=claim.org_id, top_k=3)
    similar_claim_ids = [doc_id for doc_id, _score in similar if doc_id != claim.id]

    if not similar_claim_ids:
        return "No similar prior claims found in this org's history."

    context_notes = _lookup_notes(db, claim.org_id, similar_claim_ids)
    prompt = (
        "Summarize, in 2-3 sentences, what these similar prior claims suggest "
        "about how to handle the current claim. Do not invent facts not present "
        "in the notes.\n\n"
        f"Current claim: {claim.history_notes}\n\n"
        "Similar prior claims:\n" + "\n".join(f"- {note}" for note in context_notes)
    )

    client = get_llm_client()
    # Note: unlike suggestion_service.py, this summary is informational only
    # (shown to the adjuster, not used to change claim state), so it's
    # returned as-is rather than parsed into a strict schema — there's no
    # auto-action downstream for a malformed response to corrupt. If this
    # summary were ever used to drive an automated decision, it would need
    # the same parse-and-validate treatment as the suggestion path.
    return client.complete(prompt)


def _lookup_notes(db: Session, org_id: str, claim_ids: list[str]) -> list[str]:
    from sqlalchemy import select

    stmt = select(models.Claim.history_notes).where(
        models.Claim.org_id == org_id,  # tenant scoping, even on an internal helper
        models.Claim.id.in_(claim_ids),
    )
    return [note for (note,) in db.execute(stmt).all() if note]
