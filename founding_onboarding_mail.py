"""Approved-member onboarding invitations via a durable, idempotent outbox.

Not a login, Stripe ownership, entitlement or live-trading authorization service.
A trusted caller must independently establish approval and email verification.
"""
import hashlib
import base64
import hmac
import json
import logging
import os
import sqlite3
import time
import urllib.request
from contextlib import contextmanager
from typing import Iterator

REGISTER = "https://nijaaitrading.com/register"
LOGIN = "https://nijaaitrading.com/login"
SUBJECT = "NIJA Founding 100 — registration and brokerage choices"
log = logging.getLogger("nija.onboarding")
EVENTS = {"application.received", "enrollment.approved", "identity.registered"}


def verify_resend_event(body: bytes, headers, secret: str, *, now=None) -> dict:
    """Verify Resend's Svix signature over the original bytes, with a five-minute tolerance."""
    now = int(time.time()) if now is None else int(now)
    try:
        event_id = headers["svix-id"]
        timestamp = headers["svix-timestamp"]
        if not secret.startswith("whsec_") or abs(now - int(timestamp)) > 300:
            raise ValueError("invalid_webhook")
        key = base64.b64decode(secret[6:], validate=True)
        if not key or not event_id:
            raise ValueError("invalid_webhook")
        signed = event_id.encode() + b"." + timestamp.encode() + b"." + body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        if not any(hmac.compare_digest(part, "v1," + expected)
                   for part in headers["svix-signature"].split()):
            raise ValueError("invalid_webhook")
        event = json.loads(body)
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            raise ValueError("invalid_webhook")
        return event
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("invalid_webhook") from exc


def normalize_email(email: str) -> str:
    """Validate a canonical, verified address without accepting header-control characters."""
    recipient = str(email).strip().lower()
    if (len(recipient) > 320 or recipient.count("@") != 1
            or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in recipient)
            or any(c in recipient for c in "<>,;")
            or not all(recipient.split("@"))):
        raise ValueError("invalid_email")
    return recipient

def invitation_body():
    return (
        f"Register with your verified application email: {REGISTER}\n"
        f"Already registered? Sign in: {LOGIN}\n"
        "If you already enrolled, do not pay again.\n"
        "Brokerage choices (availability varies): Kraken https://www.kraken.com/ ; "
        "Coinbase https://www.coinbase.com/ ; OKX https://www.okx.com/ ; "
        "Alpaca https://alpaca.markets/ .\n"
        "Do not share passwords or API keys by email. Do not enter keys until "
        "NIJA confirms production testing of the authenticated encrypted connection flow. "
        "Registration alone does not enable brokerage trading.\n"
        "For help contact support@nijaaitrading.com."
    )

