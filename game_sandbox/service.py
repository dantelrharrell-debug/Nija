"""Dedicated sandbox API. No imports from billing_service or trading runtime.

Run behind a same-origin HTTPS reverse proxy. The private canonical content and
report builder must come from the IONOS export, never from a browser payload.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

COOKIE = "__Host-nija-iq-sandbox"
TOKEN = re.compile(r"^[a-f0-9]{64}$")
OFFER = "nija-unified-iq-sandbox-v1"


class Denied(ValueError):
    """Request cannot grant payment or report authority."""


def digest(value: str) -> str:
    """Hash ownership receipts; raw receipts are never stored."""
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Config:
    """Separate sandbox-only settings; no fallback to production credentials."""

    database: str
    origin: str
    key: str
    webhook_secret: str
    price: str
    product: str
    enabled: bool = False

    def validate(self) -> None:
        """Reject live keys and non-isolated storage before opening any database."""
        parsed = urlparse(self.origin)
        if (
            not self.enabled
            or not self.key.startswith(("rk_test_", "sk_test_"))
            or not self.webhook_secret.startswith("whsec_")
            or parsed.scheme != "https"
            or not parsed.hostname
            or self.origin != f"https://{parsed.netloc}"
            or parsed.username
            or parsed.password
            or not re.fullmatch(r"price_[A-Za-z0-9_]+", self.price)
            or not re.fullmatch(r"prod_[A-Za-z0-9_]+", self.product)
        ):
            raise Denied("sandbox_configuration_required")
        path = Path(self.database)
        if not path.is_absolute() or path.name != "trading_iq_sandbox.sqlite3":
            raise Denied("dedicated_sandbox_database_required")


class Manifest:
    """Pin exported source and decision shape without inventing scoring rules."""

    def __init__(self, source: dict[str, Any]):
        canonical = json.dumps(source, sort_keys=True, separators=(",", ":"))
        self.digest = digest(canonical)
        self.version = source.get("version")
        self.source_sha256 = source.get("source_sha256")
        challenges = source.get("challenges")
        if (
            not isinstance(self.version, str)
            or not 1 <= len(self.version) <= 80
            or not TOKEN.fullmatch(self.source_sha256 or "")
            or source.get("structure") not in ("12_total", "12_per_challenge")
            or not isinstance(challenges, list)
        ):
            raise Denied("canonical_source_manifest_required")
        if not 1 <= len(challenges) <= 6 or (source["structure"] == "12_per_challenge" and len(challenges) != 6):
            raise Denied("challenge_count_mismatch")
        self.rounds = []
        for challenge in challenges:
            if not isinstance(challenge, dict) or not isinstance(challenge.get("rounds"), list):
                raise Denied("invalid_challenge")
            if source["structure"] == "12_per_challenge" and len(challenge["rounds"]) != 12:
                raise Denied("twelve_rounds_per_manifest_group_required")
            self.rounds.extend(challenge["rounds"])
        if len(self.rounds) != (12 if source["structure"] == "12_total" else 72):
            raise Denied("decision_count_mismatch")
        seen = set()
        for row in self.rounds:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not re.fullmatch(r"[a-z][a-z0-9_-]{1,79}", row["id"])
                or row["id"] in seen
                or type(row.get("choices")) is not int
                or not 2 <= row["choices"] <= 12
            ):
                raise Denied("invalid_round")
            seen.add(row["id"])

    def answers(self, answers: Any) -> str:
        """Accept ordered selections only, never browser scores or report contents."""
        if not isinstance(answers, list) or len(answers) != len(self.rounds):
            raise Denied("decision_count_mismatch")
        for answer, row in zip(answers, self.rounds):
            if (
                not isinstance(answer, dict)
                or set(answer) != {"roundId", "choice"}
                or answer["roundId"] != row["id"]
                or type(answer["choice"]) is not int
                or not 0 <= answer["choice"] < row["choices"]
            ):
                raise Denied("invalid_decision")
        return json.dumps(answers, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, csrf_hash TEXT NOT NULL,
 manifest TEXT NOT NULL, adult INTEGER NOT NULL CHECK(adult=1),
 answers TEXT, created INTEGER NOT NULL, expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS checkouts (
 run_id TEXT PRIMARY KEY REFERENCES runs(id),
 session_id TEXT UNIQUE, payment_intent TEXT UNIQUE, url TEXT,
 started INTEGER NOT NULL, entitled INTEGER NOT NULL DEFAULT 0 CHECK(entitled IN (0,1))
);
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, processed INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reversals (payment_intent TEXT PRIMARY KEY, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS limits (owner_hash TEXT PRIMARY KEY, started INTEGER NOT NULL, count INTEGER NOT NULL);
"""


