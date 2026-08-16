from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/applications", tags=["applications"])


def _check_salary_range(minimum, maximum) -> None:
    """Rejects an inverted salary range.

    Enforced here rather than on the schema because a PATCH may supply only one
    of the two values, and the rule has to hold against the *merged* result
    rather than the request body alone.
    """
    if minimum is not None and maximum is not None and minimum > maximum:
        raise HTTPException(
            status_code=422,
            detail="Salary min cannot be greater than salary max.",
        )


@router.get("", response_model=dict)
def read_applications(
    search: Optional[str] = None,
    status: Optional[models.ApplicationStatus] = None,
    show: str = Query("active", pattern="^(active|archived|all)$"),
    sort_by: str = Query(
        "date_applied",
        pattern="^(company|role_title|location|source|status|date_applied|next_action_date|salary_min|salary_max|created_at)$",
    ),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    items, total = crud.list_applications(
        db,
        search=search,
        status=status,
        show=show,
        sort_by=sort_by,
        sort_dir=sort_dir,
        skip=skip,
        limit=limit,
    )
    return {
        "total": total,
        "items": [schemas.ApplicationListOut.model_validate(i) for i in items],
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
    _check_salary_range(application.salary_min, application.salary_max)
    return crud.create_application(db, application)


@router.patch("/{application_id}", response_model=schemas.ApplicationOut)
def update_application(
    application_id: int,
    application: schemas.ApplicationUpdate,
    db: Session = Depends(get_db),
):
    existing = crud.get_application(db, application_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Application not found")

    # Check the range the record will end up with, not just what was sent —
    # a PATCH that lowers only salary_max can still invert the pair.
    submitted = application.model_dump(exclude_unset=True)
    _check_salary_range(
        submitted.get("salary_min", existing.salary_min),
        submitted.get("salary_max", existing.salary_max),
    )

    # Existence was confirmed above, so this cannot come back empty.
    return crud.update_application(db, application_id, application)


# Applications are archived, never deleted — there is deliberately no DELETE
# route here. See REQUIREMENTS.md §4.1.


@router.post("/{application_id}/archive", response_model=schemas.ApplicationOut)
def archive_application(application_id: int, db: Session = Depends(get_db)):
    db_application = crud.set_archived(db, application_id, True)
    if db_application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return db_application


@router.post("/{application_id}/unarchive", response_model=schemas.ApplicationOut)
def unarchive_application(application_id: int, db: Session = Depends(get_db)):
    db_application = crud.set_archived(db, application_id, False)
    if db_application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return db_application


def _require_application(db: Session, application_id: int) -> None:
    if crud.get_application(db, application_id) is None:
        raise HTTPException(status_code=404, detail="Application not found")


@router.get("/{application_id}/contacts", response_model=list[schemas.ContactOut])
def read_contacts(application_id: int, db: Session = Depends(get_db)):
    _require_application(db, application_id)
    return crud.list_contacts(db, application_id)


@router.post(
    "/{application_id}/contacts", response_model=schemas.ContactOut, status_code=201
)
def create_contact(
    application_id: int,
    contact: schemas.ContactCreate,
    db: Session = Depends(get_db),
):
    _require_application(db, application_id)
    return crud.create_contact(db, application_id, contact)


@router.patch(
    "/{application_id}/contacts/{contact_id}", response_model=schemas.ContactOut
)
def update_contact(
    application_id: int,
    contact_id: int,
    contact: schemas.ContactUpdate,
    db: Session = Depends(get_db),
):
    db_contact = crud.update_contact(db, application_id, contact_id, contact)
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact


@router.delete("/{application_id}/contacts/{contact_id}", status_code=204)
def delete_contact(application_id: int, contact_id: int, db: Session = Depends(get_db)):
    deleted = crud.delete_contact(db, application_id, contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    return None
