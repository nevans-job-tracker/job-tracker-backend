import enum

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
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

    # Appended rather than placed first, where the lifecycle would put it.
    # MySQL and MariaDB store an ENUM as its ordinal, so appending is the only
    # change that leaves existing rows meaning what they meant. The order the
    # user sees is set by STATUS_LABELS in the frontend, not here.
    interested = "interested"

    # The posting went away — pulled, filled, or expired (KAN-57). Distinct
    # from `rejected`, which asserts that somebody considered you and said no:
    # here nobody decided anything, and often the application was never sent.
    # Appended for the same ordinal reason as `interested` above.
    posting_closed = "posting_closed"


class CompanySize(str, enum.Enum):
    """Wellfound's bands, adopted rather than invented so the values match what
    the postings already say. See REQUIREMENTS.md §2 for the trade-off.

    Declared smallest to largest deliberately. MySQL and MariaDB store an ENUM
    as its ordinal, so this order is what makes `ORDER BY company_size` mean
    band order instead of alphabetical.
    """

    seed = "seed"  # 1-10 employees
    early = "early"  # 11-50
    mid_size = "mid_size"  # 51-200
    large = "large"  # 201-500
    very_large = "very_large"  # 501-1000
    massive = "massive"  # 1001+


class PayPeriod(str, enum.Enum):
    """What the figures in salary_min/salary_max actually measure (KAN-50).

    Before this column the two were told apart by magnitude alone — the display
    rule "values below 1000 are shown unrounded" was the only thing stopping an
    86/hour rate rendering as "0K". That guard remains, but it is no longer
    carrying a fact the schema should have held.
    """

    annual = "annual"
    hourly = "hourly"


class EmploymentType(str, enum.Enum):
    """Whether the posting is permanent, fixed-term, or unpaid (KAN-51).

    Declaration order is load-bearing for the same reason as CompanySize:
    MySQL and MariaDB store an ENUM as its ordinal, so this is what any
    `ORDER BY employment_type` means. It runs from most to least conventional
    commitment, with the two contract kinds adjacent.
    """

    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    contract_to_hire = "contract_to_hire"
    volunteer = "volunteer"


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    company = Column(String(255), nullable=False, index=True)
    role_title = Column(String(255), nullable=False)
    job_link = Column(String(1024), nullable=True)
    source = Column(String(255), nullable=True)  # e.g. LinkedIn, referral
    location = Column(String(255), nullable=True)

    # Both nullable: a posting often states neither, and guessing is worse than
    # leaving it blank. See REQUIREMENTS.md §2.
    company_size = Column(Enum(CompanySize), nullable=True)
    years_experience_min = Column(SmallInteger, nullable=True)

    status = Column(
        Enum(ApplicationStatus), nullable=False, default=ApplicationStatus.applied
    )

    salary_min = Column(Numeric(10, 2), nullable=True)
    salary_max = Column(Numeric(10, 2), nullable=True)
    salary_currency = Column(String(10), nullable=True, default="USD")

    # NOT NULL with a default, unlike the two below: every pay figure is one
    # period or the other, so there is no honest "unset" state. The column
    # names stay `salary_*` deliberately — renaming them is a migration that
    # also moves the API surface and the sort whitelist, to buy a better name
    # for something this column has already disambiguated. See KAN-50.
    pay_period = Column(
        Enum(PayPeriod), nullable=False, server_default=PayPeriod.annual.value
    )

    # Nullable and *not* defaulted, unlike pay_period: plenty of postings do
    # not say, and defaulting to full_time would invent a fact for every
    # existing row. Blank means "not recorded". See KAN-51.
    employment_type = Column(Enum(EmploymentType), nullable=True)

    # Only meaningful alongside a contract employment_type. That pairing is
    # enforced in the route against the merged PATCH result, not here — the
    # same shape as the salary_min <= salary_max rule and for the same reason.
    contract_term_months = Column(SmallInteger, nullable=True)

    # Expected weekly hours, which contract and part-time postings often state
    # and full-time ones rarely do.
    #
    # A *pair*, because postings write it as a range — "Commitment: 10-40
    # hrs/week" — and a single column would have to discard one end. Same shape
    # as salary_min/salary_max, including the route-level check that the pair
    # is not inverted. A fixed commitment sets both to the same value.
    #
    # Deliberately *not* tied to a particular employment_type: 20 hours a week
    # is as meaningful on a part-time role as on a contract, and a pairing rule
    # here would buy nothing. See KAN-51.
    hours_per_week_min = Column(SmallInteger, nullable=True)
    hours_per_week_max = Column(SmallInteger, nullable=True)

    # Nullable: a job can be tracked before it is applied for, in which case
    # there is no date yet and the status is `interested`. See KAN-31 and
    # REQUIREMENTS.md §2.
    date_applied = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)

    # What is owed next and when — turns the list into a worklist rather than
    # a log. See REQUIREMENTS.md §2.
    next_action = Column(String(255), nullable=True)
    next_action_date = Column(Date, nullable=True)

    # Snapshot of the posting, which outlives the job_link once the ad is taken
    # down mid-process.
    job_description = Column(Text, nullable=True)

    # What was written to this employer. Text rather than an uploaded file: a
    # PDF can be regenerated from it, and a column rides the existing encrypted
    # backup instead of needing a second store. See REQUIREMENTS.md §2.
    cover_letter = Column(Text, nullable=True)

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

    status_changes = relationship(
        "StatusChange",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="StatusChange.changed_at",
    )


class StatusChange(Base):
    """One row per status transition (KAN-42).

    Nothing reads this yet. It exists because history cannot be reconstructed
    after the fact: the applications table holds only the current status, and
    `updated_at` says when a row last changed rather than what it changed from.

    `changed_at` is when the *record* was edited, not when the thing happened.
    A rejection email left unread for a week charges that week to the previous
    status. Good enough for "three weeks in Applied"; not for "five days in
    phone screen". See REQUIREMENTS.md §3 for the deferred fix.
    """

    __tablename__ = "status_changes"

    # Declared here rather than as index=True on the column, because both are
    # composite and both exist for a specific read: the timeline walks one
    # application in order, the graph walks a date range for one status.
    # Declaring them on the model is also what keeps `alembic check` clean.
    __table_args__ = (
        Index("ix_status_changes_application", "application_id", "changed_at"),
        Index("ix_status_changes_status_date", "to_status", "changed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer,
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )

    # NULL means the history starts here rather than a transition: the
    # application was just created, or it predates the table.
    from_status = Column(Enum(ApplicationStatus), nullable=True)
    to_status = Column(Enum(ApplicationStatus), nullable=False)
    changed_at = Column(DateTime, server_default=func.now(), nullable=False)

    application = relationship("Application", back_populates="status_changes")


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
