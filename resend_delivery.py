"""Opt-in signed delivery evidence; never sends mail or changes entitlements."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone

import click
from flask import jsonify, request
from sqlalchemy import Column, DateTime, MetaData, String, Table, insert, select
from sqlalchemy.exc import IntegrityError

EVENTS = frozenset({"email.sent", "email.delivered", "email.bounced", "email.complained",
                    "email.failed", "email.delivery_delayed", "email.suppressed"})
MAX_BODY = 65536


def verify_signature(raw: bytes, headers: dict, secret: str, now: float | None = None) -> str:
    """Verify Svix HMAC over exact bytes, including ID and fresh attempt timestamp."""
    event_id = headers.get("svix-id", "")
    timestamp = headers.get("svix-timestamp", "")
    signatures = headers.get("svix-signature", "")
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id)
            or not re.fullmatch(r"[0-9]{1,12}", timestamp)
            or len(signatures) > 2048 or len(raw) > MAX_BODY):
        raise ValueError("invalid_signature")
    if abs((time.time() if now is None else now) - int(timestamp)) > 300:
        raise ValueError("expired_signature")
    if not secret.startswith("whsec_"):
        raise ValueError("invalid_signing_configuration")
    try:
        key = base64.b64decode(secret[6:], validate=True)
    except ValueError as exc:
        raise ValueError("invalid_signing_configuration") from exc
    if len(key) < 16:
        raise ValueError("invalid_signing_configuration")
    signed = event_id.encode() + b"." + timestamp.encode() + b"." + raw
    expected = base64.b64encode(hmac.digest(key, signed, "sha256")).decode()
    if not any(hmac.compare_digest(item[3:], expected)
               for item in signatures.split() if item.startswith("v1,")):
        raise ValueError("invalid_signature")
    return event_id


class DeliveryEvidence:
    """Append-only evidence with durable unique provider IDs and explicit source binding.

    Source bindings are supplied only by a trusted sender/operator after checking the
    provider message identity. Unknown messages remain unbound for reconciliation;
    recipient email and webhook-supplied tags never establish a submission identity.
    """

    def __init__(self, engine):
        self.engine = engine
        meta = MetaData()
        self.events = Table(
            "resend_delivery_events", meta,
            Column("event_id", String(128), primary_key=True),
            Column("body_sha256", String(64), nullable=False),
            Column("message_id", String(128), nullable=False, index=True),
            Column("event_type", String(40), nullable=False),
            Column("occurred_at", DateTime(timezone=True), nullable=False),
            Column("recorded_at", DateTime(timezone=True), nullable=False),
        )
        self.bindings = Table(
            "resend_delivery_source_bindings", meta,
            Column("message_id", String(128), primary_key=True),
            Column("source_event_id", String(128), nullable=False),
        )
        meta.create_all(engine)

    def bind(self, message_id: str, source_event_id: str) -> None:
        """Bind a provider message using independently verified sender evidence."""
        for value in (message_id, source_event_id):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError("invalid_binding")
        with self.engine.begin() as conn:
            try:
                with conn.begin_nested():
                    conn.execute(insert(self.bindings).values(
                        message_id=message_id, source_event_id=source_event_id))
            except IntegrityError:
                existing = conn.execute(select(self.bindings.c.source_event_id).where(
                    self.bindings.c.message_id == message_id)).scalar_one()
                if existing != source_event_id:
                    raise ValueError("binding_conflict") from None

    def record(self, event_id: str, raw: bytes) -> bool:
        """Save minimal authenticated facts; conflicting event IDs fail closed."""
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("type") not in EVENTS:
            raise ValueError("unsupported_event")
        data = payload.get("data")
        message_id = data.get("email_id") if isinstance(data, dict) else None
        if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", message_id):
            raise ValueError("invalid_message_id")
        occurred = datetime.fromisoformat(str(payload.get("created_at", "")).replace("Z", "+00:00"))
        if occurred.tzinfo is None:
            raise ValueError("invalid_event_time")
        digest = hashlib.sha256(raw).hexdigest()
        with self.engine.begin() as conn:
            try:
                with conn.begin_nested():
                    conn.execute(insert(self.events).values(
                        event_id=event_id, body_sha256=digest, message_id=message_id,
                        event_type=payload["type"], occurred_at=occurred,
                        recorded_at=datetime.now(timezone.utc)))
            except IntegrityError:
                existing = conn.execute(select(self.events.c.body_sha256).where(
                    self.events.c.event_id == event_id)).scalar_one()
                if not hmac.compare_digest(existing, digest):
                    raise ValueError("event_identity_conflict") from None
                return False
        return True

    def evidence(self, message_id: str) -> dict:
        """Return independent flags; a late sent/delayed event cannot erase failure."""
        with self.engine.connect() as conn:
            types = set(conn.execute(select(self.events.c.event_type).where(
                self.events.c.message_id == message_id)).scalars())
            source = conn.execute(select(self.bindings.c.source_event_id).where(
                self.bindings.c.message_id == message_id)).scalar_one_or_none()
        failures = sorted(types & {"email.bounced", "email.complained", "email.failed", "email.suppressed"})
        return {"message_id": message_id, "source_event_id": source,
                "acceptance_observed": "email.sent" in types,
                "delivery_observed": "email.delivered" in types,
                "delay_observed": "email.delivery_delayed" in types,
                "failure_events": failures,
                "needs_reconciliation": source is None or bool(failures)
                or ("email.delivery_delayed" in types and "email.delivered" not in types)}


def register_delivery_routes(app, engine) -> None:
    """Register a disabled-by-default receiver and shell-only evidence commands."""
    enabled = os.getenv("NIJA_RESEND_DELIVERY_ENABLED", "false") == "true"
    secret = os.getenv("RESEND_DELIVERY_WEBHOOK_SECRET", "")
    ledger = None
    if enabled:
        # No ephemeral production fallback, and no DDL before configuration validation.
        if engine.dialect.name != "postgresql" or not secret.startswith("whsec_"):
            raise RuntimeError("durable_resend_delivery_configuration_required")
        ledger = DeliveryEvidence(engine)
    app.config["RESEND_DELIVERY_EVIDENCE"] = ledger

    @app.post("/api/email/resend/webhook")
    def resend_delivery_webhook():
        if ledger is None:
            return jsonify(error="delivery_receiver_disabled"), 503
        raw = request.stream.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            return jsonify(error="payload_too_large"), 413
        try:
            event_id = verify_signature(raw, request.headers, secret)
            created = ledger.record(event_id, raw)
        except (ValueError, TypeError, UnicodeError):
            return jsonify(error="invalid_delivery_event"), 400
        except Exception:
            # Never acknowledge a failed durable write or expose provider payloads.
            app.logger.error("resend_delivery_storage_failed")
            return jsonify(error="delivery_storage_unavailable"), 503
        return jsonify(recorded=True, duplicate=not created), 200

    @app.cli.command("resend-delivery-evidence")
    @click.argument("message_id")
    def delivery_evidence(message_id):
        if ledger is None:
            raise click.ClickException("delivery_receiver_disabled")
        click.echo(json.dumps(ledger.evidence(message_id), sort_keys=True))

    @app.cli.command("resend-delivery-bind")
    @click.argument("message_id")
    @click.argument("source_event_id")
    def delivery_bind(message_id, source_event_id):
        if ledger is None:
            raise click.ClickException("delivery_receiver_disabled")
        ledger.bind(message_id, source_event_id)
        click.echo("source_binding_recorded")
