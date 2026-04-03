import os
from datetime import date, datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Enum as SAEnum
import enum

db = SQLAlchemy()


class ContactStatus(enum.Enum):
    pending = "pending"
    sent = "sent"
    accepted = "accepted"
    withdrawn = "withdrawn"
    failed = "failed"


class Contact(db.Model):
    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    linkedin_url = db.Column(db.String(500), nullable=False, unique=True)
    company = db.Column(db.String(200))
    title = db.Column(db.String(200))
    status = db.Column(
        SAEnum(ContactStatus),
        nullable=False,
        default=ContactStatus.pending,
    )
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_sent = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text)
    message_sent = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "first_name": self.first_name,
            "linkedin_url": self.linkedin_url,
            "company": self.company,
            "title": self.title,
            "status": self.status.value if self.status else None,
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "date_sent": self.date_sent.isoformat() if self.date_sent else None,
            "notes": self.notes,
            "message_sent": self.message_sent,
        }


class DailyStat(db.Model):
    __tablename__ = "daily_stats"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, default=date.today)
    sent_count = db.Column(db.Integer, nullable=False, default=0)
    max_count = db.Column(db.Integer, nullable=False, default=20)

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "sent_count": self.sent_count,
            "max_count": self.max_count,
        }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_db():
    """Return the SQLAlchemy db instance."""
    return db


def add_contact(
    name: str,
    linkedin_url: str,
    company: str = None,
    title: str = None,
    notes: str = None,
    first_name: str = None,
) -> Contact:
    """Create and persist a new Contact record."""
    if first_name is None:
        first_name = name.strip().split()[0] if name.strip() else name

    # Normalise URL – strip trailing slashes
    linkedin_url = linkedin_url.strip().rstrip("/")

    contact = Contact(
        name=name.strip(),
        first_name=first_name.strip(),
        linkedin_url=linkedin_url,
        company=company.strip() if company else None,
        title=title.strip() if title else None,
        notes=notes.strip() if notes else None,
        status=ContactStatus.pending,
    )
    db.session.add(contact)
    db.session.commit()
    return contact


def get_contacts(status: str = None, page: int = 1, per_page: int = 50):
    """Return a pagination object for contacts, optionally filtered by status."""
    query = Contact.query.order_by(Contact.date_added.desc())
    if status and status != "all":
        try:
            status_enum = ContactStatus(status)
            query = query.filter(Contact.status == status_enum)
        except ValueError:
            pass
    return query.paginate(page=page, per_page=per_page, error_out=False)


def get_daily_stats(days: int = 7) -> list:
    """Return DailyStat rows for the last *days* days, newest first."""
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days - 1)
    return (
        DailyStat.query.filter(DailyStat.date >= cutoff)
        .order_by(DailyStat.date.asc())
        .all()
    )


def update_contact_status(
    contact_id: int,
    status: str,
    message_sent: str = None,
    notes: str = None,
) -> Contact:
    """Update the status (and optionally message/notes) of a contact."""
    contact = Contact.query.get(contact_id)
    if contact is None:
        raise ValueError(f"Contact {contact_id} not found")

    contact.status = ContactStatus(status)
    if status == "sent":
        contact.date_sent = datetime.utcnow()
    if message_sent is not None:
        contact.message_sent = message_sent
    if notes is not None:
        contact.notes = notes

    db.session.commit()
    return contact


def get_today_sent_count() -> int:
    """Return how many connection requests have been sent today."""
    today = date.today()
    stat = DailyStat.query.filter_by(date=today).first()
    return stat.sent_count if stat else 0


def _get_or_create_daily_stat(today: date = None) -> DailyStat:
    if today is None:
        today = date.today()
    daily_limit = int(os.getenv("DAILY_LIMIT", 20))
    stat = DailyStat.query.filter_by(date=today).first()
    if stat is None:
        stat = DailyStat(date=today, sent_count=0, max_count=daily_limit)
        db.session.add(stat)
        db.session.commit()
    return stat


def increment_daily_sent_count() -> DailyStat:
    """Increment today's sent count by 1, creating the row if needed."""
    stat = _get_or_create_daily_stat()
    stat.sent_count += 1
    db.session.commit()
    return stat


def get_contacts_to_send() -> list:
    """
    Return pending contacts up to the remaining daily limit for today.
    """
    daily_limit = int(os.getenv("DAILY_LIMIT", 20))
    today_count = get_today_sent_count()
    remaining = daily_limit - today_count
    if remaining <= 0:
        return []

    return (
        Contact.query.filter_by(status=ContactStatus.pending)
        .order_by(Contact.date_added.asc())
        .limit(remaining)
        .all()
    )
