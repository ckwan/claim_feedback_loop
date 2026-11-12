# Scenario: Claim Denial Appeal

Adopted per the 12-week LangGraph/Temporal rebuild plan (Week 1).

## The problem

A claim gets denied (e.g. by the existing feedback-loop suggestion flow, or
set directly). The claimant or their adjuster wants to appeal the denial.
Writing a solid appeal letter requires:

1. Knowing the specific policy language the denial was based on (retrieval).
2. Reasoning about whether the denial reason is actually well-supported by
   the claim facts, or whether there's a gap worth appealing (reasoning).
3. Drafting a letter that cites the right policy sections and claim facts,
   in a tone appropriate for an insurance appeal (drafting).
4. Checking the draft is complete and well-formed before it goes to a human
   for review — right length, cites a real policy section, no placeholder
   text left in (validation).

That four-step shape (retrieve → reason → draft → validate) is what the
LangGraph agent in the 12-week plan implements as four graph nodes.

## Why this scenario over the existing "suggest next action" one

The existing Claims Feedback Loop project suggests a single next *action*
(approve/deny/review) — one LLM call, one JSON object back. It's a good
human-in-the-loop demo but a thin agent demo: there's nothing to reason
through, nothing to retrieve, nothing to draft.

Denial appeal needs all four. It's a better vehicle for LangGraph (multiple
nodes, conditional routing, a retry loop when validation fails) and for
Temporal (the human-approval wait can span hours or days — a real adjuster
won't review a draft appeal in the same request). It also still plugs into
the same human-in-the-loop *data*: an adjuster's edits to a draft appeal
become the few-shot feedback signal, same mechanism, better payload.

## Data shape (drives the synthetic dataset and later the LangGraph state)

Each case:
- `claim_id`, `org_id` — tenant scoping, unchanged from the existing project
- `policyholder_name`, `policy_type`, `claim_amount`
- `claim_facts` — a short narrative of what happened and what was claimed
- `denial_reason` — the stated reason the claim was denied
- `denial_code` — a short internal code for the reason (drives which policy
  section is relevant to retrieve)
- `policy_excerpt` — the actual policy language the denial is based on
  (this is what the RAG retrieve step should surface)

No real PHI/PII anywhere — every name, policy number, and narrative below is
synthetic, generated from templates, not derived from any real claim.

## Eval set (Week 2)

30–50 of the 60 synthetic cases below get hand-labeled with: should this
denial actually be appealed (yes/no, given the facts vs. the policy
excerpt), and if yes, what's the strongest ground for appeal. That becomes
the eval set the LangGraph agent's drafts get scored against.

## Status

- `app/agents/denial_appeal.py` — baseline pipeline (reason → draft →
  validate, plain sequential calls, no retry). Done.
- `app/agents/appeal_graph.py` — LangGraph version of the same pipeline.
  Conditional edge after validation: on failure, routes back to `draft`
  with the specific validation errors fed into the retry prompt, up to
  `MAX_RETRIES` (2) attempts before giving up. This is the piece the
  baseline structurally can't do. Verified with a scripted fake client that
  the retry fires exactly once when the first draft is bad and the second
  is good, and that it gives up cleanly after 3 total attempts when nothing
  fixes it.
- `scripts/run_baseline_eval.py` — runs both pipelines over the same
  hand-labeled cases and prints a side-by-side comparison (agreement rate,
  validation pass rate for each, and the delta between them). This
  comparison is the actual justification for using LangGraph here — not
  "I used LangGraph," but "the retry loop raised the validation pass rate
  from X% to Y% on the same cases, same model."
- Not yet run against a real model: this was all built and tested in a
  sandbox with no Ollama daemon available, using fake/scripted LLM clients
  to confirm the control flow (routing, retries, give-up condition) is
  correct. The actual numbers — real agreement rate, real validation pass
  rate, real before/after delta — still need a real run on your machine
  with Ollama + a pulled model, per the instructions at the top of
  `scripts/run_baseline_eval.py`.
