import enum

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    Date,
    DateTime,
    Numeric,
    Enum,
    func,
)
from sqlalchemy.orm import relationship

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

    # What is owed next and when — turns the list into a worklist rather than
    # a log. See REQUIREMENTS.md §2.
    next_action = Column(String(255), nullable=True)
    next_action_date = Column(Date, nullable=True)

    # Snapshot of the posting, which outlives the job_link once the ad is taken
    # down mid-process.
    job_description = Column(Text, nullable=True)

    # Archive marker. NULL means active. Applications are archived, never
    # deleted, and never purged — see REQUIREMENTS.md §4.1.
    archived_at = Column(DateTime, nullable=True, index=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    contacts = relationship(
        "Contact",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="Contact.id",
    )


class Contact(Base):
    """A person tied to an application — recruiter, hiring manager, referrer.

    Several contacts may belong to one application, so these live in their own
    table rather than as flat columns. See REQUIREMENTS.md §2.1.
    """

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer,
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)  # e.g. Manager, HR, Sr. QA Engineer
    phone = Column(String(50), nullable=True)  # free text: extensions, intl formats
    email = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    application = relationship("Application", back_populates="contacts")
