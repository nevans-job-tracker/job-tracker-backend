from datetime import datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

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
    show: str = "active",
    sort_by: str = "date_applied",
    sort_dir: str = "desc",
    skip: int = 0,
    limit: int = 100,
    with_contacts: bool = False,
):
    query = db.query(models.Application)

    # Opt-in, and eager. REQUIREMENTS.md §2.1 keeps contacts off list rows
    # because loading them per row is one query per application on every
    # request. That reasoning still holds for the list, so this stays off by
    # default; selectinload makes it one extra query for the whole page rather
    # than N, which is what lets the CSV export ask for them (KAN-39) without
    # reintroducing the cost the rule exists to avoid.
    if with_contacts:
        query = query.options(selectinload(models.Application.contacts))

    # Archive state is an axis of its own, independent of `status`: both filters
    # apply at once. See REQUIREMENTS.md §4.1.
    if show == "active":
        query = query.filter(models.Application.archived_at.is_(None))
    elif show == "archived":
        query = query.filter(models.Application.archived_at.is_not(None))

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                models.Application.company.ilike(like),
                models.Application.role_title.ilike(like),
                models.Application.location.ilike(like),
                models.Application.source.ilike(like),
                models.Application.notes.ilike(like),
            )
        )

    if status:
        query = query.filter(models.Application.status == status)

    sort_column = getattr(models.Application, sort_by, models.Application.date_applied)

    # A NULL sorts as though it were greater than every real value.
    #
    # This is a decision, not the database's default (KAN-31). An application
    # you have not sent has no `date_applied` because that date, if it ever
    # exists, is in the future — so treating NULL as the largest value makes
    # the ordering a total order that means something, rather than a pile of
    # rows dumped at whichever end the dialect happens to choose.
    #
    # What it buys: the list's default sort is `date_applied` descending, so
    # jobs not yet applied to surface at the top, where the next action is.
    # Inherited behaviour put them last — below a "Load more" button on any
    # list past 50 rows, which is to say off-screen and effectively lost.
    # Reversing the sort still reverses the whole list; nothing is pinned.
    #
    # Applied to every sortable column rather than special-cased for dates, so
    # there is one rule. Ascending now puts empty Location/Source/Next action
    # last, which is the conventional expectation and was previously reversed.
    #
    # Expressed as a leading `IS NULL` key because MariaDB has no
    # `NULLS FIRST` / `NULLS LAST`; the comparison yields 0 or 1 on both it and
    # SQLite, so the two agree.
    missing = sort_column.is_(None)
    if sort_dir == "asc":
        query = query.order_by(missing.asc(), sort_column.asc())
    else:
        query = query.order_by(missing.desc(), sort_column.desc())

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


def set_archived(
    db: Session, application_id: int, archived: bool
) -> Optional[models.Application]:
    """Archives or restores an application.

    Applications are never deleted, so this replaces what would elsewhere be a
    delete. Contacts are left attached, so restoring brings back the whole
    record. See REQUIREMENTS.md §4.1.
    """
    db_application = get_application(db, application_id)
    if not db_application:
        return None

    db_application.archived_at = datetime.now() if archived else None
    db.commit()
    db.refresh(db_application)
    return db_application


def get_contact(
    db: Session, application_id: int, contact_id: int
) -> Optional[models.Contact]:
    """Scoped to the application, so a contact id from another application
    cannot be read or written through the wrong URL."""
    return (
        db.query(models.Contact)
        .filter(
            models.Contact.id == contact_id,
            models.Contact.application_id == application_id,
        )
        .first()
    )


def list_contacts(db: Session, application_id: int) -> list[models.Contact]:
    return (
        db.query(models.Contact)
        .filter(models.Contact.application_id == application_id)
        .order_by(models.Contact.id)
        .all()
    )


def create_contact(
    db: Session, application_id: int, contact: schemas.ContactCreate
) -> models.Contact:
    db_contact = models.Contact(application_id=application_id, **contact.model_dump())
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact


def update_contact(
    db: Session, application_id: int, contact_id: int, contact: schemas.ContactUpdate
) -> Optional[models.Contact]:
    db_contact = get_contact(db, application_id, contact_id)
    if not db_contact:
        return None

    update_data = contact.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_contact, field, value)

    db.commit()
    db.refresh(db_contact)
    return db_contact


def delete_contact(db: Session, application_id: int, contact_id: int) -> bool:
    db_contact = get_contact(db, application_id, contact_id)
    if not db_contact:
        return False
    db.delete(db_contact)
    db.commit()
    return True
