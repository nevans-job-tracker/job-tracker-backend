from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas


def get_application(db: Session, application_id: int) -> Optional[models.Application]:
    return (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )


def list_applications(
    db: Session,
    search: Optional[str] = None,
    status: Optional[models.ApplicationStatus] = None,
    sort_by: str = "date_applied",
    sort_dir: str = "desc",
    skip: int = 0,
    limit: int = 100,
):
    query = db.query(models.Application)

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                models.Application.company.ilike(like),
                models.Application.role_title.ilike(like),
                models.Application.location.ilike(like),
            )
        )

    if status:
        query = query.filter(models.Application.status == status)

    sort_column = getattr(models.Application, sort_by, models.Application.date_applied)
    if sort_dir == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return items, total


def create_application(
    db: Session, application: schemas.ApplicationCreate
) -> models.Application:
    db_application = models.Application(**application.model_dump())
    db.add(db_application)
    db.commit()
    db.refresh(db_application)
    return db_application


def update_application(
    db: Session, application_id: int, application: schemas.ApplicationUpdate
) -> Optional[models.Application]:
    db_application = get_application(db, application_id)
    if not db_application:
        return None

    update_data = application.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_application, field, value)

    db.commit()
    db.refresh(db_application)
    return db_application


def delete_application(db: Session, application_id: int) -> bool:
    db_application = get_application(db, application_id)
    if not db_application:
        return False
    db.delete(db_application)
    db.commit()
    return True
