"""
Thin wrapper around the local Ollama HTTP API, so the rest of the app
does not depend on a provider SDK.

Why this file exists at all: `suggestion_service.py` should depend on "give
me a completion for this prompt," not on a specific vendor's client object
or request shape. If we ever swap providers, or add retries/timeouts/
logging in one place, this is the only file that changes.

Ollama runs outside the application container. Configure OLLAMA_BASE_URL,
OLLAMA_MODEL, and OLLAMA_TIMEOUT_SECONDS for the local model server.
"""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", os.getenv("LLM_MODEL", "llama3.2"))
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))


class LLMClient:
    """Minimal interface: give it a prompt, get back raw text."""

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        raise NotImplementedError


class StubLLMClient(LLMClient):
    """
    Deterministic, offline stand-in. Mimics a provider response closely
    enough (raw JSON text) that the parser downstream can't tell the
    difference — the same code path runs whether this stub or a real
    provider is wired in.
    """

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
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

        # A tiny bit of "reasoning": lower amount -> lower risk, mirrors the
        # Day 1 rule-based stub's behavior so Day 2 doesn't regress it.
        amount = _extract_amount(prompt)
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
                "suggested_action": "under_review",
                "rationale": "Claim amount or history warrants manual adjuster review.",
                "confidence": 0.6,
            }
        )


class OllamaLLMClient(LLMClient):
    """Client for a local Ollama server using its generate endpoint."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
        timeout: float = OLLAMA_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        request = Request(
            f"{self._base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self._timeout) as response:
            result = json.loads(response.read().decode("utf-8"))

        completion = result.get("response")
        if not isinstance(completion, str):
            raise ValueError("Ollama response did not include generated text")
        return completion


def _extract_amount(prompt: str) -> float | None:
    import re

    match = re.search(r"Amount requested:\s*([\d.]+)", prompt)
    return float(match.group(1)) if match else None


def get_llm_client() -> LLMClient:
    """Return the configured local Ollama client."""
    return OllamaLLMClient()
