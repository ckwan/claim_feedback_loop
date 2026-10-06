import json
import logging
import os

from pydantic import BaseModel, Field, ValidationError

from app import models, schemas
from app.agents.llm_client import get_llm_client


logger = logging.getLogger(__name__)


MODEL_VERSION = os.getenv("OLLAMA_MODEL", os.getenv("LLM_MODEL", "llama3.2"))


class SuggestionResponse(BaseModel):
	"""The only shape accepted from an LLM suggestion response."""

	action: str
	rationale: str
	confidence: float = Field(ge=0.0, le=1.0)


def generate_suggestion_stub(claim: models.Claim) -> tuple[str, str, float]:
	"""Return a deterministic suggestion when an LLM is unavailable."""
	if claim.status == models.ClaimStatus.OPEN:
		return (
			"under_review",
			"New claim with no prior review; route to an adjuster.",
			0.72,
		)

	if claim.status == models.ClaimStatus.UNDER_REVIEW:
		return (
			"approved" if claim.amount < 5000 else "under_review",
			"Low claim amount and no flags in history notes."
			if claim.amount < 5000
			else "High claim amount; recommend continued manual review.",
			0.55,
		)
	return ("no_action", "Claim is already in a terminal state.", 0.9)


def _suggestion_prompt(claim: models.Claim, recent_corrections: str = "") -> str:
	corrections_context = (
		f"\n{recent_corrections}\n"
		"Use these recent corrections as examples when recommending an action.\n"
		if recent_corrections
		else ""
	)
	return f"""You are reviewing an insurance claim and recommending the next action.

Claim status: {claim.status.value}
Claim amount: {claim.amount}
History notes: {claim.history_notes or "None"}

{corrections_context}
Return only valid JSON with exactly these keys:
{{"action": string, "rationale": string, "confidence": number}}
Confidence must be a number from 0 to 1.
"""


def _call_llm(prompt: str) -> str | None:
	return get_llm_client().complete(prompt, json_mode=True)


def generate_suggestion(
	claim: models.Claim, recent_corrections: str = ""
) -> tuple[str, str, float]:
	"""Generate a validated LLM suggestion, retrying malformed responses once."""
	prompt = _suggestion_prompt(claim, recent_corrections)
	for attempt in range(2):
		try:
			raw_response = _call_llm(prompt)
			logger.debug("LLM suggestion response (attempt %s): %r", attempt + 1, raw_response)
			if not raw_response:
				raise ValueError("LLM returned no response")
			parsed = SuggestionResponse.model_validate(json.loads(raw_response))
			return parsed.action, parsed.rationale, parsed.confidence
		except (ValueError, TypeError, json.JSONDecodeError, ValidationError) as exc:
			logger.warning("Could not parse LLM suggestion on attempt %s: %s", attempt + 1, exc)
		except Exception as exc:
			logger.warning("LLM suggestion failed on attempt %s: %s", attempt + 1, exc)

	action, rationale, _ = generate_suggestion_stub(claim)
	return action, f"LLM fallback used after invalid responses: {rationale}", 0.0


def summarize_claim_history(claim: models.Claim) -> schemas.ClaimHistorySummaryOut:
	"""Summarize claim history and return general, non-diagnostic next steps."""
	notes = claim.history_notes or "No history notes are available."
	# Production RAG should chunk and embed notes, then retrieve top-k relevant
	# chunks instead of sending the entire history field as context.
	prompt = f"""Summarize the following insurance claim history and suggest general next steps.

Base the response only on the notes. Do not diagnose, prescribe treatment, or
invent medical facts. Keep recommendations general and advise consulting a
qualified healthcare professional for medical decisions.

Claim history notes:
{notes}

Return only valid JSON with exactly these keys:
{{"summary": string, "suggested_next_steps": [string, ...]}}
"""
	for attempt in range(2):
		try:
			raw_response = _call_llm(prompt)
			logger.debug("Claim history summary response (attempt %s): %r", attempt + 1, raw_response)
			if not raw_response:
				raise ValueError("LLM returned no response")
			return schemas.ClaimHistorySummaryOut.model_validate(json.loads(raw_response))
		except (ValueError, TypeError, json.JSONDecodeError, ValidationError) as exc:
			logger.warning("Could not parse claim history summary on attempt %s: %s", attempt + 1, exc)
		except Exception as exc:
			logger.warning("Claim history summary failed on attempt %s: %s", attempt + 1, exc)

	raise ValueError("LLM could not return a valid claim history summary after two attempts")
