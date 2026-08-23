from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.models import ApplicationStatus, CompanySize

_http_url = TypeAdapter(HttpUrl)


def _validated_job_link(value: Optional[str]) -> Optional[str]:
    """Rejects anything that isn't an http(s) URL.

    The browser form marks this field `type="url"`, but that guard is absent
    for anything calling the API directly — including /docs.

    The original string is returned rather than the parsed URL: pydantic's
    HttpUrl normalises (adding a trailing slash, for instance), and a link the
    user pasted should come back exactly as they entered it.
    """
    if value is None or value == "":
        return None
    _http_url.validate_python(value)
    return value


class ContactBase(BaseModel):
    name: str
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class ContactOut(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    created_at: datetime
    updated_at: datetime


class ApplicationBase(BaseModel):
    company: str
    role_title: str
    job_link: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    company_size: Optional[CompanySize] = None
    # Lower bound only. Negative years is not a value anyone means to enter, so
    # it is rejected rather than stored; there is no equally obvious upper bound
    # — 30 is unusual but real — so none is imposed.
    years_experience_min: Optional[int] = Field(default=None, ge=0)
    status: ApplicationStatus = ApplicationStatus.applied
    salary_min: Optional[Decimal] = None
    salary_max: Optional[Decimal] = None
    salary_currency: Optional[str] = "USD"
    # Optional: a job being tracked before it is applied for has no date yet.
    # See REQUIREMENTS.md §2.
    date_applied: Optional[date] = None
    notes: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    job_description: Optional[str] = None
    cover_letter: Optional[str] = None

    _check_job_link = field_validator("job_link")(_validated_job_link)


class ApplicationCreate(ApplicationBase):
    @model_validator(mode="after")
    def _undated_means_interested(self):
        """A create with no date and no stated status is an intention, not an
        application.

        `applied` is the right default for the overwhelming majority of
        records, so it stays the declared one — but a record with no
        `date_applied` cannot be an application, and defaulting it to `applied`
        would produce exactly the row this story exists to prevent: something
        labelled Applied with nothing to say when.

        `model_fields_set` is what makes this safe to do silently. An explicit
        `"status": "applied"` in the request body is honoured even without a
        date; only an *absent* status is reinterpreted.
        """
        if self.date_applied is None and "status" not in self.model_fields_set:
            self.status = ApplicationStatus.interested
        return self


class ApplicationUpdate(BaseModel):
    company: Optional[str] = None
    role_title: Optional[str] = None
    job_link: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    company_size: Optional[CompanySize] = None
    years_experience_min: Optional[int] = Field(default=None, ge=0)
    status: Optional[ApplicationStatus] = None
    salary_min: Optional[Decimal] = None
    salary_max: Optional[Decimal] = None
    salary_currency: Optional[str] = None
    date_applied: Optional[date] = None
    notes: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    job_description: Optional[str] = None
    cover_letter: Optional[str] = None

    _check_job_link = field_validator("job_link")(_validated_job_link)


class ApplicationListOut(ApplicationBase):
    """List rows. Deliberately excludes contacts — the list never displays them,
    and loading them per row would mean a query per application."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime

    # Read-only: set through the archive/unarchive endpoints, never by PATCH,
    # so it cannot be edited alongside ordinary fields.
    archived_at: Optional[datetime] = None


class StatusChangeOut(BaseModel):
    """One recorded transition (KAN-42), read by the timeline (KAN-43).

    Deliberately *not* embedded in ApplicationOut. That schema is what the list
    returns when the CSV export asks for contacts, so adding history to it would
    make every exported application lazily load its own — one query per row,
    the N+1 §2.1 exists to prevent, reintroduced through a schema nobody
    thought to check.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: Optional[ApplicationStatus] = None
    to_status: ApplicationStatus
    changed_at: datetime


class ApplicationOut(ApplicationListOut):
    """Detail view, including the application's contacts."""

    contacts: List[ContactOut] = []
