from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models import ApplicationStatus


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


class ApplicationOut(ApplicationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
