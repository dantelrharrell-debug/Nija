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
            if status in ("accepted", "delivered", "suppressed", "failed") or retry_at > now:
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
            # A permanent HTTP 4xx error must not be retried blindly: suppressed
            # recipients and invalid senders require operator intervention.
            code = getattr(exc, "code", None)
            permanent = isinstance(code, int) and 400 <= code < 500 and code != 429
            state = "failed" if permanent or attempts >= 7 else "retry"
            with self.connect() as db:
                db.execute("UPDATE onboarding_mail SET status=?,attempts=?,retry_at=?,error=? WHERE key=?",
                           (state, attempts+1, now+min(3600, 60*(2**min(attempts,5))),
                            type(exc).__name__, key))
            return state
        with self.connect() as db:
            db.execute("UPDATE onboarding_mail SET status='accepted',attempts=?,provider_id=?,error=NULL WHERE key=?",
                       (attempts+1,provider_id,key))
        return "accepted"

    def due_keys(self, *, now=None, limit=25):
        """Get due queued/retry entries for a scheduled trusted worker."""
        now = int(time.time()) if now is None else int(now)
        with self.connect() as db:
            rows = db.execute(
                "SELECT key FROM onboarding_mail WHERE status IN ('queued','retry') "
                "AND retry_at<=? ORDER BY retry_at,key LIMIT ?",
                (now, max(1,min(int(limit),100))),
            ).fetchall()
        return [row[0] for row in rows]

    def record_provider_event(self, provider_id, event_type):
        """Record an event ONLY after the webhook caller verifies its signature.

        The HTTP route and provider signature verification must be implemented
        before this method is exposed to external traffic.
        """
        transitions = {
            "email.delivered": "delivered",
            "email.bounced": "suppressed",
            "email.complained": "suppressed",
        }
        state = transitions.get(event_type)
        if state is None:
            return False
        with self.connect() as db:
            cur = db.execute(
                "UPDATE onboarding_mail SET status=? "
                "WHERE provider_id=? AND status NOT IN ('suppressed','failed')",
                (state, provider_id),
            )
            return bool(cur.rowcount)
