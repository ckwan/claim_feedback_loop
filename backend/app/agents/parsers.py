"""
Parsing and validation for raw LLM output.

The principle this file exists to demonstrate: an LLM response is untrusted
input, exactly like a user's form submission, and gets validated at the
boundary before anything downstream (auto-approving a claim, persisting a
Suggestion row) trusts it.
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class SuggestionResult(BaseModel):
    suggested_action: str = Field(pattern="^(under_review|approved|denied)$")
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


class LLMResponseError(Exception):
    """Raised when the LLM's response can't be parsed into a trusted result."""


def parse_suggestion_response(raw: str) -> SuggestionResult:
    """
    Turns raw LLM text into a validated SuggestionResult, or raises
    LLMResponseError. Two distinct failure modes are handled explicitly
    rather than left to bubble up as an unhandled exception:
      1. The text isn't valid JSON at all (model rambled, wrapped it in
         markdown, etc).
      2. It's valid JSON but doesn't match the schema we need (wrong type,
         missing field, confidence out of bounds, a made-up action string).
    """
    try:
        data = json.loads(_strip_markdown_fences(raw))
    except json.JSONDecodeError as exc:
        logger.warning("LLM response was not valid JSON: %r", raw[:200])
        raise LLMResponseError(f"Non-JSON LLM response: {exc}") from exc

    try:
        return SuggestionResult.model_validate(data)
    except ValidationError as exc:
        logger.warning("LLM response failed schema validation: %r", data)
        raise LLMResponseError(f"LLM response failed validation: {exc}") from exc


def _strip_markdown_fences(raw: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` even when told not to."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
    return text.strip()


def parse_model(raw: str, model_cls):
    """Validate raw model text against any Pydantic model. Raises LLMResponseError."""
    try:
        data = json.loads(_strip_markdown_fences(raw))
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"Non-JSON LLM response: {exc}") from exc
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        # Locations and error types only. The input may hold claim text.
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors())
        raise LLMResponseError(f"LLM response failed validation: {problems}") from exc
