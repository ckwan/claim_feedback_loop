"""
Week 2/3 eval: runs the baseline (non-LangGraph) denial-appeal agent AND
the LangGraph version (app/agents/appeal_graph.py) over the same
hand-labeled cases, scores each against your labels, and prints them side
by side. Free local models only, through Ollama (no Anthropic API key, no
per-token cost).

This is the actual point of building the LangGraph version at all: without
this comparison, "I used LangGraph" has no evidence behind it. With it, you
can say exactly what changed - specifically, how many drafts that failed
validation under the baseline got fixed by the retry loop.

Setup (one-time, on your machine - this can't run inside the sandbox this
was built in, since it needs a local Ollama daemon and a pulled model):
    1. Install Ollama: https://ollama.com
    2. Pull a free model, e.g.:
         ollama pull qwen2.5:7b
       (qwen2.5:14b if your machine can handle it - better reasoning,
       slower; qwen2.5:7b is the practical default for a laptop)
    3. Make sure the daemon is running (it auto-starts after install, or
       run `ollama serve`).
    4. Hand-label some cases:
         python scripts/make_labels_template.py
         # edit data/eval_labels.json: set should_appeal true/false and
         # strongest_ground for 30-50 of the 60 cases
    5. Run the eval (runs both pipelines by default):
         LLM_PROVIDER=ollama OLLAMA_MODEL=qwen2.5:7b python scripts/run_baseline_eval.py
       To run only one pipeline:
         ... python scripts/run_baseline_eval.py --only baseline
         ... python scripts/run_baseline_eval.py --only langgraph

What it checks, per labeled case, per pipeline:
  - Deterministic: did the agent's draft (when it drafted one) pass
    validate_draft() - non-empty, cites the real policy section, no
    leftover placeholder text?
  - Agreement: does the agent's should_appeal match your hand label?
  - Agent-only checks don't need an LLM judge here because should_appeal
    is a binary your label already answers directly - no need to spend a
    second model call asking "is this correct," which would just add
    noise for a binary field.

Writes results to data/eval_results_baseline.json and/or
data/eval_results_langgraph.json and prints a summary for each pipeline,
plus a final comparison line.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.appeal_graph import run_langgraph_appeal  # noqa: E402
from app.agents.denial_appeal import AppealCase, run_baseline_appeal  # noqa: E402
from app.agents.llm_client import get_llm_client  # noqa: E402

CASES_PATH = ROOT / "data" / "synthetic_denial_cases.json"
LABELS_PATH = ROOT / "data" / "eval_labels.json"
RESULTS_DIR = ROOT / "data"

PIPELINES = {
    "baseline": run_baseline_appeal,
    "langgraph": run_langgraph_appeal,
}


def _require_ollama() -> None:
    """
    This eval is specifically meant to use only free models. Rather than
    silently falling back to the offline stub (which would "pass" without
    testing anything real) or a paid Anthropic call, fail loudly if
    LLM_PROVIDER isn't explicitly set to ollama.
    """
    if os.getenv("LLM_PROVIDER") != "ollama":
        sys.exit(
            "Refusing to run: set LLM_PROVIDER=ollama (and optionally "
            "OLLAMA_MODEL=qwen2.5:7b) before running this eval, so it's "
            "clear which model produced these results. Example:\n\n"
            "  LLM_PROVIDER=ollama OLLAMA_MODEL=qwen2.5:7b python scripts/run_baseline_eval.py"
        )


def run_pipeline(name: str, labeled: list[dict], cases_by_id: dict, client) -> list[dict]:
    run_fn = PIPELINES[name]
    results = []

    for i, label in enumerate(labeled, 1):
        case_data = cases_by_id.get(label["claim_id"])
        if case_data is None:
            print(f"  [{i}/{len(labeled)}] {label['claim_id']}: SKIP (not found in synthetic cases)")
            continue

        case = AppealCase(**case_data)
        print(f"  [{i}/{len(labeled)}] {case.claim_id} ({case.denial_code})...", end=" ", flush=True)

        try:
            result = run_fn(case, client)
        except Exception as exc:  # noqa: BLE001 - eval script, surface any failure per-case and keep going
            print(f"ERROR: {exc}")
            results.append({"claim_id": case.claim_id, "error": str(exc)})
            continue

        agent_said_appeal = bool(result.reasoning and result.reasoning.should_appeal)
        label_said_appeal = bool(label["should_appeal"])
        matched = agent_said_appeal == label_said_appeal

        print("MATCH" if matched else "DISAGREE")

        results.append(
            {
                "claim_id": case.claim_id,
                "denial_code": case.denial_code,
                "agent_should_appeal": agent_said_appeal,
                "agent_ground": result.reasoning.strongest_ground if result.reasoning else None,
                "label_should_appeal": label_said_appeal,
                "label_ground": label.get("strongest_ground"),
                "agreement": matched,
                "draft_letter": result.draft_letter,
                "validation_passed": result.validation_passed,
                "validation_errors": result.validation_errors,
                "error": result.error,
            }
        )

    return results


def summarize(name: str, results: list[dict], model_name: str) -> dict:
    n = len(results)
    agree = sum(1 for r in results if r.get("agreement"))
    draft_attempted = [r for r in results if r.get("draft_letter")]
    validation_pass = sum(1 for r in draft_attempted if r["validation_passed"])

    print("\n" + "=" * 60)
    print(f"Pipeline: {name}  |  Model: {model_name} (via Ollama)")
    print(f"Cases scored: {n}")
    print(f"Agreement with your labels: {agree}/{n} ({agree / n:.0%})" if n else "No cases scored.")
    if draft_attempted:
        print(
            f"Validation pass rate (when a draft was written): "
            f"{validation_pass}/{len(draft_attempted)} ({validation_pass / len(draft_attempted):.0%})"
        )

    failures = [r for r in draft_attempted if not r["validation_passed"]]
    if failures:
        label = "FAILED validation with no retry" if name == "baseline" else "still failed after retries"
        print(f"\n{len(failures)} case(s) where {name} drafted a letter that {label}:")
        for r in failures:
            print(f"  - {r['claim_id']}: {r['validation_errors']}")

    return {
        "pipeline": name,
        "n": n,
        "agreement": agree,
        "agreement_rate": (agree / n) if n else None,
        "draft_attempted": len(draft_attempted),
        "validation_pass": validation_pass,
        "validation_pass_rate": (validation_pass / len(draft_attempted)) if draft_attempted else None,
    }


def main() -> None:
    _require_ollama()

    if not LABELS_PATH.exists():
        sys.exit(
            f"{LABELS_PATH} doesn't exist yet. Run:\n"
            "  python scripts/make_labels_template.py\n"
            "then hand-label 30-50 cases before running this eval."
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["baseline", "langgraph"], default=None, help="Run just one pipeline instead of both.")
    args = parser.parse_args()
    pipelines_to_run = [args.only] if args.only else ["baseline", "langgraph"]

    cases_by_id = {c["claim_id"]: c for c in json.loads(CASES_PATH.read_text())}
    labels = json.loads(LABELS_PATH.read_text())
    labeled = [l for l in labels if l.get("should_appeal") is not None]

    if not labeled:
        sys.exit(f"No labeled cases found in {LABELS_PATH} - fill in should_appeal (true/false) for at least a few cases first.")

    model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    client = get_llm_client()

    summaries = []
    for name in pipelines_to_run:
        print(f"\nRunning {name} agent on {len(labeled)} labeled cases via Ollama ({model_name})...\n")
        results = run_pipeline(name, labeled, cases_by_id, client)
        (RESULTS_DIR / f"eval_results_{name}.json").write_text(json.dumps(results, indent=2))
        summaries.append(summarize(name, results, model_name))

    if len(summaries) == 2:
        base, graph = summaries
        print("\n" + "=" * 60)
        print("COMPARISON (baseline -> langgraph)")
        if base["agreement_rate"] is not None and graph["agreement_rate"] is not None:
            print(f"  Agreement with labels: {base['agreement_rate']:.0%} -> {graph['agreement_rate']:.0%}")
        if base["validation_pass_rate"] is not None and graph["validation_pass_rate"] is not None:
            print(f"  Validation pass rate:  {base['validation_pass_rate']:.0%} -> {graph['validation_pass_rate']:.0%}")
        print("\nThis is the number that justifies using LangGraph here: how much the")
        print("retry-on-validation-failure loop improved the validation pass rate over")
        print("the plain sequential baseline, on the same cases with the same model.")

    print(f"\nFull results written to {RESULTS_DIR}/eval_results_<pipeline>.json")


if __name__ == "__main__":
    main()
