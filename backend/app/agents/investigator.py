"""A ReAct agent that investigates a claim.

ReAct means Reason and Act. The model does not answer in one shot. It loops:

    think  -> picks a tool and says why        (the model)
    act    -> the tool runs and returns facts  (our code)
    think  -> reads the result and decides again
    ...    -> until it calls "finish" with an answer

The difference from the fixed pipelines elsewhere in this project (appeal_graph.py,
and the review graph in NoteLoop) is who decides the next step. There the code always
runs the same steps in the same order. Here the model chooses, which is more flexible
and needs more guarding. The guards:

  * Tools are an allowlist. An unknown tool name is rejected.
  * org_id is bound into every tool when the agent is built. The model cannot pass
    one, and an "org_id" argument is rejected by schema, so it cannot reach another
    tenant. Asking for another tenant's claim id just returns "not found".
  * The loop has a step cap, and stops on a repeated identical action.
  * Tool results hold text written by other people, so they go back to the model
    inside tagged blocks, with tags neutralized.
  * The final answer may only cite claim ids that a tool actually returned.
  * The agent only reads. No tool changes a claim.

The loop is a LangGraph graph so the steps show up as a trace in LangSmith.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.agents.llm_client import get_llm_client, traceable
from app.agents.parsers import LLMResponseError, parse_model
from app.agents.prompts import _recent_overrides_for_org
from app.rag.retriever import SearchUnavailable, retrieve
from app.safety import UNTRUSTED_NOTICE, clean_text, neutralize_tags, wrap_untrusted

logger = logging.getLogger(__name__)

MAX_STEPS = 5
DEFAULT_QUESTION = "What should the adjuster know before deciding on this claim?"
OBSERVATION_CHARS = 1200


# --- what the model may ask for ----------------------------------------------------


class _Args(BaseModel):
    # Unknown arguments, including "org_id", are errors rather than ignored.
    model_config = ConfigDict(extra="forbid")


class SearchArgs(_Args):
    query: str = Field(min_length=2, max_length=300)
    top_k: int = Field(default=3, ge=1, le=5)


class GetClaimArgs(_Args):
    claim_id: str = Field(min_length=1, max_length=64)


class OverrideArgs(_Args):
    limit: int = Field(default=3, ge=1, le=5)


class NoArgs(_Args):
    pass


class FinishArgs(_Args):
    answer: str = Field(min_length=1, max_length=1500)
    cited_claim_ids: list[str] = Field(default_factory=list, max_length=10)


class StepReply(BaseModel):
    thought: str = Field(default="", max_length=600)
    action: str
    args: dict = Field(default_factory=dict)


class Tool:
    def __init__(self, name: str, description: str, args: type[_Args], fn: Callable[..., str]):
        self.name, self.description, self.args, self.fn = name, description, args, fn


def build_tools(db: Session, org_id: str, claim: models.Claim) -> dict[str, Tool]:
    """The tools, with the organization fixed. Nothing here reads org_id from the model."""

    def search_similar_claims(a: SearchArgs) -> str:
        try:
            found = retrieve(db, org_id, a.query, top_k=a.top_k, exclude_claim_id=claim.id)
        except SearchUnavailable:
            return "Search is not available in this environment."
        if not found.hits:
            return "No similar claims found."
        return "\n".join(
            f"claim_id={h.claim_id} amount={h.amount:.0f} status={h.status} notes: {h.snippet}"
            for h in found.hits
        )

    def get_claim(a: GetClaimArgs) -> str:
        row = db.execute(
            select(models.Claim).where(models.Claim.id == a.claim_id, models.Claim.org_id == org_id)
        ).scalar_one_or_none()
        if row is None:
            return "No claim with that id in this organization."
        return (f"claim_id={row.id} amount={row.amount:.0f} status={row.status.value} "
                f"notes: {row.history_notes or 'none'}")

    def get_override_examples(a: OverrideArgs) -> str:
        rows = _recent_overrides_for_org(db, org_id, a.limit)
        if not rows:
            return "No adjuster overrides recorded yet."
        return "\n".join(
            f"claim_id={c.id} amount={c.amount:.0f}: AI suggested {s.suggested_action}, "
            f"adjuster chose {f.final_action} because: {f.override_reason}"
            for c, s, f in rows
        )

    def get_override_rate(_: NoArgs) -> str:
        rows = (db.query(models.Feedback).join(models.Suggestion).join(models.Claim)
                .filter(models.Claim.org_id == org_id).all())
        if not rows:
            return "No adjuster feedback recorded yet."
        over = sum(1 for r in rows if r.action_taken == models.FeedbackAction.OVERRIDDEN)
        return f"{over} of {len(rows)} AI suggestions were overridden ({over / len(rows):.0%})."

    tools = [
        Tool("search_similar_claims", "Find similar past claims in this organization. Args: query (text), top_k (1-5, optional).", SearchArgs, search_similar_claims),
        Tool("get_claim", "Read one claim in this organization by id. Args: claim_id.", GetClaimArgs, get_claim),
        Tool("get_override_examples", "Recent cases where an adjuster overrode the AI, with reasons. Args: limit (1-5, optional).", OverrideArgs, get_override_examples),
        Tool("get_override_rate", "How often adjusters here override the AI. No args.", NoArgs, get_override_rate),
    ]
    return {t.name: t for t in tools}


# --- the loop ----------------------------------------------------------------------


class State(TypedDict, total=False):
    question: str
    steps: list[dict]
    seen_ids: list[str]
    stopped_because: str
    answer: str
    cited: list[str]


def _prompt(claim: models.Claim, tools: dict[str, Tool], state: State) -> str:
    tool_lines = "\n".join(f"- {t.name}: {t.description}" for t in tools.values())
    lines = [
        "You are a ReAct investigator helping an insurance adjuster. Work in steps. "
        "Each reply is ONE JSON object and nothing else: "
        '{"thought": "<short reason>", "action": "<tool name>", "args": {...}}.',
        f"Tools:\n{tool_lines}\n- finish: Give the final answer. "
        "Args: answer (text), cited_claim_ids (list of claim ids your answer relies on, from tool results only).",
        "You only read information. You cannot change a claim. " + UNTRUSTED_NOTICE,
        f"Claim under investigation: {claim.id}",
        f"Amount: {claim.amount:.0f}  Status: {claim.status.value}",
        wrap_untrusted("history", claim.history_notes or "none"),
        f"Question: {state['question']}",
    ]
    for step in state.get("steps", []):
        n = step["step"]
        lines.append(f"Thought {n}: {step['thought']}")
        lines.append(f"Action {n}: {step['action']} {json.dumps(step['args'], sort_keys=True)}")
        lines.append(f"Observation {n}:")
        lines.append(wrap_untrusted("observation", step["observation"], OBSERVATION_CHARS))
    return "\n".join(lines)


def _ids_in(text: str) -> list[str]:
    return re.findall(r"claim_id=([\w-]+)", text)


def build_graph(db: Session, claim: models.Claim, max_steps: int = MAX_STEPS):
    tools = build_tools(db, claim.org_id, claim)
    client = get_llm_client()

    def think(state: State) -> dict:
        prompt = _prompt(claim, tools, state)
        reply = None
        for _attempt in range(2):
            try:
                reply = parse_model(client.complete(prompt, json_mode=True), StepReply)
                break
            except LLMResponseError as exc:
                logger.warning("Investigator reply rejected: %s", exc)
            except Exception as exc:
                logger.warning("Investigator model call failed: %s", type(exc).__name__)
                break
        steps = list(state.get("steps", []))
        n = len(steps) + 1
        if reply is None:
            return {"stopped_because": "error",
                    "answer": "The model did not return a usable step, so the investigation stopped."}

        if reply.action == "finish":
            try:
                fin = FinishArgs.model_validate(reply.args)
            except ValidationError:
                return {"stopped_because": "error", "answer": "The final answer was malformed."}
            known = set(state.get("seen_ids", [])) | {claim.id}
            cited = [c for c in dict.fromkeys(fin.cited_claim_ids) if c in known and c != claim.id]
            return {"stopped_because": "finished",
                    "answer": neutralize_tags(clean_text(fin.answer, 1500)), "cited": cited}

        tool = tools.get(reply.action)
        if tool is None:
            observation = f"Unknown tool '{clean_text(reply.action, 40)}'. Use one of: {', '.join(tools)}, finish."
            args = {}
        else:
            try:
                args = tool.args.model_validate(reply.args).model_dump()
            except ValidationError as exc:
                problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors())
                observation, args = f"Invalid arguments: {problems}", {}
            else:
                key = (reply.action, json.dumps(args, sort_keys=True))
                if any((s["action"], json.dumps(s["args"], sort_keys=True)) == key for s in steps):
                    return {"stopped_because": "repeated_action",
                            "answer": "The investigation stopped because the same step was repeated."}
                observation = tool.fn(tool.args(**args))
        steps.append({"step": n, "thought": clean_text(reply.thought, 600), "action": reply.action,
                      "args": args, "observation": observation})
        seen = list(state.get("seen_ids", [])) + _ids_in(observation)
        if len(steps) >= max_steps:
            return {"steps": steps, "seen_ids": seen, "stopped_because": "step_limit",
                    "answer": f"The investigation reached its limit of {max_steps} steps without a final answer."}
        return {"steps": steps, "seen_ids": seen}

    def route(state: State) -> str:
        return END if state.get("stopped_because") else "think"

    graph = StateGraph(State)
    graph.add_node("think", think)
    graph.set_entry_point("think")
    graph.add_conditional_edges("think", route, {"think": "think", END: END})
    return graph.compile()


@traceable(name="claim_investigator", run_type="chain")
def investigate(db: Session, claim: models.Claim, question: str | None = None,
                max_steps: int = MAX_STEPS) -> dict:
    state: State = {"question": clean_text(question or DEFAULT_QUESTION, 300), "steps": [], "seen_ids": []}
    final = build_graph(db, claim, max_steps).invoke(state, {"recursion_limit": max_steps * 2 + 5})
    return {
        "claim_id": claim.id,
        "answer": final.get("answer", ""),
        "cited_claim_ids": final.get("cited", []),
        "steps": [{**s, "observation": clean_text(s["observation"], 600)} for s in final.get("steps", [])],
        "stopped_because": final.get("stopped_because", "error"),
    }
