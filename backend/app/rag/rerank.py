"""Re-ordering search results with a language model.

Search returns candidates by similarity, which is fast and cheap but only roughly
right. A reranker reads the query and each candidate together and scores how well the
candidate answers it, which is slower but more accurate. The usual pattern is to
retrieve about ten candidates cheaply and let the model pick the best few.

The reranker only reorders. It cannot add a result, and if it fails or returns nonsense
the original order is kept, so reranking can make results better but never absent.
"""
from __future__ import annotations

import logging
from typing import Protocol

from pydantic import BaseModel, Field

from app.agents.llm_client import get_llm_client
from app.agents.parsers import LLMResponseError, parse_model
from app.safety import UNTRUSTED_NOTICE, clean_text, neutralize_tags

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

PROMPT = """Rerank these candidates by how well each answers the query. \
Respond with one JSON object and nothing else: \
{{"ranking": [{{"id": <candidate number>, "score": <0 to 10>}}, ...]}}, best first. \
Use only the candidate numbers given. {notice}

<query>
{query}
</query>

{candidates}"""


class RankedItem(BaseModel):
    id: int
    score: float = Field(ge=0, le=10)


class RerankReply(BaseModel):
    ranking: list[RankedItem]


class Reranker(Protocol):
    def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float | None]]:
        """Return (index into texts, score) for every text, best first."""


def build_prompt(query: str, texts: list[str]) -> str:
    blocks = [
        f'<candidate id="{i}">\n{neutralize_tags(clean_text(t, 600))}\n</candidate>'
        for i, t in enumerate(texts, start=1)
    ]
    return PROMPT.format(
        notice=UNTRUSTED_NOTICE, query=neutralize_tags(clean_text(query, 300)), candidates="\n".join(blocks)
    )


def validate_ranking(reply: RerankReply, count: int) -> list[tuple[int, float | None]]:
    """Keep known, unseen ids in the model's order, then append anything it left out."""
    seen: set[int] = set()
    out: list[tuple[int, float | None]] = []
    for item in reply.ranking:
        if 1 <= item.id <= count and item.id not in seen:
            seen.add(item.id)
            out.append((item.id - 1, item.score))
    out.extend((i, None) for i in range(count) if (i + 1) not in seen)
    return out


class LLMReranker:
    def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float | None]]:
        original = [(i, None) for i in range(len(texts))]
        if len(texts) < 2:
            return original
        prompt = build_prompt(query, texts)
        client = get_llm_client()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return validate_ranking(parse_model(client.complete(prompt, json_mode=True), RerankReply), len(texts))
            except LLMResponseError as exc:
                logger.warning("Rerank reply rejected (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc)
            except Exception as exc:  # the model call itself failed
                logger.warning("Rerank call failed: %s", type(exc).__name__)
                break
        logger.error("Reranking failed. Keeping the original order.")
        return original
