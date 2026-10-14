"""Approved-member onboarding invitations via a durable, idempotent outbox.

Not a login, Stripe ownership, entitlement or live-trading authorization service.
A trusted caller must independently establish approval and email verification.
"""
import hashlib
import json
import os
import sqlite3
import time
import urllib.request

REGISTER = "https://nijaaitrading.com/register"
LOGIN = "https://nijaaitrading.com/login"
SUBJECT = "NIJA Founding 100 — registration and brokerage choices"

def invitation_body():
    return (
        f"Register with your verified application email: {REGISTER}\n"
        f"Already registered? Sign in: {LOGIN}\n"
        "If you already enrolled, do not pay again.\n"
        "Brokerage choices (availability varies): Kraken https://www.kraken.com/ ; "
        "Coinbase https://www.coinbase.com/ ; OKX https://www.okx.com/ ; "
        "Alpaca https://alpaca.markets/ .\n"
        "Do not share passwords or API keys by email. Do not enter keys until "
        "the authenticated encrypted connection is verified. "
        "Registration alone does not enable brokerage trading.\n"
        "For help contact support@nijaaitrading.com."
    )

class InvitationOutbox:
    def __init__(self, db_path):
        self.db_path = db_path
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS onboarding_mail (
              key TEXT PRIMARY KEY, recipient TEXT NOT NULL,
              status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
              retry_at INTEGER NOT NULL DEFAULT 0,
              provider_id TEXT, error TEXT)""")

    def connect(self):
        return sqlite3.connect(self.db_path, timeout=15)

    def enqueue(self, application_id, email, *, approved=False, verified=False):
        if not approved or not verified:
            raise ValueError("verified_approved_application_required")
        recipient = str(email).strip().lower()
        if recipient.count("@") != 1 or any(c.isspace() for c in recipient):
            raise ValueError("invalid_email")
        if not application_id:
            raise ValueError("application_id_required")
        key = hashlib.sha256(("founding-100-invite-v1:" + str(application_id)).encode()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO onboarding_mail(key,recipient,status) VALUES (?,?,'queued')",
                       (key, recipient))
            saved = db.execute("SELECT recipient FROM onboarding_mail WHERE key=?", (key,)).fetchone()[0]
            if saved != recipient:
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
            row = db.execute("SELECT recipient,status,attempts,retry_at FROM onboarding_mail WHERE key=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            recipient, status, attempts, retry_at = row
            if status in ("accepted", "delivered", "suppressed") or retry_at > now:
                return status
            # Lease prevents concurrent workers from double-submitting; provider
            # idempotency key also deduplicates crash/retry submissions.
            db.execute("UPDATE onboarding_mail SET status='sending',retry_at=? WHERE key=?",
                       (now + 120, key))
        payload = json.dumps({"from":sender,"to":[recipient],"subject":SUBJECT,
                              "text":invitation_body()}).encode()
        req = urllib.request.Request("https://api.resend.com/emails", data=payload,
                                     headers={"Authorization":"Bearer "+api_key,
                                              "Content-Type":"application/json",
                                              "Idempotency-Key":key},method="POST")
        try:
            response = (opener or urllib.request.urlopen)(req, timeout=12)
            provider_id = json.loads(response.read().decode())["id"]
        except Exception as exc:
            with self.connect() as db:
                db.execute("UPDATE onboarding_mail SET status='retry',attempts=?,retry_at=?,error=? WHERE key=?",
                           (attempts+1,now+min(3600,60*(2**min(attempts,5))),type(exc).__name__,key))
            return "retry"
        with self.connect() as db:
            db.execute("UPDATE onboarding_mail SET status='accepted',attempts=?,provider_id=?,error=NULL WHERE key=?",
                       (attempts+1,provider_id,key))
        return "accepted"