class InvitationOutbox:
    def __init__(self, db_path):
        self.db_path = db_path
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS onboarding_mail (
              key TEXT PRIMARY KEY, recipient TEXT NOT NULL,
              status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
              retry_at INTEGER NOT NULL DEFAULT 0,
              provider_id TEXT, error TEXT)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(onboarding_mail)")}
            for name, definition in (
                ("event_type", "TEXT NOT NULL DEFAULT 'enrollment.approved'"),
                ("created_at", "INTEGER NOT NULL DEFAULT 0"),
                ("first_attempt_at", "INTEGER"),
                ("accepted_at", "INTEGER"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE onboarding_mail ADD COLUMN {name} {definition}")
            db.execute("""CREATE TABLE IF NOT EXISTS onboarding_suppression (
                recipient TEXT PRIMARY KEY, reason TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS onboarding_provider_events (
                provider_id TEXT NOT NULL, event_type TEXT NOT NULL,
                PRIMARY KEY(provider_id,event_type))""")
            db.execute("""CREATE TABLE IF NOT EXISTS onboarding_alerts (
                key TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at INTEGER NOT NULL,
                resolved_at INTEGER)""")
            db.execute("""CREATE TABLE IF NOT EXISTS onboarding_members (
                application_id TEXT PRIMARY KEY, member_id TEXT NOT NULL UNIQUE,
                recipient TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
                registered INTEGER NOT NULL DEFAULT 0)""")
            # Backfill address-wide suppression for installations using the original outbox.
            db.execute("""INSERT OR IGNORE INTO onboarding_suppression
                SELECT recipient,'legacy_suppression' FROM onboarding_mail WHERE status='suppressed'""")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Commit/rollback each short transaction and always close its connection."""
        db = sqlite3.connect(self.db_path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, application_id, email, *, approved=False, verified=False):
        if not approved or not verified:
            raise ValueError("verified_approved_application_required")
        recipient = normalize_email(email)
        if not application_id:
            raise ValueError("application_id_required")
        key = hashlib.sha256(("founding-100-invite-v1:" + str(application_id)).encode()).hexdigest()
        with self.connect() as db:
            db.execute("""INSERT OR IGNORE INTO onboarding_mail(key,recipient,status,created_at)
                VALUES (?,?,'queued',?)""", (key, recipient, int(time.time())))
            saved = db.execute("SELECT recipient FROM onboarding_mail WHERE key=?", (key,)).fetchone()[0]
            if saved != recipient:
                raise ValueError("recipient_changed_manual_verification_required")
        return key

    def ingest_identity_event(self, claims: dict) -> str | None:
        """Atomically bind a verified identity event and queue its event-specific instructions.

        The caller must verify a dedicated server-signed assertion first. Neither
        Stripe email addresses nor browser/Zapier form fields are identity proof.
        """
        event_type = claims.get("event_type")
        if event_type not in EVENTS or claims.get("email_verified") is not True:
            raise ValueError("verified_identity_event_required")
        application_id, member_id = claims.get("application_id"), claims.get("sub")
        if not all(isinstance(v, str) and 0 < len(v) <= 128 for v in (application_id, member_id)):
            raise ValueError("identity_required")
        recipient = normalize_email(claims.get("email", ""))
        if event_type == "enrollment.approved" and claims.get("approved") is not True:
            raise ValueError("approved_application_required")
        prefix = "founding-100-invite-v1:" if event_type == "enrollment.approved" else "founding-100-receipt-v1:"
        key = hashlib.sha256((prefix + application_id).encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT member_id,recipient FROM onboarding_members WHERE application_id=?", (application_id,)
            ).fetchone()
            if saved and saved != (member_id, recipient):
                raise ValueError("identity_changed_manual_verification_required")
            db.execute("""INSERT OR IGNORE INTO onboarding_members(application_id,member_id,recipient)
                VALUES (?,?,?)""", (application_id, member_id, recipient))
            # A member ID must not silently bind to a second application.
            if not db.execute("SELECT 1 FROM onboarding_members WHERE application_id=?", (application_id,)).fetchone():
                raise ValueError("member_already_bound")
            if event_type == "identity.registered":
                db.execute("UPDATE onboarding_members SET registered=1 WHERE application_id=?", (application_id,))
                return None
            if event_type == "enrollment.approved":
                db.execute("UPDATE onboarding_members SET approved=1 WHERE application_id=?", (application_id,))
            suppressed = db.execute(
                "SELECT 1 FROM onboarding_suppression WHERE recipient=?", (recipient,)
            ).fetchone()
            db.execute("""INSERT OR IGNORE INTO onboarding_mail
                (key,recipient,status,event_type,created_at) VALUES (?,?,?,?,?)""",
                       (key, recipient, "suppressed" if suppressed else "queued", event_type, int(time.time())))
            saved_recipient = db.execute("SELECT recipient FROM onboarding_mail WHERE key=?", (key,)).fetchone()[0]
            if saved_recipient != recipient:
                raise ValueError("recipient_changed_manual_verification_required")
        return key

    def send(self, key, *, sender=None, api_key=None, now=None, opener=None):
        sender = sender or os.getenv("NIJA_ONBOARDING_SENDER")
        api_key = api_key or os.getenv("RESEND_API_KEY")
        if not sender or not api_key:
            raise RuntimeError("mail_provider_not_configured")
        now = int(time.time()) if now is None else now
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT recipient,status,attempts,retry_at,event_type,first_attempt_at
                FROM onboarding_mail WHERE key=?""", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            recipient, status, attempts, retry_at, event_type, first_attempt_at = row
            if status in ("accepted", "delivered", "suppressed", "failed") or retry_at > now:
                return status
            if db.execute("SELECT 1 FROM onboarding_suppression WHERE recipient=?", (recipient,)).fetchone():
                db.execute("UPDATE onboarding_mail SET status='suppressed' WHERE key=?", (key,))
                return "suppressed"
            # Resend retains idempotency keys for 24 hours. An ambiguous send must
            # never be resubmitted after that window, including after a long outage.
            if (first_attempt_at is not None and now - first_attempt_at >= 23 * 3600
                    or first_attempt_at is None and (status == "sending" or attempts > 0)):
                db.execute("UPDATE onboarding_mail SET status='failed',error='reconcile_before_redrive' WHERE key=?",
                           (key,))
                self._alert(db, key, "reconcile_before_redrive", now)
                return "failed"
            # Lease prevents concurrent workers from double-submitting; provider
            # idempotency key also deduplicates crash/retry submissions.
            db.execute("""UPDATE onboarding_mail SET status='sending',retry_at=?,
                first_attempt_at=COALESCE(first_attempt_at,?) WHERE key=?""", (now + 120, now, key))
        body = invitation_body()
        subject = SUBJECT
        if event_type == "application.received":
            subject = "NIJA Founding 100 — application received"
            body = ("We received your application. This is not enrollment approval or activation.\n"
                    f"Register: {REGISTER}\nAlready registered? Sign in: {LOGIN}\n"
                    "Do not pay again or send passwords or API keys by email.\n")
        payload = json.dumps({"from": sender, "to": [recipient], "subject": subject, "text": body}).encode()
        req = urllib.request.Request("https://api.resend.com/emails", data=payload,
                                     headers={"Authorization":"Bearer "+api_key,
                                              "Content-Type":"application/json",
                                              "Idempotency-Key":key},method="POST")
        try:
            response = (opener or urllib.request.urlopen)(req, timeout=12)
            provider_id = json.loads(response.read().decode())["id"]
            if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 128:
                raise ValueError("provider_response_invalid")
        except Exception as exc:
            # A permanent HTTP 4xx error must not be retried blindly: suppressed
            # recipients and invalid senders require operator intervention.
            code = getattr(exc, "code", None)
            # HTTP 408 means the provider timed out; retry with the same Idempotency-Key.
            # Resend 429 is also transient. Other 4xx responses fail closed.
            permanent = isinstance(code, int) and 400 <= code < 500 and code not in (408, 429)
            state = "failed" if permanent or attempts >= 7 else "retry"
            with self.connect() as db:
                db.execute("""UPDATE onboarding_mail SET status=?,attempts=?,retry_at=?,error=?
                    WHERE key=? AND status='sending'""",
                           (state, attempts+1, now+min(3600, 60*(2**min(attempts,5))),
                            type(exc).__name__, key))
                if state == "failed":
                    self._alert(db, key, "provider_failure", now)
            return state
        with self.connect() as db:
            db.execute("""UPDATE onboarding_mail SET attempts=?,provider_id=?,accepted_at=? WHERE key=?""",
                       (attempts+1,provider_id,now,key))
            db.execute("""UPDATE onboarding_mail SET status='accepted',error=NULL
                WHERE key=? AND status='sending'""", (key,))
            # Webhooks can arrive before the HTTP send response is persisted.
            events = db.execute("SELECT event_type FROM onboarding_provider_events WHERE provider_id=?",
                                (provider_id,)).fetchall()
            for (pending_type,) in events:
                self._apply_provider_event(db, provider_id, pending_type, now)
            state = db.execute("SELECT status FROM onboarding_mail WHERE key=?", (key,)).fetchone()[0]
        return state

    def due_keys(self, *, now=None, limit=25, recipients=None):
        """Get due queued/retry entries for a scheduled trusted worker."""
        now = int(time.time()) if now is None else int(now)
        params = [now]
        recipient_filter = ""
        if recipients is not None:
            recipients = sorted(set(recipients))
            if not recipients:
                return []
            recipient_filter = " AND recipient IN (" + ",".join("?" for _ in recipients) + ")"
            params.extend(recipients)
        params.append(max(1, min(int(limit), 100)))
        with self.connect() as db:
            rows = db.execute(
                "SELECT key FROM onboarding_mail WHERE status IN ('queued','retry','sending') "
                "AND retry_at<=?" + recipient_filter + " ORDER BY retry_at,key LIMIT ?",
                params,
            ).fetchall()
        return [row[0] for row in rows]

    def record_provider_event(self, provider_id, event_type):
        """Record an event ONLY after the webhook caller verifies its signature.

        The HTTP route validates Resend's signature before invoking this method.
        """
        if event_type not in {"email.sent", "email.delivered", "email.bounced", "email.complained",
                              "email.failed", "email.delivery_delayed"}:
            return False
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 128:
            raise ValueError("provider_id_required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO onboarding_provider_events VALUES (?,?)", (provider_id, event_type))
            return self._apply_provider_event(db, provider_id, event_type, int(time.time()))

    def _apply_provider_event(self, db, provider_id, event_type, now):
        row = db.execute("SELECT key,recipient,status FROM onboarding_mail WHERE provider_id=?",
                         (provider_id,)).fetchone()
        if not row:
            return False
        key, recipient, status = row
        if event_type in ("email.bounced", "email.complained"):
            db.execute("INSERT OR IGNORE INTO onboarding_suppression VALUES (?,?)", (recipient, event_type))
            db.execute("""UPDATE onboarding_mail SET status='suppressed',error=?
                WHERE recipient=?""", (event_type, recipient))
            self._alert(db, key, event_type, now)
        elif event_type == "email.failed" and status != "suppressed":
            db.execute("UPDATE onboarding_mail SET status='failed',error=? WHERE key=?", (event_type, key))
            self._alert(db, key, event_type, now)
        elif event_type == "email.delivered" and status not in ("suppressed", "failed"):
            db.execute("UPDATE onboarding_mail SET status='delivered' WHERE key=?", (key,))
            db.execute("UPDATE onboarding_alerts SET resolved_at=? WHERE key=?", (now, key))
        elif event_type == "email.delivery_delayed" and status in ("accepted", "sending"):
            self._alert(db, key, event_type, now)
        return True

    @staticmethod
    def _alert(db, key, reason, now):
        db.execute("""INSERT INTO onboarding_alerts(key,reason,created_at) VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET reason=excluded.reason,resolved_at=NULL""", (key, reason, now))
        log.error("Onboarding mail requires operator attention: key=%s reason=%s", key, reason)

    def alerts(self, *, now=None, threshold=3600) -> list[dict]:
        """Persist and return dead-letter, queue-stall and missing-delivery alerts."""
        now = int(time.time()) if now is None else int(now)
        with self.connect() as db:
            rows = db.execute("""SELECT key FROM onboarding_mail WHERE
                (status IN ('queued','retry','sending') AND created_at<=?) OR
                (status='accepted' AND COALESCE(accepted_at,0)<=?)""",
                              (now - threshold, now - threshold)).fetchall()
            for (key,) in rows:
                self._alert(db, key, "delivery_overdue", now)
            return [dict(zip(("key", "reason", "created_at"), row)) for row in db.execute(
                "SELECT key,reason,created_at FROM onboarding_alerts WHERE resolved_at IS NULL"
            )]

    def redrive(self, key: str, *, now=None) -> None:
        """Retry a dead letter only inside the provider's original deduplication window."""
        now = int(time.time()) if now is None else int(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,first_attempt_at,recipient FROM onboarding_mail WHERE key=?",
                             (key,)).fetchone()
            if (not row or row[0] != "failed" or row[1] is None or now - row[1] >= 23 * 3600
                    or db.execute("SELECT 1 FROM onboarding_suppression WHERE recipient=?", (row[2],)).fetchone()):
                raise ValueError("redrive_requires_provider_reconciliation")
            db.execute("UPDATE onboarding_mail SET status='retry',attempts=0,retry_at=? WHERE key=?", (now, key))
            db.execute("UPDATE onboarding_alerts SET resolved_at=? WHERE key=?", (now, key))

    def member_status(self, member_id: str) -> dict:
        """Return only this immutable owner's lifecycle and mail delivery state."""
        with self.connect() as db:
            member = db.execute("""SELECT recipient,approved,registered,application_id FROM onboarding_members
                WHERE member_id=?""",
                                (member_id,)).fetchone()
            if not member:
                raise KeyError(member_id)
            keys = [hashlib.sha256((prefix + member[3]).encode()).hexdigest() for prefix in
                    ("founding-100-invite-v1:", "founding-100-receipt-v1:")]
            rows = db.execute("SELECT key,event_type,status,error FROM onboarding_mail WHERE key IN (?,?)",
                              keys).fetchall()
            return {"canonical_email": member[0], "approved": bool(member[1]), "registered": bool(member[2]),
                    "messages": [{"key": r[0], "event_type": r[1],
                                  "status": "failed" if r[2] == "suppressed" else
                                  "queued" if r[2] in ("retry", "sending") else r[2],
                                  "suppressed": r[2] == "suppressed", "error": r[3]} for r in rows]}
