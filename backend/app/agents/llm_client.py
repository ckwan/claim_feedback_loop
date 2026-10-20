"""
Thin wrapper around whatever LLM provider we call, so the rest of the app
never imports an SDK (anthropic/openai) directly.

Why this file exists at all: `suggestion_service.py` should depend on "give
me a completion for this prompt," not on a specific vendor's client object
or request shape. If we ever swap providers, or add retries/timeouts/
logging in one place, this is the only file that changes.

No API key configured -> falls back to a deterministic stub so the rest of
the pipeline (prompt building, parsing, few-shot context, the FastAPI
endpoints) is fully runnable and testable with zero setup. This mirrors the
project's "runs with zero setup" philosophy from Day 1.

LangSmith tracing: every `complete()` call is wrapped with `@traceable`, so
once LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY are set in the
environment, every LLM call — stub or real — shows up in LangSmith with its
prompt, output, and latency, with zero code changes at the call site. If the
`langsmith` package isn't installed, or those env vars aren't set, this is a
true no-op: `traceable` degrades to a plain passthrough, so nothing about
local dev without LangSmith changes.
"""
from __future__ import annotations

import json
import os

try:
    from langsmith import traceable
except ImportError:  # langsmith not installed -> tracing is a no-op

    def traceable(*, name: str | None = None, run_type: str = "llm"):
        def decorator(func):
            return func

        return decorator


class LLMClient:
    """Minimal interface: give it a prompt, get back raw text."""

    def complete(self, prompt: str) -> str:
        raise NotImplementedError


class StubLLMClient(LLMClient):
    """
    Deterministic, offline stand-in. Mimics a provider response closely
    enough (raw JSON text) that the parser downstream can't tell the
    difference — the same code path runs whether this stub or a real
    provider is wired in.
    """

    @traceable(name="stub_llm_complete", run_type="llm")
    def complete(self, prompt: str) -> str:
        # The suggestion-scoring prompt and the RAG history-summary prompt
        # both route through this one offline stub. Branch on a marker
        # unique to the scoring prompt (see prompts.py) so the stub returns
        # the right *shape* of response for whichever caller invoked it —
        # structured JSON for scoring, plain text for a summary.
        if "Now score this claim" not in prompt:
            return (
                "Based on similar prior claims in this org's history, comparable "
                "claims of this type and amount have typically been approved after "
                "standard review, with no notable risk flags recorded."
            )

        # Status-aware, mirroring the claim state machine's VALID_TRANSITIONS
        # (app/models.py) so this stub never suggests an action that would
        # be an illegal transition for the claim's current status:
        #   open          -> under_review is the only legal next step
        #   under_review  -> approved or denied (NOT "under_review" again)
        #   approved/denied (terminal) -> no_action
        amount = _extract_amount(prompt)
        status = _extract_status(prompt)

        if status == "open":
            return json.dumps(
                {
                    "suggested_action": "under_review",
                    "rationale": "New claim with no prior review; route to an adjuster.",
                    "confidence": 0.7,
                }
            )

        if status == "under_review":
            if amount is not None and amount < 1000:
                return json.dumps(
                    {
                        "suggested_action": "approved",
                        "rationale": "Low claim amount and no risk flags in the provided history.",
                        "confidence": 0.8,
                    }
                )
            return json.dumps(
                {
                    "suggested_action": "denied",
                    "rationale": "High claim amount with no mitigating history notes on file.",
                    "confidence": 0.55,
                }
            )

        # approved / denied / unrecognized status: nothing left to suggest.
        return json.dumps(
            {
                "suggested_action": "no_action",
                "rationale": "Claim is already in a terminal state.",
                "confidence": 0.9,
            }
        )


class OllamaLLMClient(LLMClient):
    """
    Local, free model via Ollama's HTTP API (http://localhost:11434 by
    default). This is what the Week 2 eval runs against — no API key, no
    per-token cost, works with any model you've pulled (`ollama pull
    qwen2.5:7b`, `ollama pull qwen2.5:14b`, etc).

    Requires the Ollama daemon running locally (`ollama serve`, or it's
    already running if you installed the desktop app) and the model already
    pulled. This client does NOT pull models for you — a missing model
    fails fast with Ollama's own error message rather than silently
    downloading gigabytes mid-eval-run.
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        import httpx  # already a project dependency (app's own test client)

        self._model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self._base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout)

    @traceable(name="ollama_llm_complete", run_type="llm")
    def complete(self, prompt: str) -> str:
        response = self._client.post(
            "/api/generate",
            json={"model": self._model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return response.json()["response"]


class AnthropicLLMClient(LLMClient):
    """
    Real provider. Imports the SDK lazily so a missing dependency or API key
    never breaks the stub path used in tests/local dev.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        import anthropic  # local import: optional dependency

        self._client = anthropic.Anthropic()
        self._model = model

    @traceable(name="anthropic_llm_complete", run_type="llm")
    def complete(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text


def _extract_amount(prompt: str) -> float | None:
    import re

    match = re.search(r"Amount requested:\s*([\d.]+)", prompt)
    return float(match.group(1)) if match else None


def _extract_status(prompt: str) -> str | None:
    import re

    match = re.search(r"Current status:\s*(\w+)", prompt)
    return match.group(1) if match else None


def get_llm_client() -> LLMClient:
    """
    Single place that decides which client the rest of the app gets.

    Priority: LLM_PROVIDER env var wins if set ("ollama" | "anthropic" |
    "stub"). Otherwise: ANTHROPIC_API_KEY set -> real paid client; OLLAMA_MODEL
    set -> free local client; else -> offline stub.

    The eval harness (scripts/run_baseline_eval.py) sets LLM_PROVIDER=ollama
    explicitly so a stray ANTHROPIC_API_KEY in your shell env never causes a
    paid call mid-eval.
    """
    provider = os.getenv("LLM_PROVIDER")
    if provider == "ollama":
        return OllamaLLMClient()
    if provider == "anthropic":
        return AnthropicLLMClient()
    if provider == "stub":
        return StubLLMClient()

    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicLLMClient()
    if os.getenv("OLLAMA_MODEL"):
        return OllamaLLMClient()
    return StubLLMClient()
