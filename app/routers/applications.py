from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/applications", tags=["applications"])


def _check_range(minimum, maximum, message: str) -> None:
    """Rejects an inverted min/max pair.

    Enforced here rather than on the schema because a PATCH may supply only one
    of the two values, and the rule has to hold against the *merged* result
    rather than the request body alone — lowering only the max can still invert
    the pair against the stored min.

    Shared by salary and weekly hours, which are the same shape and the same
    kind of typo. See REQUIREMENTS.md §2.
    """
    if minimum is not None and maximum is not None and minimum > maximum:
        raise HTTPException(status_code=422, detail=message)


SALARY_INVERTED = "Salary min cannot be greater than salary max."
HOURS_INVERTED = "Hours per week min cannot be greater than hours per week max."


CONTRACT_TYPES = (
    models.EmploymentType.contract,
    models.EmploymentType.contract_to_hire,
)


def _check_contract_term(employment_type, term_months) -> None:
    """Rejects a contract term on a posting that is not a contract.

    Same shape and same reasoning as the salary rule above: a PATCH may set
    only one of the pair, so switching a stored contract to full_time while
    its term remains has to fail. Checking the request body alone would let
    that through and leave a term nothing explains.

    The form hides the term field unless a contract type is selected, but that
    is convenience — §6.1 makes the general point that a rule enforced only in
    the UI is decorative while the API is directly reachable.
    """
    if term_months is not None and employment_type not in CONTRACT_TYPES:
        raise HTTPException(
            status_code=422,
            detail="A contract term only applies to a contract role.",
        )


@router.get("", response_model=dict)
def read_applications(
    search: Optional[str] = None,
    status: Optional[models.ApplicationStatus] = None,
    # A coarser cut of `status`, not a widening of it (KAN-62). Folding
    # "active" into the `status` parameter would mean a field typed as a single
    # ApplicationStatus accepting values that are not one, so the API would be
    # lying about its own type. One dropdown drives both; that is the UI's
    # business, not the wire's.
    activity: Optional[str] = Query(None, pattern="^(active|inactive|all)$"),
    source: Optional[str] = None,
    # `show` keeps its wire values even though `show=active` and
    # `activity=active` now mean unrelated things — archive state and lifecycle
    # respectively. Renaming buys a tidier wire for a coordinated backend,
    # frontend and test change; KAN-50 made the same call about salary_min. The
    # displayed labels carry the distinction ("Archived Hidden"), and this is
    # recorded so the mismatch reads as a decision rather than an oversight.
    show: str = Query("active", pattern="^(active|archived|all)$"),
    sort_by: str = Query(
        "date_applied",
        pattern=(
            "^(company|role_title|location|source|status|company_size|"
            "years_experience_min|employment_type|date_applied|"
            "next_action_date|salary_min|salary_max|created_at)$"
        ),
    ),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = 0,
    limit: int = 100,
    include_contacts: bool = False,
    db: Session = Depends(get_db),
):
    # None means "nothing was said about lifecycle", which is not the same as
    # asking for active. Asking for one status is asking for that status
    # whatever its lifecycle, so `?status=rejected` on its own has to return
    # rejected rows rather than the empty intersection with a default it never
    # mentioned. An explicit `activity` still applies alongside `status` — the
    # two only stop combining when one of them was never asked for.
    resolved_activity = activity or ("all" if status else "active")

    items, total, total_unfiltered = crud.list_applications(
        db,
        search=search,
        status=status,
        activity=resolved_activity,
        source=source,
        show=show,
        sort_by=sort_by,
        sort_dir=sort_dir,
        skip=skip,
        limit=limit,
        with_contacts=include_contacts,
    )
    # Contacts are embedded only when asked for. The CSV export (KAN-39) wants
    # them; the list screen never does, and §2.1 is explicit about why it must
    # not pay for them by default.
    out = schemas.ApplicationOut if include_contacts else schemas.ApplicationListOut
    return {
        "total": total,
        # What the filters excluded, so the list can account for rows that are
        # not on screen (KAN-62). With archive state and activity as
        # independent axes, a row can be missing for either reason and neither
        # dropdown says so on its own.
        "total_unfiltered": total_unfiltered,
        "items": [out.model_validate(i) for i in items],
    }


