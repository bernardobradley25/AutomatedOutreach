"""
LinkedIn automation bot using Playwright.

All browser interactions include randomised, human-like delays.
Actions are logged to bot.log in the project root.
"""

import json
import logging
import os
import random
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_PATH = Path(__file__).parent / "bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

SESSION_FILE = Path(__file__).parent / "session.json"

# ---------------------------------------------------------------------------
# Bot class
# ---------------------------------------------------------------------------

class LinkedInBot:
    def __init__(self):
        self.email = os.getenv("LINKEDIN_EMAIL", "")
        self.password = os.getenv("LINKEDIN_PASSWORD", "")
        self.headless = os.getenv("HEADLESS", "true").lower() == "true"
        self.message_template = os.getenv(
            "MESSAGE_TEMPLATE",
            "Hi {first_name}, I came across your profile and would love to connect!",
        )
        self.daily_limit = int(os.getenv("DAILY_LIMIT", 20))

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _random_delay(self, min_s: float = 2.0, max_s: float = 5.0):
        """Sleep for a random duration to mimic human behaviour."""
        delay = random.uniform(min_s, max_s)
        logger.debug(f"Sleeping {delay:.1f}s")
        time.sleep(delay)

    def _start_browser(self):
        """Launch Playwright browser (called lazily)."""
        from playwright.sync_api import sync_playwright  # local import to avoid issues

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    def _new_context(self, storage_state=None):
        kwargs = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if storage_state:
            kwargs["storage_state"] = storage_state
        self._context = self._browser.new_context(**kwargs)
        self._page = self._context.new_page()

    def _close(self):
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as exc:
            logger.warning(f"Error during browser teardown: {exc}")
        finally:
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None

    def _is_logged_in(self) -> bool:
        """Check whether the current page session is authenticated."""
        try:
            self._page.goto("https://www.linkedin.com/feed/", timeout=20_000)
            self._random_delay(2, 4)
            url = self._page.url
            return "feed" in url or "mynetwork" in url
        except Exception as exc:
            logger.warning(f"Login check failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_session(self) -> bool:
        """
        Attempt to restore a previous session from session.json.
        Returns True if the session is still valid.
        """
        if not SESSION_FILE.exists():
            logger.info("No session file found.")
            return False

        try:
            with open(SESSION_FILE) as f:
                storage_state = json.load(f)

            self._start_browser()
            self._new_context(storage_state=storage_state)

            if self._is_logged_in():
                logger.info("Session restored successfully.")
                return True
            else:
                logger.info("Saved session is expired or invalid.")
                self._close()
                return False
        except Exception as exc:
            logger.error(f"Failed to load session: {exc}")
            self._close()
            return False

    def login(self) -> bool:
        """
        Perform a fresh LinkedIn login.
        Saves session cookies to session.json on success.
        Waits for manual 2FA if the checkpoint page appears.
        """
        if not self.email or not self.password:
            logger.error("LINKEDIN_EMAIL and LINKEDIN_PASSWORD must be set in .env")
            return False

        try:
            if self._browser is None:
                self._start_browser()
            self._new_context()

            page = self._page
            logger.info("Navigating to LinkedIn login page…")
            page.goto("https://www.linkedin.com/login", timeout=30_000)
            self._random_delay(1.5, 3)

            # Fill credentials
            page.fill("#username", self.email)
            self._random_delay(0.5, 1.5)
            page.fill("#password", self.password)
            self._random_delay(0.5, 1.5)
            page.click('[type="submit"]')
            self._random_delay(3, 6)

            # Handle 2FA / verification checkpoint
            if "checkpoint" in page.url or "challenge" in page.url:
                logger.warning(
                    "2FA / CAPTCHA detected. Complete verification in the browser, "
                    "then this process will continue automatically (timeout: 5 min)."
                )
                # Wait up to 5 minutes for the user to complete 2FA
                for _ in range(60):
                    time.sleep(5)
                    if "feed" in page.url or "mynetwork" in page.url:
                        break
                else:
                    logger.error("Timed out waiting for 2FA completion.")
                    return False

            if "feed" not in page.url and "mynetwork" not in page.url:
                logger.error(f"Login failed – ended up at: {page.url}")
                return False

            # Persist session
            storage_state = self._context.storage_state()
            with open(SESSION_FILE, "w") as f:
                json.dump(storage_state, f)
            logger.info(f"Login successful. Session saved to {SESSION_FILE}")
            return True

        except Exception as exc:
            logger.error(f"Login error: {exc}")
            return False

    def send_connection_request(self, contact) -> bool:
        """
        Visit a contact's LinkedIn profile and send a connection request
        with a personalised note.

        Returns True on success, False on failure.
        """
        page = self._page
        url = contact.linkedin_url

        try:
            logger.info(f"Visiting profile: {url} ({contact.name})")
            page.goto(url, timeout=30_000)
            self._random_delay(3, 6)

            # Dismiss any "Add to your feed" / sign-in overlay
            try:
                dismiss = page.locator('[aria-label="Dismiss"]').first
                if dismiss.is_visible(timeout=2_000):
                    dismiss.click()
                    self._random_delay(1, 2)
            except Exception:
                pass

            # ----------------------------------------------------------
            # Find the Connect button
            # Strategy 1: visible "Connect" button in top action area
            # Strategy 2: "More" dropdown → "Connect"
            # ----------------------------------------------------------
            connect_clicked = False

            # Strategy 1 – direct Connect button
            connect_btn = page.locator(
                'button:has-text("Connect")'
            ).first
            try:
                if connect_btn.is_visible(timeout=4_000):
                    connect_btn.click()
                    connect_clicked = True
                    logger.info("Clicked direct Connect button.")
            except Exception:
                pass

            # Strategy 2 – "More" dropdown
            if not connect_clicked:
                try:
                    more_btn = page.locator(
                        'button:has-text("More")'
                    ).first
                    if more_btn.is_visible(timeout=4_000):
                        more_btn.click()
                        self._random_delay(1, 2)
                        connect_option = page.locator(
                            '[role="option"]:has-text("Connect"), '
                            'li:has-text("Connect") > *'
                        ).first
                        if connect_option.is_visible(timeout=3_000):
                            connect_option.click()
                            connect_clicked = True
                            logger.info("Clicked Connect via More dropdown.")
                except Exception:
                    pass

            if not connect_clicked:
                logger.warning(f"Could not find Connect button for {contact.name} at {url}")
                return False

            self._random_delay(2, 4)

            # ----------------------------------------------------------
            # Add a personalised note
            # ----------------------------------------------------------
            message = self.message_template.format(
                first_name=contact.first_name or contact.name.split()[0],
                name=contact.name or "",
                company=contact.company or "",
                title=contact.title or "",
            )

            try:
                add_note_btn = page.locator(
                    'button:has-text("Add a note"), [aria-label="Add a note"]'
                ).first
                if add_note_btn.is_visible(timeout=3_000):
                    add_note_btn.click()
                    self._random_delay(1, 2)
                    note_field = page.locator(
                        'textarea[name="message"], textarea#custom-message'
                    ).first
                    if note_field.is_visible(timeout=3_000):
                        note_field.fill(message)
                        self._random_delay(1, 2)
            except Exception as exc:
                logger.warning(f"Could not add note: {exc} – sending without note.")
                message = None

            # ----------------------------------------------------------
            # Submit the connection request
            # ----------------------------------------------------------
            try:
                send_btn = page.locator(
                    'button:has-text("Send"), [aria-label="Send now"]'
                ).first
                if send_btn.is_visible(timeout=4_000):
                    send_btn.click()
                    self._random_delay(2, 4)
                    logger.info(f"Connection request sent to {contact.name}.")
                    return True
            except Exception as exc:
                logger.error(f"Failed to click Send for {contact.name}: {exc}")
                return False

            # If the dialog closed without finding "Send", assume success
            # (LinkedIn sometimes auto-sends without a note dialog)
            logger.info(f"Assumed success for {contact.name} (dialog closed).")
            return True

        except Exception as exc:
            logger.error(f"Error sending request to {contact.name}: {exc}")
            return False

    def run_daily_outreach(self, app=None) -> dict:
        """
        Main entry point for automated outreach.

        Loads (or creates) a browser session, retrieves pending contacts up to
        the daily limit, sends connection requests, and updates the database.

        Pass the Flask *app* instance so we can use the app context when
        updating the DB from a background thread.

        Returns a summary dict: {sent, failed, skipped}.
        """
        from database import get_contacts_to_send, update_contact_status, increment_daily_sent_count

        summary = {"sent": 0, "failed": 0, "skipped": 0}

        def _run():
            # Try to restore saved session; fall back to fresh login
            if not self.load_session():
                logger.info("Attempting fresh login…")
                if not self.login():
                    logger.error("Cannot proceed without a valid LinkedIn session.")
                    return

            with (app.app_context() if app else _null_context()):
                contacts = get_contacts_to_send()

            if not contacts:
                logger.info("No pending contacts to process today.")
                self._close()
                return

            logger.info(f"Processing {len(contacts)} contact(s) today.")

            for contact in contacts:
                success = self.send_connection_request(contact)
                with (app.app_context() if app else _null_context()):
                    if success:
                        update_contact_status(contact.id, "sent")
                        increment_daily_sent_count()
                        summary["sent"] += 1
                    else:
                        update_contact_status(contact.id, "failed")
                        summary["failed"] += 1

                # Human-like pause between requests
                self._random_delay(3, 8)

            self._close()
            logger.info(
                f"Daily outreach complete. "
                f"Sent: {summary['sent']}, Failed: {summary['failed']}"
            )

        try:
            _run()
        except Exception as exc:
            logger.error(f"Unexpected error in run_daily_outreach: {exc}")
            self._close()

        return summary


# ---------------------------------------------------------------------------
# Context manager helper for non-Flask threads
# ---------------------------------------------------------------------------

class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
