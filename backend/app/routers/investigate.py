from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import schemas
from app.agents.investigator import investigate
from app.database import get_db
from app.deps import get_current_org_id
from app.routers.claims import _get_claim_or_404

router = APIRouter(tags=["investigate"])


class InvestigateRequest(BaseModel):
    question: str | None = Field(default=None, max_length=300)


@router.post("/claims/{claim_id}/investigate", response_model=schemas.InvestigationOut)
def investigate_claim(
    claim_id: str,
    body: InvestigateRequest | None = None,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    """Run the ReAct investigator on a claim. Read only. Returns the answer and every step."""
    claim = _get_claim_or_404(db, claim_id, org_id)
    return investigate(db, claim, body.question if body else None)
