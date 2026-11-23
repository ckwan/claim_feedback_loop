"""
Baseline (non-LangGraph) denial-appeal agent: four sequential LLM calls,
plain Python, no graph, no state machine, no retry loop.

This exists on purpose as the thing to beat. Week 3 builds the same four
steps as LangGraph nodes with conditional routing and a retry loop when
validation fails; without this file, there's nothing to compare that
against, and "I used LangGraph" has no measured justification.

Pipeline: retrieve -> reason -> draft -> validate.
  1. retrieve_policy   - in this baseline, the policy excerpt is already on
                          the case (Week 3's RAG retrieval step gets a real
                          lookup; here we skip straight to "assume retrieval
                          succeeded" so this step isolates the other three).
  2. reason_about_case  - should this denial actually be appealed, given the
                          facts vs. the policy excerpt? LLM call #1.
  3. draft_letter       - write the appeal letter. LLM call #2.
  4. validate_draft     - cheap deterministic checks only (no LLM call) -
                          non-empty, cites a real policy section, isn't
                          absurdly short. This baseline does NOT retry on a
                          validation failure; it just reports the failure.
                          That's the specific gap LangGraph's retry loop is
                          meant to close.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.parsers import LLMResponseError, _strip_markdown_fences

logger = logging.getLogger(__name__)


class ReasoningResult(BaseModel):
    should_appeal: bool
    strongest_ground: str = Field(description="One sentence: the strongest ground for appeal, or why there isn't one.")
    confidence: float = Field(ge=0.0, le=1.0)


class AppealCase(BaseModel):
    """Mirrors one entry of data/synthetic_denial_cases.json."""

    claim_id: str
    org_id: str
    policyholder_name: str
    policy_type: str
    claim_amount: float
    claim_facts: str
    denial_reason: str
    denial_code: str
    policy_excerpt: str


@dataclass
class AppealResult:
    claim_id: str
    reasoning: ReasoningResult | None
    draft_letter: str | None
    validation_passed: bool
    validation_errors: list[str]
    error: str | None = None


REASONING_INSTRUCTIONS = """You are an insurance claims specialist evaluating whether a denied claim \
should be appealed. Respond with a single JSON object and nothing else, with exactly \
these keys: "should_appeal" (true or false), "strongest_ground" (one sentence), \
and "confidence" (a float between 0 and 1)."""


def _build_reasoning_prompt(case: AppealCase) -> str:
    return (
        f"{REASONING_INSTRUCTIONS}\n\n"
        f"Policy excerpt the denial is based on:\n{case.policy_excerpt}\n\n"
        f"Denial reason given: {case.denial_reason}\n\n"
        f"Claim facts:\n{case.claim_facts}\n\n"
        "Now evaluate this case:"
    )


def _build_draft_prompt(case: AppealCase, reasoning: ReasoningResult) -> str:
    return (
        "Write a formal insurance claim appeal letter on behalf of the policyholder. "
        "Cite the specific policy section where relevant. Keep it to 3-4 short paragraphs. "
        "Return only the letter text, no preamble.\n\n"
        f"Policyholder: {case.policyholder_name}\n"
        f"Claim ID: {case.claim_id}\n"
        f"Denial reason: {case.denial_reason}\n"
        f"Policy excerpt: {case.policy_excerpt}\n"
        f"Claim facts: {case.claim_facts}\n"
        f"Strongest ground for appeal: {reasoning.strongest_ground}\n"
    )


def reason_about_case(case: AppealCase, client: LLMClient) -> ReasoningResult:
    raw = client.complete(_build_reasoning_prompt(case))
    try:
        data = json.loads(_strip_markdown_fences(raw))
        return ReasoningResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMResponseError(f"Reasoning step failed to parse: {exc}\nRaw: {raw[:300]}") from exc


def draft_letter(case: AppealCase, reasoning: ReasoningResult, client: LLMClient) -> str:
    raw = client.complete(_build_draft_prompt(case, reasoning))
    return raw.strip()


def validate_draft(case: AppealCase, draft: str) -> tuple[bool, list[str]]:
    """
    Deterministic only, on purpose: this baseline's "validate" step is meant
    to be cheap and dumb, so any failure it catches is a case where the
    fix is "try again," not "write a smarter validator." That's exactly the
    gap a LangGraph retry loop is for.
    """
    errors = []

    if len(draft) < 150:
        errors.append(f"Draft too short ({len(draft)} chars, expected >= 150).")

    policy_section = case.policy_excerpt.split(":")[0].split("(")[0].strip()
    if policy_section and policy_section.lower() not in draft.lower():
        errors.append(f"Draft does not mention the cited policy section ('{policy_section}').")

    if "{" in draft or "[insert" in draft.lower() or "placeholder" in draft.lower():
        errors.append("Draft appears to contain template placeholder text.")

    return (len(errors) == 0, errors)


def run_baseline_appeal(case: AppealCase, client: LLMClient | None = None) -> AppealResult:
    """The full baseline pipeline for one case. No retries, no branching."""
    client = client or get_llm_client()

    try:
        reasoning = reason_about_case(case, client)
    except LLMResponseError as exc:
        logger.warning("Reasoning step failed for %s: %s", case.claim_id, exc)
        return AppealResult(
            claim_id=case.claim_id,
            reasoning=None,
            draft_letter=None,
            validation_passed=False,
            validation_errors=[],
            error=f"reasoning_failed: {exc}",
        )

    if not reasoning.should_appeal:
        return AppealResult(
            claim_id=case.claim_id,
            reasoning=reasoning,
            draft_letter=None,
            validation_passed=True,
            validation_errors=[],
        )

    draft = draft_letter(case, reasoning, client)
    passed, errors = validate_draft(case, draft)

    return AppealResult(
        claim_id=case.claim_id,
        reasoning=reasoning,
        draft_letter=draft,
        validation_passed=passed,
        validation_errors=errors,
    )