@router.get("/sources", response_model=dict)
def read_sources(db: Session = Depends(get_db)):
    """The distinct sources, for the list's Source filter.

    Declared *before* /{application_id}: that path parameter is typed int, so
    FastAPI would try to parse "sources" as one and return 422 rather than
    falling through to this route.

    A separate endpoint rather than a field on the list response, because the
    list is filtered and paginated — its rows are the wrong population to
    build a stable set of options from. See KAN-56.
    """
    return {"sources": crud.list_sources(db)}


@router.get("/status-timeline", response_model=schemas.StatusTimelineOut)
def read_status_timeline(db: Session = Depends(get_db)):
    """Applications per status per day, for the insights screen (KAN-70).

    Declared before /{application_id} for the same reason /sources is: that
    path parameter is typed int, so "status-timeline" would 422 rather than
    fall through.

    **Computed here rather than in the browser.** The alternative is shipping
    every history row and replaying it client-side, which puts the same logic
    somewhere it has to be re-derived per consumer and grows the response with
    the table rather than with the number of days.

    **Archived applications are included.** Archiving records whether a record
    should still be in view (§4.1) — not something that happened to the
    application — so excluding them would make bands shrink on days when
    nothing actually changed.
    """
    return crud.status_timeline(db)


@router.get("/{application_id}", response_model=schemas.ApplicationOut)
def read_application(application_id: int, db: Session = Depends(get_db)):
    db_application = crud.get_application(db, application_id)
    if db_application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return db_application


def _check_not_duplicate(db: Session, application) -> None:
    """Rejects a second copy of a posting already tracked.

    Enforced here rather than as a UNIQUE index, which does not fit: job_link
    is VARCHAR(1024) and InnoDB's key limit is 3072 bytes, which utf8mb4
    reaches at 768 characters for that column alone. Hashing the link would
    work and is more machinery than a single-user tracker needs.

    That makes this a convention rather than an assertion — a second writer
    could race it. There is one writer, so the exposure is theoretical. See
    REQUIREMENTS.md §2.
    """
    existing = crud.find_duplicate(
        db, application.company, application.role_title, application.job_link
    )
    if existing is None:
        return

    # Naming the archive state matters: a rejection pointing at a record that
    # is not in the list is otherwise baffling.
    where = " (archived)" if existing.archived_at else ""
    raise HTTPException(
        status_code=409,
        detail=(
            f"Already tracked as #{existing.id}{where}: "
            f"{existing.company} — {existing.role_title}."
        ),
    )


@router.post("", response_model=schemas.ApplicationOut, status_code=201)
def create_application(
    application: schemas.ApplicationCreate, db: Session = Depends(get_db)
):
    _check_range(application.salary_min, application.salary_max, SALARY_INVERTED)
    _check_range(
        application.hours_per_week_min,
        application.hours_per_week_max,
        HOURS_INVERTED,
    )
    _check_contract_term(application.employment_type, application.contract_term_months)
    _check_not_duplicate(db, application)
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
    _check_range(
        submitted.get("salary_min", existing.salary_min),
        submitted.get("salary_max", existing.salary_max),
        SALARY_INVERTED,
    )
    _check_range(
        submitted.get("hours_per_week_min", existing.hours_per_week_min),
        submitted.get("hours_per_week_max", existing.hours_per_week_max),
        HOURS_INVERTED,
    )
    _check_contract_term(
        submitted.get("employment_type", existing.employment_type),
        submitted.get("contract_term_months", existing.contract_term_months),
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


@router.get(
    "/{application_id}/history", response_model=list[schemas.StatusChangeOut]
)
def read_status_history(application_id: int, db: Session = Depends(get_db)):
    """Its own endpoint rather than embedded in the detail response — see the
    note on StatusChangeOut for why that would cost the CSV export an N+1."""
    _require_application(db, application_id)
    return crud.list_status_changes(db, application_id)


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
