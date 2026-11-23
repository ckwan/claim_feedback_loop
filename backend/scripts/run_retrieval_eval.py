"""
Retrieval eval: keyword vs vector vs hybrid vs hybrid + LLM rerank.

Loads backend/data/retrieval_eval.json (synthetic claims and queries with known
relevant claims) into a throwaway organization in the Postgres database named by
DATABASE_URL, indexes it, scores every method, prints a table, saves the numbers, and
removes the data again.

Needs Postgres with pgvector (`docker compose up db`, then `alembic upgrade head`).

Real numbers need real models:
    ollama pull nomic-embed-text
    ollama pull qwen2.5:7b
    EMBEDDING_PROVIDER=ollama LLM_PROVIDER=ollama OLLAMA_MODEL=qwen2.5:7b \\
        python scripts/run_retrieval_eval.py

With the defaults (the offline hash embedder and stub reranker) the script only checks
that the plumbing works. The hash embedder matches shared words and does not understand
meaning, so those numbers say nothing about how good semantic search is.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal, is_postgres  # noqa: E402
from app.rag import evalkit  # noqa: E402
from app.rag.embeddings import get_embedder  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "data" / "retrieval_results"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare retrieval methods.")
    parser.add_argument("--no-rerank", action="store_true", help="Skip the LLM reranking row")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    if not is_postgres():
        sys.exit("This eval needs Postgres with pgvector. Set DATABASE_URL to a postgresql:// URL.")

    embedder = get_embedder()
    dataset = evalkit.load_dataset()
    methods = tuple(m for m in evalkit.METHODS if not (args.no_rerank and "rerank" in m))

    db = SessionLocal()
    org = models.Organization(name="retrieval-eval (temporary)")
    db.add(org)
    db.commit()
    try:
        print(f"Embedding {len(dataset['claims'])} claims with {embedder.name} ...", file=sys.stderr)
        ids = evalkit.load_corpus(db, org.id, dataset["claims"], embedder)
        print(f"Scoring {len(dataset['queries'])} queries x {len(methods)} methods ...", file=sys.stderr)
        results = evalkit.run_eval(db, org.id, dataset, ids, embedder, methods)
    finally:
        db.rollback()
        db.execute(delete(models.ClaimChunk).where(models.ClaimChunk.org_id == org.id))
        db.execute(delete(models.Claim).where(models.Claim.org_id == org.id))
        db.execute(delete(models.Organization).where(models.Organization.id == org.id))
        db.commit()
        db.close()

    print(evalkit.table(results))
    if not args.no_save:
        RESULTS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = RESULTS / f"{stamp}-{embedder.name.replace(':', '-')}.json"
        path.write_text(json.dumps({"embedder": embedder.name, "results": results}, indent=2))
        print(f"\nSaved {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
