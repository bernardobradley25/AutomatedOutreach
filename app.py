"""
Flask web dashboard for LinkedIn outreach automation.
"""

import io
import logging
import os
import threading
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    Response,
)
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///outreach.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialise the shared db instance from database.py
from database import db, Contact, ContactStatus, DailyStat
from database import (
    add_contact,
    get_contacts,
    get_daily_stats,
    update_contact_status,
    get_today_sent_count,
    get_contacts_to_send,
    increment_daily_sent_count,
)

db.init_app(app)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App startup
# ---------------------------------------------------------------------------

def create_tables():
    with app.app_context():
        db.create_all()

create_tables()

# Start the scheduler when the module loads (skip in reloader child process)
from scheduler import start_scheduler, shutdown_scheduler, get_next_run_time
import atexit

if os.environ.get("WERKZEUG_RUN_MAIN") != "false":
    start_scheduler(app)
    atexit.register(shutdown_scheduler)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_stats():
    """Return a dict of dashboard statistics."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    today_sent = get_today_sent_count()
    daily_limit = int(os.getenv("DAILY_LIMIT", 20))

    total_sent = db.session.query(db.func.count(Contact.id)).filter(
        Contact.status.in_([ContactStatus.sent, ContactStatus.accepted])
    ).scalar() or 0

    week_sent = (
        db.session.query(db.func.count(Contact.id))
        .filter(Contact.date_sent >= week_start)
        .scalar()
        or 0
    )

    pending_count = (
        db.session.query(db.func.count(Contact.id))
        .filter(Contact.status == ContactStatus.pending)
        .scalar()
        or 0
    )

    accepted_count = (
        db.session.query(db.func.count(Contact.id))
        .filter(Contact.status == ContactStatus.accepted)
        .scalar()
        or 0
    )

    failed_count = (
        db.session.query(db.func.count(Contact.id))
        .filter(Contact.status == ContactStatus.failed)
        .scalar()
        or 0
    )

    withdrawn_count = (
        db.session.query(db.func.count(Contact.id))
        .filter(Contact.status == ContactStatus.withdrawn)
        .scalar()
        or 0
    )

    # Weekly bar chart data (last 7 days)
    daily_stats = get_daily_stats(7)
    chart_labels = []
    chart_data = []
    for i in range(7):
        day = today - timedelta(days=6 - i)
        chart_labels.append(day.strftime("%a %m/%d"))
        stat = next((s for s in daily_stats if s.date == day), None)
        chart_data.append(stat.sent_count if stat else 0)

    return {
        "today_sent": today_sent,
        "daily_limit": daily_limit,
        "week_sent": week_sent,
        "total_sent": total_sent,
        "pending_count": pending_count,
        "accepted_count": accepted_count,
        "failed_count": failed_count,
        "withdrawn_count": withdrawn_count,
        "chart_labels": chart_labels,
        "chart_data": chart_data,
    }


# ---------------------------------------------------------------------------
# Routes – Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    stats = _build_stats()
    recent_contacts = (
        Contact.query.filter(
            Contact.status.in_([ContactStatus.sent, ContactStatus.accepted])
        )
        .order_by(Contact.date_sent.desc())
        .limit(10)
        .all()
    )
    next_run = get_next_run_time()
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_contacts=recent_contacts,
        next_run=next_run,
    )


# ---------------------------------------------------------------------------
# Routes – Contacts
# ---------------------------------------------------------------------------

@app.route("/contacts")
def contacts():
    status_filter = request.args.get("status", "all")
    page = request.args.get("page", 1, type=int)
    pagination = get_contacts(status=status_filter, page=page, per_page=50)
    return render_template(
        "contacts.html",
        contacts=pagination.items,
        pagination=pagination,
        status_filter=status_filter,
        statuses=[s.value for s in ContactStatus],
    )


@app.route("/contacts/add", methods=["POST"])
def add_contact_route():
    name = request.form.get("name", "").strip()
    linkedin_url = request.form.get("linkedin_url", "").strip()
    company = request.form.get("company", "").strip()
    title = request.form.get("title", "").strip()
    notes = request.form.get("notes", "").strip()

    if not name or not linkedin_url:
        flash("Name and LinkedIn URL are required.", "danger")
        return redirect(url_for("contacts"))

    try:
        add_contact(
            name=name,
            linkedin_url=linkedin_url,
            company=company or None,
            title=title or None,
            notes=notes or None,
        )
        flash(f"Contact '{name}' added successfully.", "success")
    except Exception as exc:
        flash(f"Error adding contact: {exc}", "danger")

    return redirect(url_for("contacts"))


@app.route("/contacts/import", methods=["GET", "POST"])
def import_contacts():
    if request.method == "GET":
        return render_template("import.html")

    file = request.files.get("csv_file")
    if not file or not file.filename.endswith(".csv"):
        flash("Please upload a valid CSV file.", "danger")
        return redirect(url_for("import_contacts"))

    try:
        df = pd.read_csv(file)
        df.columns = [c.strip().lower() for c in df.columns]

        required = {"name", "linkedin_url"}
        if not required.issubset(set(df.columns)):
            flash("CSV must have at least 'name' and 'linkedin_url' columns.", "danger")
            return redirect(url_for("import_contacts"))

        added = 0
        skipped = 0
        errors = []
        for _, row in df.iterrows():
            try:
                add_contact(
                    name=str(row.get("name", "")).strip(),
                    linkedin_url=str(row.get("linkedin_url", "")).strip(),
                    company=str(row.get("company", "")).strip() or None,
                    title=str(row.get("title", "")).strip() or None,
                    notes=str(row.get("notes", "")).strip() or None,
                )
                added += 1
            except Exception as exc:
                skipped += 1
                errors.append(str(exc))

        msg = f"Imported {added} contact(s)."
        if skipped:
            msg += f" Skipped {skipped} (duplicates or errors)."
        flash(msg, "success" if added else "warning")

    except Exception as exc:
        flash(f"Failed to parse CSV: {exc}", "danger")

    return redirect(url_for("contacts"))


@app.route("/contacts/export")
def export_contacts():
    contacts_all = Contact.query.order_by(Contact.date_added.desc()).all()
    rows = [c.to_dict() for c in contacts_all]
    df = pd.DataFrame(rows)
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts_export.csv"},
    )


@app.route("/contacts/<int:contact_id>/update", methods=["POST"])
def update_contact(contact_id):
    status = request.form.get("status")
    notes = request.form.get("notes")

    try:
        contact = Contact.query.get_or_404(contact_id)
        if status and status in [s.value for s in ContactStatus]:
            contact.status = ContactStatus(status)
        if notes is not None:
            contact.notes = notes.strip() or None
        db.session.commit()
        flash("Contact updated.", "success")
    except Exception as exc:
        flash(f"Update failed: {exc}", "danger")

    return redirect(request.referrer or url_for("contacts"))


@app.route("/contacts/<int:contact_id>/delete", methods=["POST"])
def delete_contact(contact_id):
    try:
        contact = Contact.query.get_or_404(contact_id)
        db.session.delete(contact)
        db.session.commit()
        flash(f"Contact '{contact.name}' deleted.", "success")
    except Exception as exc:
        flash(f"Delete failed: {exc}", "danger")

    return redirect(request.referrer or url_for("contacts"))


# ---------------------------------------------------------------------------
# Routes – Outreach
# ---------------------------------------------------------------------------

@app.route("/outreach/run", methods=["POST"])
def run_outreach():
    """Manually trigger an outreach run in a background thread."""
    def _run():
        from linkedin_bot import LinkedInBot
        bot = LinkedInBot()
        bot.run_daily_outreach(app=app)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    flash("Outreach run started in the background. Check bot.log for progress.", "info")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Routes – API
# ---------------------------------------------------------------------------

@app.route("/api/stats")
def api_stats():
    stats = _build_stats()
    return jsonify(stats)


@app.route("/api/contacts")
def api_contacts():
    status_filter = request.args.get("status", "all")
    page = request.args.get("page", 1, type=int)
    pagination = get_contacts(status=status_filter, page=page, per_page=50)
    return jsonify({
        "contacts": [c.to_dict() for c in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "page": pagination.page,
    })


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("base.html", error="Page not found (404)"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("base.html", error=f"Internal server error: {e}"), 500
