"""
LangGraph version of the denial-appeal pipeline.

This is the thing the baseline in denial_appeal.py was built to be compared
against. Same three model-facing steps (reason, draft, validate), same
AppealCase input, same AppealResult shape out - the only difference is the
edge between validate and draft: here it's a conditional edge that routes
back to re-draft when validation fails, instead of just reporting the
failure and stopping.

Why this is the whole point of using LangGraph instead of three function
calls: the baseline has no way to act on a validation failure except give
up. This graph can retry, up to MAX_RETRIES times, each time re-drafting
with the specific validation errors fed back into the prompt - so a retry
isn't "ask the same question again," it's "ask again, and here's what was
wrong last time."

State is a flat TypedDict rather than a Pydantic model because LangGraph
nodes return partial-state dicts that get merged in; the state itself
doesn't need field validation (the pydantic models built in denial_appeal.py
still validate every model response, same as the baseline).
"""
from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agents.denial_appeal import (
    AppealCase,
    AppealResult,
    ReasoningResult,
    draft_letter,
    reason_about_case,
    validate_draft,
)
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.parsers import LLMResponseError

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


class AppealState(TypedDict, total=False):
    case: AppealCase
    client: LLMClient
    reasoning: ReasoningResult | None
    draft: str | None
    validation_passed: bool
    validation_errors: list[str]
    retry_count: int
    error: str | None


def reason_node(state: AppealState) -> dict:
    case = state["case"]
    try:
        reasoning = reason_about_case(case, state["client"])
    except LLMResponseError as exc:
        logger.warning("Reasoning step failed for %s: %s", case.claim_id, exc)
        return {"error": f"reasoning_failed: {exc}"}
    return {"reasoning": reasoning}


def draft_node(state: AppealState) -> dict:
    """
    Drafts (or re-drafts) the letter. On a retry, the validation errors from
    the previous attempt are appended to the prompt context, which is the
    part the baseline structurally can't do - it never loops back here.
    """
    case = state["case"]
    reasoning = state["reasoning"]
    retry_count = state.get("retry_count", 0)
    prior_errors = state.get("validation_errors", [])

    if retry_count == 0 or not prior_errors:
        draft = draft_letter(case, reasoning, state["client"])
    else:
        # Re-draft with explicit feedback about what failed last time.
        feedback = "\n".join(f"- {e}" for e in prior_errors)
        retry_prompt = (
            "Write a formal insurance claim appeal letter on behalf of the policyholder. "
            "Cite the specific policy section where relevant. Keep it to 3-4 short paragraphs. "
            "Return only the letter text, no preamble.\n\n"
            f"Policyholder: {case.policyholder_name}\n"
            f"Claim ID: {case.claim_id}\n"
            f"Denial reason: {case.denial_reason}\n"
            f"Policy excerpt: {case.policy_excerpt}\n"
            f"Claim facts: {case.claim_facts}\n"
            f"Strongest ground for appeal: {reasoning.strongest_ground}\n\n"
            "Your previous draft had these problems - fix them in this version:\n"
            f"{feedback}"
        )
        draft = state["client"].complete(retry_prompt).strip()

    return {"draft": draft, "retry_count": retry_count + 1}


def validate_node(state: AppealState) -> dict:
    case = state["case"]
    draft = state["draft"]
    passed, errors = validate_draft(case, draft)
    return {"validation_passed": passed, "validation_errors": errors}


def route_after_reasoning(state: AppealState) -> str:
    if state.get("error"):
        return "end"
    if not state["reasoning"].should_appeal:
        return "end"
    return "draft"


def route_after_validation(state: AppealState) -> str:
    """
    retry_count is the number of drafts written so far (set by draft_node
    after each attempt). MAX_RETRIES=2 means "retry up to 2 times," i.e.
    allow up to 1 initial draft + 2 retries = 3 draft attempts total before
    giving up, so the cutoff is retry_count >= MAX_RETRIES + 1.
    """
    if state["validation_passed"]:
        return "end"
    if state.get("retry_count", 0) >= MAX_RETRIES + 1:
        return "end"
    return "retry"


def build_appeal_graph():
    graph = StateGraph(AppealState)

    graph.add_node("reason", reason_node)
    graph.add_node("draft", draft_node)
    graph.add_node("validate", validate_node)

    graph.set_entry_point("reason")

    graph.add_conditional_edges(
        "reason",
        route_after_reasoning,
        {"draft": "draft", "end": END},
    )
    graph.add_edge("draft", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {"retry": "draft", "end": END},
    )

    return graph.compile()


_compiled_graph = None


def run_langgraph_appeal(case: AppealCase, client: LLMClient | None = None) -> AppealResult:
    """
    Same signature and return shape as run_baseline_appeal() in
    denial_appeal.py, so the eval script can run either pipeline over the
    same cases and compare results directly.
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_appeal_graph()

    client = client or get_llm_client()
    initial_state: AppealState = {"case": case, "client": client, "retry_count": 0}

    final_state = _compiled_graph.invoke(initial_state)

    return AppealResult(
        claim_id=case.claim_id,
        reasoning=final_state.get("reasoning"),
        draft_letter=final_state.get("draft"),
        validation_passed=final_state.get("validation_passed", True),
        validation_errors=final_state.get("validation_errors", []),
        error=final_state.get("error"),
    )