class Sandbox:
    """Durable owner/run/payment boundary with a single Checkout per run."""

    def __init__(self, config: Config, manifest: Manifest, stripe: Any, report_builder: Callable[[Any], dict]):
        config.validate()
        self.config, self.manifest, self.stripe, self.report_builder = config, manifest, stripe, report_builder
        target = Path(config.database)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target.is_symlink():
            raise Denied("unsafe_storage_path")
        target.touch(mode=0o600, exist_ok=True)
        target.chmod(0o600)
        with self.db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        """Serialize transitions and commit event deduplication with entitlements."""
        connection = sqlite3.connect(self.config.database, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def start(self, adult: Any, owner: str | None = None) -> tuple[str, str, str]:
        """Persist adult self-attestation only; do not collect dates of birth."""
        if adult is not True:
            raise Denied("adult_attestation_required")
        owner = owner if isinstance(owner, str) and TOKEN.fullmatch(owner) else secrets.token_hex(32)
        csrf, run_id, now = secrets.token_hex(32), secrets.token_hex(24), int(time.time())
        with self.db() as db:
            recent = db.execute(
                "SELECT COUNT(*) FROM runs WHERE owner_hash=? AND created>?", (digest(owner), now - 3600)
            ).fetchone()[0]
            if recent >= 20:
                raise Denied("too_many_runs")
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,1,NULL,?,?)",
                (run_id, digest(owner), digest(csrf), self.manifest.digest, now, now + 365 * 86400),
            )
        return run_id, owner, csrf

    def owned(self, db: sqlite3.Connection, run_id: str, owner: str, csrf: str | None = None) -> Any:
        """Require possession of the first-party HttpOnly ownership cookie."""
        if not isinstance(owner, str) or not TOKEN.fullmatch(owner):
            raise Denied("ownership_required")
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if (
            not row
            or not hmac.compare_digest(row["owner_hash"], digest(owner))
            or row["expires"] < int(time.time())
            or row["manifest"] != self.manifest.digest
        ):
            raise Denied("ownership_required")
        if csrf is not None and (not TOKEN.fullmatch(csrf) or not hmac.compare_digest(row["csrf_hash"], digest(csrf))):
            raise Denied("csrf_required")
        return row

    def complete(self, run_id: str, owner: str, csrf: str, answers: Any) -> None:
        """Freeze validated decision history; retries may only repeat the same history."""
        encoded = self.manifest.answers(answers)
        with self.db() as db:
            row = self.owned(db, run_id, owner, csrf)
            if row["answers"] is not None and row["answers"] != encoded:
                raise Denied("run_is_immutable")
            db.execute("UPDATE runs SET answers=? WHERE id=?", (encoded, run_id))

    def checkout(self, run_id: str, owner: str, csrf: str) -> dict:
        """Reserve durably before Stripe; reuse the same idempotency key on retries."""
        now = int(time.time())
        with self.db() as db:
            run = self.owned(db, run_id, owner, csrf)
            if run["answers"] is None:
                raise Denied("complete_game_first")
            row = db.execute("SELECT * FROM checkouts WHERE run_id=?", (run_id,)).fetchone()
            if row and row["session_id"]:
                return {"url": row["url"], "run_id": run_id, "existing": True}
            if row and now - row["started"] >= 23 * 3600:
                raise Denied("checkout_requires_reconciliation")
            db.execute("INSERT OR IGNORE INTO checkouts(run_id,started) VALUES (?,?)", (run_id, now))
        price = self.stripe.price(self.config.price)
        if not (
            price.get("id") == self.config.price
            and price.get("product") == self.config.product
            and price.get("active") is True
            and price.get("livemode") is False
            and price.get("type") == "one_time"
            and price.get("unit_amount") == 100
            and price.get("currency") == "usd"
        ):
            raise Denied("sandbox_price_mismatch")
        metadata = {
            "offer": OFFER,
            "run_id": run_id,
            "manifest": self.manifest.digest,
            "version": self.manifest.version,
        }
        session = self.stripe.create(
            {
                "mode": "payment",
                "line_items": [{"price": self.config.price, "quantity": 1}],
                "client_reference_id": run_id,
                "metadata": metadata,
                "payment_intent_data": {"metadata": metadata},
                "success_url": self.config.origin + "/report?run_id=" + run_id,
                "cancel_url": self.config.origin + "/report?run_id=" + run_id + "&cancelled=1",
            },
            "tiq-sandbox-" + run_id,
        )
        target = urlparse(session.get("url", ""))
        if (
            not re.fullmatch(r"cs_test_[A-Za-z0-9_]{8,250}", session.get("id", ""))
            or session.get("livemode") is not False
            or session.get("mode") != "payment"
            or target.scheme != "https"
            or target.hostname != "checkout.stripe.com"
        ):
            raise Denied("unexpected_checkout")
        with self.db() as db:
            db.execute(
                "UPDATE checkouts SET session_id=?,url=? WHERE run_id=? AND session_id IS NULL",
                (session["id"], session["url"], run_id),
            )
            actual = db.execute("SELECT session_id FROM checkouts WHERE run_id=?", (run_id,)).fetchone()[0]
            if actual != session["id"]:
                raise Denied("provider_idempotency_violation")
        return {"url": session["url"], "run_id": run_id, "existing": False}

    def verified(self, session_id: str, run: Any) -> tuple[bool, str]:
        """Retrieve authoritative Stripe state, including current refund/dispute flags."""
        session, lines = self.stripe.purchase(session_id)
        metadata, intent = session.get("metadata", {}), session.get("payment_intent", {})
        charge = intent.get("latest_charge", {}) if isinstance(intent, dict) else {}
        rows = lines.get("data", [])
        valid = (
            session.get("id") == session_id
            and session.get("livemode") is False
            and session.get("mode") == "payment"
            and session.get("status") == "complete"
            and session.get("payment_status") == "paid"
            and session.get("amount_total") == 100
            and session.get("currency") == "usd"
            and session.get("client_reference_id") == run["id"]
            and metadata
            == {"offer": OFFER, "run_id": run["id"], "manifest": self.manifest.digest, "version": self.manifest.version}
            and intent.get("status") == "succeeded"
            and intent.get("amount_received") == 100
            and intent.get("currency") == "usd"
            and intent.get("livemode") is False
            and charge.get("status") == "succeeded"
            and charge.get("paid") is True
            and charge.get("livemode") is False
            and charge.get("amount_refunded") == 0
            and charge.get("refunded") is False
            and charge.get("disputed") is False
            and len(rows) == 1
            and lines.get("has_more") is False
        )
        if valid:
            line = rows[0]
            valid = (
                line.get("quantity") == 1
                and line.get("amount_total") == 100
                and line.get("currency") == "usd"
                and line.get("price", {}).get("id") == self.config.price
                and line.get("price", {}).get("product") == self.config.product
            )
        payment_intent = intent.get("id", "") if isinstance(intent, dict) else ""
        return bool(valid and re.fullmatch(r"pi_[A-Za-z0-9_]+", payment_intent)), payment_intent

    def webhook(self, raw: bytes, signature: str) -> None:
        """Verify raw-body signature before an atomic, replay-safe transition."""
        event = self.stripe.event(raw, signature, self.config.webhook_secret)
        if event.get("livemode") is not False or not re.fullmatch(r"evt_[A-Za-z0-9_]+", event.get("id", "")):
            raise Denied("sandbox_event_required")
        kind, obj = event["type"], event["data"]["object"]
        with self.db() as db:
            if db.execute("SELECT 1 FROM events WHERE id=?", (event["id"],)).fetchone():
                return
            if kind in (
                "charge.refunded",
                "charge.dispute.created",
                "charge.dispute.updated",
                "charge.dispute.closed",
                "refund.created",
                "refund.updated",
                "refund.failed",
            ):
                pi = obj.get("payment_intent")
                if isinstance(pi, str):
                    # Conservative, sticky revocation even for pending refunds or won disputes.
                    db.execute("INSERT OR IGNORE INTO reversals VALUES (?,?)", (pi, kind))
                    db.execute("UPDATE checkouts SET entitled=0 WHERE payment_intent=?", (pi,))
            elif kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
                row = db.execute("SELECT * FROM checkouts WHERE session_id=?", (obj.get("id"),)).fetchone()
                if row:
                    run = db.execute("SELECT * FROM runs WHERE id=?", (row["run_id"],)).fetchone()
                    valid, pi = self.verified(row["session_id"], run)
                    if valid:
                        reversed_payment = db.execute(
                            "SELECT 1 FROM reversals WHERE payment_intent=?", (pi,)
                        ).fetchone()
                        db.execute(
                            "UPDATE checkouts SET payment_intent=?,entitled=? WHERE run_id=?",
                            (pi, int(not reversed_payment), row["run_id"]),
                        )
                elif obj.get("metadata", {}).get("offer") == OFFER:
                    # Checkout create may have succeeded before a local crash; retry after reconciliation.
                    raise Denied("checkout_not_yet_bound")
            elif kind == "checkout.session.async_payment_failed":
                db.execute("UPDATE checkouts SET entitled=0 WHERE session_id=?", (obj.get("id"),))
            db.execute("INSERT INTO events VALUES (?,?)", (event["id"], int(time.time())))

    def report(self, run_id: str, owner: str) -> dict:
        """Allow owned reopening; current provider state must still permit access."""
        with self.db() as db:
            run = self.owned(db, run_id, owner)
            row = db.execute("SELECT * FROM checkouts WHERE run_id=?", (run_id,)).fetchone()
            if not row or not row["entitled"]:
                raise Denied("verified_webhook_required")
            valid, pi = self.verified(row["session_id"], run)
            revoked = db.execute("SELECT 1 FROM reversals WHERE payment_intent=?", (pi,)).fetchone()
            if not valid or revoked or pi != row["payment_intent"]:
                raise Denied("payment_reversed_or_unverified")
            answers = json.loads(run["answers"])
            self.manifest.answers(answers)
        # The original exported report function is injected server-side. Never substitute synthetic scoring.
        return self.report_builder(answers)

    def backup(self, destination: str) -> None:
        """Create a consistent SQLite backup for an isolated staging restore test."""
        target = Path(destination)
        if target.exists() or target.resolve() == Path(self.config.database).resolve():
            raise Denied("new_backup_path_required")
        target.touch(mode=0o600)
        with sqlite3.connect(self.config.database) as source, sqlite3.connect(destination) as backup:
            source.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise Denied("backup_integrity_failed")
