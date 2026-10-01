import json
import logging
import os

from pydantic import BaseModel, Field, ValidationError

from app import models


logger = logging.getLogger(__name__)


MODEL_VERSION = os.getenv("LLM_MODEL", "llm-suggestion-v1")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "10"))


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


def _suggestion_prompt(claim: models.Claim) -> str:
	return f"""You are reviewing an insurance claim and recommending the next action.

Claim status: {claim.status.value}
Claim amount: {claim.amount}
History notes: {claim.history_notes or "None"}

Return only valid JSON with exactly these keys:
{{"action": string, "rationale": string, "confidence": number}}
Confidence must be a number from 0 to 1.
"""


def _call_openai(prompt: str) -> str | None:
	if not os.getenv("OPENAI_API_KEY"):
		return None
	try:
		from openai import OpenAI
	except ImportError:
		return None

	client = OpenAI(timeout=LLM_TIMEOUT_SECONDS)
	response = client.chat.completions.create(
		model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
		messages=[{"role": "user", "content": prompt}],
		response_format={"type": "json_object"},
		timeout=LLM_TIMEOUT_SECONDS,
	)
	return response.choices[0].message.content


def _call_anthropic(prompt: str) -> str | None:
	if not os.getenv("ANTHROPIC_API_KEY"):
		return None
	try:
		from anthropic import Anthropic
	except ImportError:
		return None

	client = Anthropic(timeout=LLM_TIMEOUT_SECONDS)
	message = client.messages.create(
		model=os.getenv("LLM_MODEL", "claude-3-5-haiku-latest"),
		max_tokens=300,
		messages=[{"role": "user", "content": prompt}],
		timeout=LLM_TIMEOUT_SECONDS,
	)
	return next((block.text for block in message.content if block.type == "text"), None)


def _call_llm(prompt: str) -> str | None:
	return _call_openai(prompt) or _call_anthropic(prompt)


def generate_suggestion(claim: models.Claim) -> tuple[str, str, float]:
	"""Generate a validated LLM suggestion, retrying malformed responses once."""
	prompt = _suggestion_prompt(claim)
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
