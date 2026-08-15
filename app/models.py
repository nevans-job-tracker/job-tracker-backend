import enum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Date,
    DateTime,
    Numeric,
    Enum,
    func,
)

from app.database import Base


class ApplicationStatus(str, enum.Enum):
    applied = "applied"
    phone_screen = "phone_screen"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    ghosted = "ghosted"
    withdrawn = "withdrawn"


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    company = Column(String(255), nullable=False, index=True)
    role_title = Column(String(255), nullable=False)
    job_link = Column(String(1024), nullable=True)
    source = Column(String(255), nullable=True)  # e.g. LinkedIn, referral
    location = Column(String(255), nullable=True)

    status = Column(
        Enum(ApplicationStatus), nullable=False, default=ApplicationStatus.applied
    )

    salary_min = Column(Numeric(10, 2), nullable=True)
    salary_max = Column(Numeric(10, 2), nullable=True)
    salary_currency = Column(String(10), nullable=True, default="USD")

    date_applied = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
