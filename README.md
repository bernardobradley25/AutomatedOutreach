# AutomatedOutreach

A LinkedIn connection request automation system with a local web dashboard, browser automation via Playwright, SQLite contact tracking, and Mon–Fri scheduling.

## Quick Start

### 1. Copy and configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```
LINKEDIN_EMAIL=you@example.com
LINKEDIN_PASSWORD=yourpassword
DAILY_LIMIT=20
HEADLESS=true
MESSAGE_TEMPLATE=Hi {first_name}, I came across your profile and would love to connect!
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browser

```bash
playwright install chromium
```

### 4. Run the application

```bash
python run.py
```

### 5. Open the dashboard

Navigate to [http://localhost:5000](http://localhost:5000)

---

## Features

- **Dashboard** – Live stats: today's sends, weekly total, pending count, bar/pie charts
- **Contact management** – Add, edit, delete contacts; filter by status
- **CSV import/export** – Bulk import contacts with a preview before committing
- **Automated scheduler** – Runs connection requests Mon–Fri at 9:00 AM automatically
- **Manual trigger** – Run outreach on demand via the dashboard
- **Session persistence** – Playwright session saved to `session.json` to avoid repeated logins
- **2FA support** – Pauses and waits for manual 2FA completion when detected

---

## Project Structure

```
AutomatedOutreach/
├── app.py              # Flask web application & routes
├── database.py         # SQLAlchemy models & DB helpers
├── linkedin_bot.py     # Playwright LinkedIn automation bot
├── scheduler.py        # APScheduler Mon–Fri job configuration
├── run.py              # Entry point
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── outreach.db         # SQLite database (auto-created)
├── bot.log             # Bot activity log (auto-created)
├── session.json        # Saved browser session (auto-created)
├── static/
│   └── style.css       # Custom CSS (Bootstrap 5 dark theme)
└── templates/
    ├── base.html        # Base layout with sidebar
    ├── dashboard.html   # Dashboard with charts
    ├── contacts.html    # Contacts list & management
    ├── import.html      # CSV import page
    └── _status_badge.html  # Reusable status badge partial
```

---

## CSV Import Format

| Column | Required | Description |
|--------|----------|-------------|
| `name` | Yes | Full name |
| `linkedin_url` | Yes | Full LinkedIn profile URL |
| `company` | No | Employer |
| `title` | No | Job title |
| `notes` | No | Personal notes |

Example:
```csv
name,linkedin_url,company,title,notes
Jane Smith,https://linkedin.com/in/janesmith,Acme Corp,VP Engineering,Met at SaaStr
Bob Jones,https://linkedin.com/in/bobjones,Widgets Inc,CTO,
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LINKEDIN_EMAIL` | — | Your LinkedIn login email |
| `LINKEDIN_PASSWORD` | — | Your LinkedIn login password |
| `DAILY_LIMIT` | `20` | Max connection requests per day |
| `HEADLESS` | `true` | Run browser headlessly (`true`/`false`) |
| `MESSAGE_TEMPLATE` | (see .env.example) | Personalised note template; `{first_name}` is replaced |

---

## Status Definitions

| Status | Meaning |
|--------|---------|
| `pending` | Queued, not yet sent |
| `sent` | Request dispatched |
| `accepted` | Contact accepted the request |
| `withdrawn` | Request withdrawn |
| `failed` | Bot could not send the request |

---

## Notes

- LinkedIn may require 2FA on first login; the bot will pause and wait up to 5 minutes for you to complete it in the browser window.
- Set `HEADLESS=false` to watch the browser while debugging.
- Bot activity is logged to `bot.log`.
- The SQLite database is stored as `outreach.db` in the project root.
- The scheduler uses `America/New_York` timezone by default; edit `scheduler.py` to change it.
