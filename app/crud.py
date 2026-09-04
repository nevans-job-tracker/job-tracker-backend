from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_
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
    activity: str = "active",
    source: Optional[str] = None,
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

    # Exact, not ilike. The values come from a dropdown built from the data, so
    # exactness is achievable — and it keeps "LinkedIn" and "linkedin" distinct
    # rather than quietly merging them, which is what makes the fragmentation
    # §2 predicted visible instead of hidden.
    if source:
        query = query.filter(models.Application.source == source)

    if status:
        query = query.filter(models.Application.status == status)

    # A second, coarser cut of the same column (KAN-62). Both apply when both
    # are given: the UI only ever sends one, so an impossible pair is only
    # reachable by hand-editing a URL, and an empty list is a more predictable
    # answer there than one filter quietly winning.
    #
    # sorted() because a frozenset has no order and the emitted IN clause would
    # otherwise vary between runs, which makes a query log needlessly unstable.
    if activity == "active":
        query = query.filter(
            models.Application.status.in_(sorted(models.ACTIVE_STATUSES))
        )
    elif activity == "inactive":
        query = query.filter(
            models.Application.status.in_(sorted(models.INACTIVE_STATUSES))
        )

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

    # Every row in the table, filters and archive state included, so the list
    # can say what it is not showing (KAN-62). Counted separately rather than
    # derived, because `total` has every filter applied and there is no
    # arithmetic that recovers the whole from it.
    #
    # A second COUNT on every list request. It is one indexless count over a
    # table this project measures in dozens of rows, and the alternative is a
    # count the screen cannot explain.
    total_unfiltered = db.query(models.Application).count()

    items = query.offset(skip).limit(limit).all()
    return items, total, total_unfiltered


def _record_status(db: Session, application_id: int, from_status, to_status) -> None:
    """Appends to the status history (KAN-42).

    Called explicitly from the two functions that can move a status, rather
    than from an ORM event that fires invisibly. Be clear about what that is: a
    convention, not the kind of assertion conftest.py uses to protect the live
    database. A third write path added later would leave history silently
    incomplete — which is the worst failure mode, because nothing looks wrong.
    `test_only_two_paths_change_a_status` is what pins the assumption.
    """
    db.add(
        models.StatusChange(
            application_id=application_id,
            from_status=from_status,
            to_status=to_status,
        )
    )


def list_sources(db: Session):
    """Every distinct source, sorted, across *all* records.

    Deliberately not filtered by the caller's current view. If the options
    were computed from the rows on screen, choosing a source would collapse
    the dropdown to that one value and leave no way back — the set has to be
    stable while the list underneath it changes.

    Archived records count for the same reason: their source is still a real
    thing the data contains, and hiding the option would make those rows
    unreachable through the filter.
    """
    rows = (
        db.query(models.Application.source)
        .filter(models.Application.source.isnot(None))
        .filter(models.Application.source != "")
        .distinct()
        .all()
    )
    return sorted(row[0] for row in rows)


def find_duplicate(db: Session, company: str, role_title: str, job_link):
    """The existing application matching company, role title and job link.

    Compared case-insensitively and trimmed, so "Sequencing.com" and
    "sequencing.com" are one posting rather than two.

    Two records with no link at all, matching on company and role, count as
    duplicates. SQL would normally say NULL != NULL and let both through —
    which is exactly the manual-entry case this exists to stop.

    Archived records count. You already have the posting; that it is out of
    view is not a reason to add another. See REQUIREMENTS.md §4.1.
    """
    normalise = lambda value: func.lower(func.trim(value))
    query = db.query(models.Application).filter(
        normalise(models.Application.company) == (company or "").strip().lower(),
        normalise(models.Application.role_title) == (role_title or "").strip().lower(),
    )

    link = (job_link or "").strip()
    if link:
        query = query.filter(normalise(models.Application.job_link) == link.lower())
    else:
        query = query.filter(models.Application.job_link.is_(None))

    return query.first()


def create_application(
    db: Session, application: schemas.ApplicationCreate
) -> models.Application:
    db_application = models.Application(**application.model_dump())
    db.add(db_application)
    db.flush()  # assigns the id the history row needs

    # from_status is NULL: an application does not transition into existence.
    _record_status(db, db_application.id, None, db_application.status)

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
    previous_status = db_application.status
    for field, value in update_data.items():
        setattr(db_application, field, value)

    # Only a real move is history. Saving the detail screen without touching
    # the status sends it back unchanged every time, and recording those would
    # bury the transitions in noise and make every duration read as zero.
    if db_application.status != previous_status:
        _record_status(db, application_id, previous_status, db_application.status)

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


def status_timeline(db: Session):
    """How many applications sat in each status on each day (KAN-70).

    Reconstructed by replaying `status_changes` rather than stored: walk the
    days from the first recorded change to today, apply each change as its
    date passes, and snapshot the counts. The applications table holds only
    the current status, so a day-by-day picture can come from nowhere else.

    Computed here rather than in the browser. Sending every history row and
    reconstructing client-side would put this logic somewhere it has to be
    re-derived per consumer, and would grow the response with the table.

    **Archived applications are included.** Archiving records whether a record
    should still be in view (§4.1), not something that happened to it —
    excluding them would make bands shrink on days when nothing changed.

    A day with no changes still gets an entry, carrying the previous day's
    counts forward. Without that the chart would join across gaps and imply
    movement that did not happen.
    """
    changes = (
        db.query(models.StatusChange)
        .order_by(models.StatusChange.changed_at, models.StatusChange.id)
        .all()
    )
    if not changes:
        # An empty series rather than a single zeroed day. The screen has its
        # own empty state, and inventing a day would put a point on a chart of
        # nothing that happened.
        return {"series": [], "opening_count": 0}

    first = changes[0].changed_at.date()
    last = max(first, datetime.utcnow().date())


    current: dict[int, str] = {}
    series = []
    index = 0
    day = first

    while day <= last:
        # Apply everything recorded on or before this day.
        while index < len(changes) and changes[index].changed_at.date() <= day:
            change = changes[index]
            current[change.application_id] = change.to_status.value
            index += 1

        counts: dict[str, int] = {}
        for status in current.values():
            counts[status] = counts.get(status, 0) + 1

        series.append({"date": day.isoformat(), "counts": counts})
        day += timedelta(days=1)

    # How many applications the chart opens with. Everything predating KAN-42
    # was stamped at the migration, so the left edge is a step rather than a
    # slope, and rendering that without saying so would claim a day of
    # activity that did not happen. Returned as a number so the note scales
    # with the data instead of being a fixed sentence that goes stale.
    #
    # **Read off the first day's snapshot, not counted from the rows landing
    # that day.** Those differ whenever an application moved twice on the
    # opening day — it contributes two rows and one application — and a number
    # the chart beside it contradicts is worse than no number. Taken from the
    # series, the two cannot disagree.
    opening = sum(series[0]["counts"].values())

    return {"series": series, "opening_count": opening}


def list_status_changes(db: Session, application_id: int) -> list[models.StatusChange]:
    """Oldest first. `id` breaks ties, because two changes in the same second
    are possible and the timeline's durations depend on a stable order."""
    return (
        db.query(models.StatusChange)
        .filter(models.StatusChange.application_id == application_id)
        .order_by(models.StatusChange.changed_at, models.StatusChange.id)
        .all()
    )


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
