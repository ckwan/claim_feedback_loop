from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(tags=["setup"])


@router.post("/organizations", response_model=schemas.OrganizationOut)
def create_organization(payload: schemas.OrganizationCreate, db: Session = Depends(get_db)):
    org = models.Organization(name=payload.name)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.post("/adjusters", response_model=schemas.AdjusterOut)
def create_adjuster(payload: schemas.AdjusterCreate, db: Session = Depends(get_db)):
    adjuster = models.Adjuster(org_id=payload.org_id, name=payload.name, email=payload.email)
    db.add(adjuster)
    db.commit()
    db.refresh(adjuster)
    return adjuster
