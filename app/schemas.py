from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, HttpUrl, TypeAdapter, field_validator

from app.models import ApplicationStatus

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
    status: ApplicationStatus = ApplicationStatus.applied
    salary_min: Optional[Decimal] = None
    salary_max: Optional[Decimal] = None
    salary_currency: Optional[str] = "USD"
    date_applied: date
    notes: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    job_description: Optional[str] = None

    _check_job_link = field_validator("job_link")(_validated_job_link)


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationUpdate(BaseModel):
    company: Optional[str] = None
    role_title: Optional[str] = None
    job_link: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    status: Optional[ApplicationStatus] = None
    salary_min: Optional[Decimal] = None
    salary_max: Optional[Decimal] = None
    salary_currency: Optional[str] = None
    date_applied: Optional[date] = None
    notes: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    job_description: Optional[str] = None

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


class ApplicationOut(ApplicationListOut):
    """Detail view, including the application's contacts."""

    contacts: List[ContactOut] = []
