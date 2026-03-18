"""
NIJA Email Service

Sends transactional emails for:
- Email address verification
- Password reset
- Login notifications
- Subscription events

Supports SMTP (Gmail, SendGrid SMTP relay, or any provider) via environment
variables.  Falls back to console logging when SMTP is not configured so that
development/testing works without an email server.

Required environment variables (for live delivery):
    SMTP_HOST        - e.g. smtp.sendgrid.net  or  smtp.gmail.com
    SMTP_PORT        - e.g. 587
    SMTP_USERNAME    - e.g. apikey  (SendGrid)  or  your@gmail.com
    SMTP_PASSWORD    - SMTP password / API key
    EMAIL_FROM       - From address shown to recipients
    EMAIL_FROM_NAME  - Friendly sender name (default: NIJA Trading)
    APP_BASE_URL     - Base URL for links in emails (e.g. https://app.nija.trading)

Author: NIJA Trading Systems
Version: 1.0
"""

import os
import logging
import sqlite3
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger("nija.auth.email_service")

# ---------------------------------------------------------------------------
# Configuration (resolved from environment at module load time)
# ---------------------------------------------------------------------------

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@nija.trading")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "NIJA Trading")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://app.nija.trading")

# How long an email-verification token remains valid
VERIFY_TOKEN_TTL_HOURS = 24
RESET_TOKEN_TTL_HOURS = 2


class EmailService:
    """
    Transactional email sender with SQLite token persistence.
    """

    def __init__(self, db_path: str = "users.db"):
        self.db_path = db_path
        self._init_tables()
        smtp_available = bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD)
        if smtp_available:
            logger.info(f"EmailService ready (SMTP {SMTP_HOST}:{SMTP_PORT})")
        else:
            logger.warning(
                "SMTP not configured – emails will be logged to console only. "
                "Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD to enable delivery."
            )

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_tables(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                token       TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                email       TEXT NOT NULL,
                purpose     TEXT NOT NULL DEFAULT 'verify',
                created_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                used        INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_verification_email(self, user_id: str, email: str) -> str:
        """
        Issue a verification token and send a verification email.

        Returns the plain-text token (useful for testing / logging).
        """
        token = self._create_token(user_id, email, purpose="verify",
                                   ttl_hours=VERIFY_TOKEN_TTL_HOURS)
        verify_url = f"{APP_BASE_URL}/verify-email?token={token}"

        subject = "Verify your NIJA account email"
        html = f"""
        <p>Hi,</p>
        <p>Please verify your email address to activate your NIJA account.</p>
        <p>
            <a href="{verify_url}" style="
                display:inline-block;padding:12px 24px;background:#1a73e8;
                color:#fff;border-radius:4px;text-decoration:none;font-weight:bold;">
                Verify Email
            </a>
        </p>
        <p>This link expires in {VERIFY_TOKEN_TTL_HOURS} hours.</p>
        <p>If you did not create a NIJA account, please ignore this email.</p>
        <hr/>
        <p style="font-size:12px;color:#888;">
            NIJA Trading &mdash; Autonomous Crypto Trading Platform
        </p>
        """
        text = (
            f"Verify your NIJA email: {verify_url}\n"
            f"This link expires in {VERIFY_TOKEN_TTL_HOURS} hours."
        )

        self._send(to=email, subject=subject, html=html, text=text)
        logger.info(f"Verification email dispatched to {email} (user={user_id})")
        return token

    def send_password_reset_email(self, user_id: str, email: str) -> str:
        """Issue a password-reset token and send an email. Returns the token."""
        token = self._create_token(user_id, email, purpose="reset",
                                   ttl_hours=RESET_TOKEN_TTL_HOURS)
        reset_url = f"{APP_BASE_URL}/reset-password?token={token}"

        subject = "Reset your NIJA password"
        html = f"""
        <p>Hi,</p>
        <p>We received a request to reset your NIJA account password.</p>
        <p>
            <a href="{reset_url}" style="
                display:inline-block;padding:12px 24px;background:#e53935;
                color:#fff;border-radius:4px;text-decoration:none;font-weight:bold;">
                Reset Password
            </a>
        </p>
        <p>This link expires in {RESET_TOKEN_TTL_HOURS} hours.</p>
        <p>If you did not request a password reset, please ignore this email and
           consider changing your password immediately.</p>
        """
        text = (
            f"Reset your NIJA password: {reset_url}\n"
            f"This link expires in {RESET_TOKEN_TTL_HOURS} hours."
        )

        self._send(to=email, subject=subject, html=html, text=text)
        logger.info(f"Password-reset email dispatched to {email} (user={user_id})")
        return token

    def send_login_notification(self, email: str, ip_address: str, user_agent: str = "") -> None:
        """Send a notification email when a new login is detected."""
        subject = "New login to your NIJA account"
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        html = f"""
        <p>Hi,</p>
        <p>A new login was detected for your NIJA account:</p>
        <ul>
            <li><strong>Time:</strong> {timestamp}</li>
            <li><strong>IP Address:</strong> {ip_address}</li>
            <li><strong>Device:</strong> {user_agent or 'Unknown'}</li>
        </ul>
        <p>If this was not you, please change your password immediately and
           contact <a href="mailto:security@nija.trading">security@nija.trading</a>.</p>
        """
        text = (
            f"New NIJA login at {timestamp} from IP {ip_address}.\n"
            "If this was not you, change your password immediately."
        )
        self._send(to=email, subject=subject, html=html, text=text)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def verify_token(self, token: str, purpose: str = "verify") -> Optional[str]:
        """
        Validate a token and mark it used.

        Returns the associated user_id on success, None on failure.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, expires_at, used
            FROM email_verification_tokens
            WHERE token = ? AND purpose = ?
        """, (token, purpose))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        user_id, expires_at_str, used = row

        if used:
            conn.close()
            logger.warning(f"Token already used: {token[:8]}…")
            return None

        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.utcnow() > expires_at:
            conn.close()
            logger.warning(f"Token expired: {token[:8]}…")
            return None

        cursor.execute(
            "UPDATE email_verification_tokens SET used = 1 WHERE token = ?",
            (token,)
        )
        conn.commit()
        conn.close()
        return user_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_token(
        self,
        user_id: str,
        email: str,
        purpose: str,
        ttl_hours: int,
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        expires = now + timedelta(hours=ttl_hours)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Invalidate any previous unused tokens for same user+purpose
        cursor.execute("""
            UPDATE email_verification_tokens
            SET used = 1
            WHERE user_id = ? AND purpose = ? AND used = 0
        """, (user_id, purpose))
        cursor.execute("""
            INSERT INTO email_verification_tokens
                (token, user_id, email, purpose, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (token, user_id, email, purpose, now.isoformat(), expires.isoformat()))
        conn.commit()
        conn.close()
        return token

    def _send(self, to: str, subject: str, html: str, text: str) -> None:
        """Send an email via SMTP, or log to console if SMTP is unconfigured."""
        if not (SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD):
            logger.info(
                "[EMAIL - console fallback]\n"
                f"  To:      {to}\n"
                f"  Subject: {subject}\n"
                f"  Body:    {text}"
            )
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>"
        msg["To"] = to
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(EMAIL_FROM, [to], msg.as_string())
            logger.debug(f"Email sent to {to}: {subject}")
        except Exception as exc:
            logger.error(f"Failed to send email to {to}: {exc}")
            raise


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[EmailService] = None


def get_email_service(db_path: str = "users.db") -> EmailService:
    """Return the module-level EmailService singleton."""
    global _instance
    if _instance is None:
        _instance = EmailService(db_path=db_path)
    return _instance
