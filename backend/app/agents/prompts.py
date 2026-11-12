"""
Prompt construction for claim-suggestion generation.

This is the file that actually "closes the loop": it pulls recent human
overrides for this org and folds them into the prompt as few-shot examples,
so a past correction can change the model's next suggestion instead of just
sitting in the `feedback` table unused.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.safety import UNTRUSTED_NOTICE, clean_text, neutralize_tags, wrap_untrusted

MAX_FEW_SHOT_EXAMPLES = 3

SYSTEM_INSTRUCTIONS = """You are assisting an insurance adjuster by suggesting the next action \
on a claim. Respond with a single JSON object and nothing else, with exactly \
these keys: "suggested_action" (one of: under_review, approved, denied), \
"rationale" (one sentence), and "confidence" (a float between 0 and 1). """ + UNTRUSTED_NOTICE


def build_suggestion_prompt(claim: "models.Claim", db: Session) -> str:
    few_shot = _recent_overrides_for_org(db, org_id=claim.org_id, limit=MAX_FEW_SHOT_EXAMPLES)

    sections = [SYSTEM_INSTRUCTIONS]

    if few_shot:
        sections.append(_format_few_shot_block(few_shot))

    sections.append(_format_claim_block(claim))

    return "\n\n".join(sections)


def _recent_overrides_for_org(
    db: Session, org_id: str, limit: int
) -> list[tuple["models.Claim", "models.Suggestion", "models.Feedback"]]:
    """
    The core of the feedback loop: pull the most recent *overridden*
    suggestions for this org (not accepted ones — an override is the
    signal that the model got something wrong) so the prompt can learn
    from this org's specific correction history rather than generic
    training data.
    """
    stmt = (
        select(models.Claim, models.Suggestion, models.Feedback)
        .join(models.Suggestion, models.Suggestion.claim_id == models.Claim.id)
        .join(models.Feedback, models.Feedback.suggestion_id == models.Suggestion.id)
        .where(
            models.Claim.org_id == org_id,  # tenant scoping — never skip this
            models.Feedback.action_taken == models.FeedbackAction.OVERRIDDEN,
        )
        .order_by(models.Feedback.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).all())


def _safe(text: str | None) -> str:
    # History notes and override reasons are typed by people. See app/safety.py.
    return neutralize_tags(clean_text(text, 400)) or "none"


def _format_few_shot_block(
    examples: list[tuple["models.Claim", "models.Suggestion", "models.Feedback"]]
) -> str:
    lines = ["Recent adjuster corrections on similar claims (learn from these):"]
    for claim, suggestion, feedback in examples:
        lines.append(
            f'- Claim amount ${claim.amount:.0f}, history: "{_safe(claim.history_notes)}". '
            f'AI suggested "{suggestion.suggested_action}", but the adjuster overrode it to '
            f'"{feedback.final_action}" because: {_safe(feedback.override_reason)}.'
        )
    return "\n".join(lines)


def _format_claim_block(claim: "models.Claim") -> str:
    return (
        "Now score this claim:\n"
        f"Amount requested: {claim.amount}\n"
        f"Current status: {claim.status.value}\n"
        "History notes:\n" + wrap_untrusted("history", claim.history_notes or "none")
    )
