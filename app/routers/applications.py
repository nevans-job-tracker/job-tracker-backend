from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=dict)
def read_applications(
    search: Optional[str] = None,
    status: Optional[models.ApplicationStatus] = None,
    sort_by: str = Query("date_applied", pattern="^(company|role_title|status|date_applied|salary_min|salary_max|created_at)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    items, total = crud.list_applications(
        db,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_dir=sort_dir,
        skip=skip,
        limit=limit,
    )
    return {
        "total": total,
        "items": [schemas.ApplicationOut.model_validate(i) for i in items],
    }


@router.get("/{application_id}", response_model=schemas.ApplicationOut)
def read_application(application_id: int, db: Session = Depends(get_db)):
    db_application = crud.get_application(db, application_id)
    if db_application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return db_application


@router.post("", response_model=schemas.ApplicationOut, status_code=201)
def create_application(
    application: schemas.ApplicationCreate, db: Session = Depends(get_db)
):
    return crud.create_application(db, application)


@router.patch("/{application_id}", response_model=schemas.ApplicationOut)
def update_application(
    application_id: int,
    application: schemas.ApplicationUpdate,
    db: Session = Depends(get_db),
):
    db_application = crud.update_application(db, application_id, application)
    if db_application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return db_application


@router.delete("/{application_id}", status_code=204)
def delete_application(application_id: int, db: Session = Depends(get_db)):
    deleted = crud.delete_application(db, application_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Application not found")
    return None
