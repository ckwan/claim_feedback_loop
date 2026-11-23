# Postgres and pgvector notes (coming from MySQL)

Short notes from building the search in this project.

## MySQL to Postgres, the parts I actually used

| Task | MySQL | Postgres |
|---|---|---|
| Auto id | AUTO_INCREMENT | identity column, or UUID text as here |
| JSON | JSON | JSONB, indexable with GIN |
| Full text | FULLTEXT + MATCH AGAINST | tsvector + GIN + to_tsquery, ts_rank |
| Extensions | none | CREATE EXTENSION vector (needs superuser) |
| Generated column | GENERATED ... STORED | GENERATED ALWAYS AS (...) STORED |
| Limit per tenant | WHERE org_id = ? | same, but the index choice matters (see below) |
| Explain | EXPLAIN | EXPLAIN (ANALYZE, BUFFERS) runs the query and shows real timings |

## pgvector in four lines

```sql
CREATE EXTENSION vector;
ALTER TABLE claim_chunks ADD COLUMN embedding vector(768);
CREATE INDEX ON claim_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
SELECT id FROM claim_chunks WHERE org_id = $1 ORDER BY embedding <=> $2 LIMIT 5;
```

`<=>` is cosine distance (0 is identical). `<->` is L2 and `<#>` is negative inner product. The operator must match the index operator class, or the index is not used.

## The lesson: filtered ANN search can return too few rows

An HNSW index finds the nearest neighbours first and applies the `WHERE org_id = ...` filter after. If another tenant's rows are closer to the query, the index returns its candidates, the filter removes them, and you can get fewer rows than `LIMIT`, even zero.

The fix is iterative scan (pgvector 0.8):

```sql
SET LOCAL hnsw.iterative_scan = 'relaxed_order';
SET LOCAL hnsw.ef_search = 100;
```

`tests/test_search_postgres.py` reproduces it: with the index forced and the other tenant's rows closer, the plain query returns 0 rows and the iterative one returns 5. `SET LOCAL` lasts for the transaction only, so it does not leak to other queries on a pooled connection.

## Hybrid search with Reciprocal Rank Fusion

Vector scores and `ts_rank` are on different scales, so they cannot be added. RRF uses ranks only:

    score = 1 / (60 + vector_rank) + 1 / (60 + keyword_rank)

A claim found by only one method still scores, from that one term. It is one SQL query with two CTEs and a FULL OUTER JOIN (`app/rag/search.py`).

## Exercises to do next

1. Run `EXPLAIN (ANALYZE, BUFFERS)` on the vector query. Find the HNSW index scan.
2. Drop the HNSW index and run again. Compare timings, then note when exact search is fine (small tables).
3. Change `ef_search` to 10, then 200. Watch recall in the retrieval eval against latency.
4. Try `ivfflat` instead of HNSW and read the difference in build time and recall.
5. Add a partial index per large tenant and see whether the planner uses it.
