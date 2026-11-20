"""Offline signature, durable retry and recovery tests; no provider calls."""
import base64
import hmac
import json
import secrets
import sqlite3
import time
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import create_engine

from resend_delivery import DeliveryEvidence, register_delivery_routes, verify_signature


def signed(raw, key, event_id="msg_test", timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = base64.b64encode(hmac.digest(
        key, event_id.encode() + b"." + timestamp.encode() + b"." + raw, "sha256")).decode()
    return {"svix-id": event_id, "svix-timestamp": timestamp, "svix-signature": "v1," + signature}


def payload(kind="email.delivered", message="email_test"):
    return json.dumps({"type": kind, "created_at": "2026-11-16T19:00:00Z",
                       "data": {"email_id": message}}).encode()


def test_official_svix_vector():
    # Public test vector: https://docs.svix.com/receiving/verifying-payloads/how-manual
    public_vector_bytes = bytes.fromhex("a652779e6c820c604a2276af74e2b5e63b25")
    public_signing_value = "whsec_" + base64.b64encode(public_vector_bytes).decode()
    headers = {"svix-id": "msg_loFOjxBNrRLzqYUf", "svix-timestamp": "1731705121",
               "svix-signature": "v1,rAvfW3dJ/X/qxhsaXPOyyCGmRKsaKWcsNccKXlIktD0="}
    assert verify_signature(b'{"event_type":"ping","data":{"success":true}}',
                            headers, public_signing_value, now=1731705121) == headers["svix-id"]


def test_raw_body_id_time_and_signature_are_bound():
    key = secrets.token_bytes(32)
    signing_value = "whsec_" + base64.b64encode(key).decode()
    raw = payload()
    headers = signed(raw, key)
    assert verify_signature(raw, headers, signing_value) == "msg_test"
    for bad_body, bad_headers in (
        (raw + b" ", headers), (raw, {**headers, "svix-id": "msg_other"}),
        (raw, signed(raw, key, timestamp=int(time.time()) - 301)),
        (raw, signed(raw, key, timestamp=int(time.time()) + 301)),
        (raw, {**headers, "svix-signature": "v2,invalid"}),
    ):
        with pytest.raises(ValueError):
            verify_signature(bad_body, bad_headers, signing_value)
    assert verify_signature(raw, {**headers, "svix-signature": "v1,old " + headers["svix-signature"]}, signing_value)


def test_durable_deduplication_conflicts_and_restore(tmp_path):
    db = tmp_path / "ledger.sqlite"
    engine = create_engine("sqlite:///" + str(db))
    ledger = DeliveryEvidence(engine)
    assert ledger.record("msg_one", payload())
    assert not ledger.record("msg_one", payload())
    with pytest.raises(ValueError, match="identity_conflict"):
        ledger.record("msg_one", payload("email.failed"))
    ledger.bind("email_test", "source_one")
    ledger.bind("email_test", "source_one")
    with pytest.raises(ValueError, match="binding_conflict"):
        ledger.bind("email_test", "different_source")
    engine.dispose()
    restarted = DeliveryEvidence(create_engine("sqlite:///" + str(db)))
    assert not restarted.record("msg_one", payload())
    backup = tmp_path / "restored.sqlite"
    with sqlite3.connect(db) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    restored = DeliveryEvidence(create_engine("sqlite:///" + str(backup)))
    assert restored.evidence("email_test") == restarted.evidence("email_test")
    assert not restored.record("msg_one", payload())


def test_delivery_acceptance_failure_and_unknown_source_stay_separate():
    ledger = DeliveryEvidence(create_engine("sqlite://"))
    ledger.record("delivered", payload())
    state = ledger.evidence("email_test")
    assert state["delivery_observed"] and not state["acceptance_observed"]
    assert state["needs_reconciliation"]
    ledger.bind("email_test", "source_one")
    ledger.record("complaint", payload("email.complained"))
    ledger.record("late_sent", payload("email.sent"))
    ledger.record("late_delay", payload("email.delivery_delayed"))
    state = ledger.evidence("email_test")
    assert state["failure_events"] == ["email.complained"]
    assert state["delivery_observed"] and state["needs_reconciliation"]
    ledger.bind("email_second", "source_two")
    ledger.record("second", payload(message="email_second"))
    assert not ledger.evidence("email_second")["needs_reconciliation"]


@pytest.mark.parametrize("kind", ["email.bounced", "email.failed", "email.suppressed", "email.delivery_delayed"])
def test_failure_and_delay_need_review(kind):
    ledger = DeliveryEvidence(create_engine("sqlite://"))
    ledger.bind("email_test", "source_one")
    ledger.record("msg_test", payload(kind))
    assert ledger.evidence("email_test")["needs_reconciliation"]


def test_disabled_receiver_has_no_schema_or_public_evidence(monkeypatch):
    from sqlalchemy import inspect
    monkeypatch.delenv("NIJA_RESEND_DELIVERY_ENABLED", raising=False)
    app = Flask(__name__)
    engine = create_engine("sqlite://")
    register_delivery_routes(app, engine)
    assert inspect(engine).get_table_names() == []
    assert app.test_client().post("/api/email/resend/webhook").status_code == 503
    assert app.test_client().get("/api/email/resend/evidence").status_code == 404
    monkeypatch.setenv("NIJA_RESEND_DELIVERY_ENABLED", "true")
    with pytest.raises(RuntimeError, match="durable"):
        register_delivery_routes(Flask(__name__), engine)


def test_receiver_acknowledges_only_authenticated_durable_writes(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("NIJA_RESEND_DELIVERY_ENABLED", "true")
    key = secrets.token_bytes(32)
    monkeypatch.setenv("RESEND_DELIVERY_WEBHOOK_SECRET", "whsec_" + base64.b64encode(key).decode())
    ledger = DeliveryEvidence(create_engine("sqlite://"))
    app = Flask(__name__)
    with patch("resend_delivery.DeliveryEvidence", return_value=ledger):
        register_delivery_routes(app, SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    client = app.test_client()
    body = payload()
    assert client.post("/api/email/resend/webhook", data=body).status_code == 400
    first = client.post("/api/email/resend/webhook", data=body, headers=signed(body, key))
    assert first.status_code == 200 and not first.json["duplicate"]
    assert client.post("/api/email/resend/webhook", data=body, headers=signed(body, key)).json["duplicate"]
    with patch.object(ledger, "record", side_effect=RuntimeError("private details")):
        result = client.post("/api/email/resend/webhook", data=body, headers=signed(body, key))
    assert result.status_code == 503 and b"private details" not in result.data
    assert client.post("/api/email/resend/webhook", data=b"x" * 65537).status_code == 413
    inbound = payload("email.received")
    assert client.post("/api/email/resend/webhook", data=inbound, headers=signed(inbound, key)).status_code == 400


@pytest.mark.parametrize("invalid", ["", "wrong_prefix", "whsec_", "whsec_!!!",
                                     "whsec_" + base64.b64encode(b"short").decode()])
def test_invalid_signing_configuration_cannot_create_tables(monkeypatch, invalid):
    from types import SimpleNamespace
    monkeypatch.setenv("NIJA_RESEND_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("RESEND_DELIVERY_WEBHOOK_SECRET", invalid)
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    with patch("resend_delivery.DeliveryEvidence") as storage:
        with pytest.raises(RuntimeError, match="durable_resend_delivery_configuration_required"):
            register_delivery_routes(Flask(__name__), engine)
        storage.assert_not_called()
