"""Isolated lifecycle-to-delivery tests; no real provider, checkout, or trading calls."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import jwt
from flask import Flask

from founding_onboarding_api import register_onboarding_routes


class OnboardingAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.secret = "test-only-onboarding-identity"
        self.webhook_key = b"test-only-webhook-signing-material"
        self.env = patch.dict(os.environ, {
            "NIJA_ONBOARDING_DB_PATH": self.temp.name + "/outbox.db",
            "NIJA_ONBOARDING_IDENTITY_SECRET": self.secret,
            "NIJA_ONBOARDING_OPERATOR_SECRET": "test-only-operator",
            "RESEND_ONBOARDING_WEBHOOK_SECRET": "whsec_" + base64.b64encode(self.webhook_key).decode(),
            "NIJA_ONBOARDING_SEND_MODE": "disabled",
            "NIJA_ONBOARDING_DOMAIN_VERIFIED": "true",
            "NIJA_ONBOARDING_SENDER": "support@nijaaitrading.com",
            "RESEND_API_KEY": "test-only-provider",
        })
        self.env.start()
        self.store = Mock()
        self.store.get_customer.return_value = None
        self.app = Flask(__name__)
        self.app.testing = True
        register_onboarding_routes(self.app, self.store)
        self.client = self.app.test_client()
        self.outbox = self.app.config["ONBOARDING_OUTBOX"]

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def headers(self, audience="nija-onboarding-events", **extra):
        now = int(time.time())
        claims = dict(sub="member1", application_id="app1", email="member@example.test",
                      email_verified=True, approved=True, event_type="enrollment.approved",
                      iss="nija-identity", aud=audience, iat=now, exp=now + 120)
        claims.update(extra)
        secret = "test-only-operator" if audience == "nija-onboarding-operator" else self.secret
        return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}

    def post_event(self, **claims):
        return self.client.post("/api/onboarding/events", json={}, headers=self.headers(**claims))

    def status(self, **claims):
        return self.client.get("/api/onboarding/status",
                               headers=self.headers("nija-onboarding-status", **claims))

    def provider_event(self, event_type, *, stamp=None, body=None, signature=None):
        body = body or json.dumps({"type": event_type, "data": {"email_id": "mail1"}}).encode()
        stamp = str(int(time.time()) if stamp is None else stamp)
        digest = base64.b64encode(hmac.new(
            self.webhook_key, b"event1." + stamp.encode() + b"." + body, hashlib.sha256).digest()).decode()
        return self.client.post("/api/onboarding/resend/webhook", data=body, content_type="application/json",
                                headers={"svix-id": "event1", "svix-timestamp": stamp,
                                         "svix-signature": signature or "v1," + digest})

    def accept_mail(self):
        key = self.post_event().json["message_key"]
        response = Mock()
        response.read.return_value = b'{"id":"mail1"}'
        self.outbox.send(key, opener=Mock(return_value=response))
        return key

    def test_signup_delivery_and_registration_are_separate(self):
        key = self.accept_mail()
        status = self.status().json
        self.assertEqual(status["messages"][0]["status"], "accepted")
        self.assertFalse(status["registered"])
        self.assertFalse(status["member_activated"])
        self.assertEqual(self.provider_event("email.delivered").status_code, 200)
        self.assertEqual(self.status().json["messages"][0]["status"], "delivered")
        self.assertEqual(self.post_event(event_type="identity.registered").status_code, 202)
        status = self.status().json
        self.assertTrue(status["registered"])
        self.assertFalse(status["member_activated"])
        self.assertFalse(status["broker_connection_ready"])
        self.assertEqual(self.post_event().json["message_key"], key)
        self.assertEqual(self.outbox.due_keys(), [])

    def test_receipt_invite_and_registration_have_independent_events(self):
        receipt = self.post_event(event_type="application.received", approved=False).json["message_key"]
        invite = self.post_event().json["message_key"]
        self.assertNotEqual(receipt, invite)
        self.post_event(event_type="identity.registered")
        self.assertEqual(len(self.outbox.due_keys()), 2)
        self.post_event(event_type="application.received", approved=False)
        self.assertTrue(self.status().json["approved"])
        self.assertTrue(self.status().json["registered"])

    def test_already_registered_member_gets_one_invitation_not_new_checkout(self):
        self.post_event(event_type="identity.registered")
        for _ in range(3):
            self.post_event()
        self.assertEqual(len(self.outbox.due_keys()), 1)
        self.assertIn("Already registered? Sign in", __import__("founding_onboarding_mail").invitation_body())
        self.store.assert_not_called()
        self.assertEqual(self.store.method_calls, [])

    def test_checkout_email_mismatch_never_attaches_subscription_or_changes_trial(self):
        self.post_event()
        self.post_event(event_type="identity.registered")
        customer = {"email": "checkout-other@example.test", "entitled": True,
                    "trial_start": 123, "trial_end": 456, "subscription_id": "sub_existing"}
        self.store.get_customer.return_value = customer.copy()
        status = self.status().json
        self.assertFalse(status["entitlement_linked"])
        self.assertTrue(status["identity_reconciliation_required"])
        self.store.get_customer.assert_called_once_with("member1")
        self.assertEqual(self.store.get_customer.return_value, customer)
        self.assertEqual([c[0] for c in self.store.method_calls], ["get_customer"])

    def test_existing_owner_link_does_not_activate_member(self):
        self.post_event()
        self.post_event(event_type="identity.registered")
        self.store.get_customer.return_value = {"email": "member@example.test", "entitled": True}
        self.assertTrue(self.status().json["entitlement_linked"])
        self.assertFalse(self.status().json["member_activated"])

    def test_invalid_stored_billing_email_reports_reconciliation_not_client_error(self):
        self.post_event()
        self.store.get_customer.return_value = {"email": "legacy invalid email", "entitled": True}
        response = self.status()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["identity_reconciliation_required"])
        self.assertFalse(response.json["entitlement_linked"])

    def test_wrong_signature_audience_and_browser_flags_rejected(self):
        headers = self.headers()
        headers["Authorization"] += "tampered"
        self.assertEqual(self.client.post("/api/onboarding/events", json={}, headers=headers).status_code, 400)
        self.assertEqual(self.client.post("/api/onboarding/events", json={},
                                         headers=self.headers("nija-onboarding-status")).status_code, 400)
        self.assertEqual(self.client.post("/api/onboarding/events", json={"approved": True},
                                         headers=self.headers(approved=False)).status_code, 400)
        self.assertEqual(self.post_event(email_verified=False).status_code, 400)
        self.assertEqual(self.post_event(exp=int(time.time()) + 600).status_code, 400)
        self.assertEqual(self.outbox.due_keys(), [])

    def test_identity_cannot_be_rebound_to_new_email_or_owner(self):
        self.post_event()
        self.assertEqual(self.post_event(email="other@example.test").status_code, 400)
        self.assertEqual(self.post_event(sub="other").status_code, 400)
        self.assertEqual(self.post_event(application_id="other").status_code, 400)
        self.assertEqual(len(self.outbox.due_keys()), 1)
        self.assertEqual(self.status(sub="other").status_code, 404)

    def test_shared_address_does_not_expose_another_owners_messages(self):
        self.post_event()
        self.post_event(application_id="app2", sub="member2")
        self.assertEqual(len(self.status().json["messages"]), 1)
        self.assertEqual(len(self.status(sub="member2").json["messages"]), 1)
        self.assertNotEqual(self.status().json["messages"], self.status(sub="member2").json["messages"])

    def test_signed_webhooks_suppression_and_replay(self):
        self.accept_mail()
        for event in ("email.sent", "email.bounced", "email.delivered", "email.bounced"):
            self.assertEqual(self.provider_event(event).status_code, 200)
        message = self.status().json["messages"][0]
        self.assertEqual(message["status"], "failed")
        self.assertTrue(message["suppressed"])
        self.post_event(application_id="app2", sub="member2")
        self.assertTrue(self.status(sub="member2").json["messages"][0]["suppressed"])
        self.assertEqual(self.outbox.due_keys(), [])

    def test_bad_stale_future_and_tampered_webhooks_have_no_effect(self):
        self.accept_mail()
        self.assertEqual(self.provider_event("email.delivered", signature="v1,wrong").status_code, 400)
        self.assertEqual(self.provider_event("email.delivered", stamp=int(time.time()) - 301).status_code, 400)
        self.assertEqual(self.provider_event("email.delivered", stamp=int(time.time()) + 301).status_code, 400)
        self.assertEqual(self.client.post("/api/onboarding/resend/webhook",
                                         json={"type": "email.delivered"}).status_code, 400)
        self.assertEqual(self.status().json["messages"][0]["status"], "accepted")

    def test_worker_send_gates_controlled_recipient_and_cli(self):
        self.post_event()
        headers = self.headers("nija-onboarding-operator", scope="onboarding:operate")
        url = "/api/onboarding/operator/work"
        response = Mock()
        response.read.return_value = b'{"id":"mail1"}'
        with patch("urllib.request.urlopen", return_value=response) as send:
            self.assertEqual(self.client.post(url, json={}, headers=headers).status_code, 503)
            os.environ["NIJA_ONBOARDING_SEND_MODE"] = "controlled"
            self.assertEqual(self.client.post(url, json={}, headers=headers).json["processed"], 0)
            send.assert_not_called()
            os.environ["NIJA_ONBOARDING_TEST_RECIPIENTS"] = "member@example.test"
            result = self.app.test_cli_runner().invoke(args=["onboarding-worker", "--once"])
            self.assertEqual(result.exit_code, 0, result.output)
            send.assert_called_once()
            self.assertEqual(self.client.post(url, json={}, headers=headers).json["processed"], 0)
        self.assertEqual(self.status().json["messages"][0]["status"], "accepted")

    def test_domain_auth_and_operator_scope_required(self):
        self.post_event()
        os.environ["NIJA_ONBOARDING_SEND_MODE"] = "enabled"
        url = "/api/onboarding/operator/work"
        self.assertEqual(self.client.post(url, json={}, headers=self.headers()).status_code, 400)
        headers = self.headers("nija-onboarding-operator", scope="onboarding:operate")
        with patch("urllib.request.urlopen") as send:
            os.environ["NIJA_ONBOARDING_DOMAIN_VERIFIED"] = "false"
            self.assertEqual(self.client.post(url, json={}, headers=headers).status_code, 503)
            os.environ["NIJA_ONBOARDING_DOMAIN_VERIFIED"] = "true"
            os.environ["NIJA_ONBOARDING_SENDER"] = "sender@other.test"
            self.assertEqual(self.client.post(url, json={}, headers=headers).status_code, 503)
            send.assert_not_called()

    def test_operator_alerts_and_redrive(self):
        key = self.post_event().json["message_key"]
        error = OSError()
        error.code = 403
        self.outbox.send(key, opener=Mock(side_effect=error))
        headers = self.headers("nija-onboarding-operator", scope="onboarding:operate")
        response = self.client.get("/api/onboarding/operator/alerts", headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["alerts"][0]["key"], key)
        self.assertEqual(self.client.post("/api/onboarding/operator/redrive",
                                         json={"key": key}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/onboarding/operator/alerts", headers=headers).status_code, 200)

    def test_outbox_survives_app_restart(self):
        self.post_event()
        app = Flask("restarted")
        register_onboarding_routes(app, self.store)
        self.assertEqual(app.config["ONBOARDING_OUTBOX"].due_keys(), self.outbox.due_keys())

    def test_controlled_recipient_not_starved_by_unrelated_queue(self):
        for index in range(30):
            self.outbox.enqueue(str(index), "other@example.test", approved=True, verified=True)
        self.post_event()
        os.environ["NIJA_ONBOARDING_SEND_MODE"] = "controlled"
        os.environ["NIJA_ONBOARDING_TEST_RECIPIENTS"] = "member@example.test"
        response = Mock()
        response.read.return_value = b'{"id":"mail1"}'
        with patch("urllib.request.urlopen", return_value=response) as send:
            result = self.app.test_cli_runner().invoke(args=["onboarding-worker", "--once"])
            self.assertEqual(result.exit_code, 0, result.output)
            send.assert_called_once()
        self.assertEqual(self.status().json["messages"][0]["status"], "accepted")

    def test_storage_failure_on_one_message_does_not_abort_batch(self):
        self.post_event()
        self.post_event(application_id="app2", sub="member2")
        os.environ["NIJA_ONBOARDING_SEND_MODE"] = "enabled"
        with patch.object(self.outbox, "send", side_effect=[sqlite3.OperationalError("locked"), "accepted"]) as send:
            result = self.app.test_cli_runner().invoke(args=["onboarding-worker", "--once"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(send.call_count, 2)

    def test_unconfigured_onboarding_reports_unavailable_not_missing_member(self):
        os.environ.pop("NIJA_ONBOARDING_DB_PATH")
        app = Flask("disabled")
        register_onboarding_routes(app, self.store)
        client = app.test_client()
        # No durable store => no event intake, no mail, no new enrollment.
        self.assertEqual(client.post("/api/onboarding/events", json={}).status_code, 404)
        response = client.get("/api/onboarding/status")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "onboarding_temporarily_unavailable")
        self.assertIs(response.json["full_onboarding_certified"], False)
        self.assertIs(response.json["member_activated"], False)
        self.assertIs(response.json["broker_connection_ready"], False)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Retry-After"], "300")
        self.store.get_customer.assert_not_called()

    def test_real_billing_app_keeps_existing_trial_and_all_billing_rows_unchanged(self):
        from sqlalchemy import select, update
        from billing_service import create_app
        from billing_service_store import BillingServiceStore

        store = BillingServiceStore("sqlite:///" + self.temp.name + "/billing.db")
        store.create_checkout(user_id="member1", email="member@example.test", offer_code="founding_beta",
                              expected_price_id="price_existing", expected_product_id="prod_existing",
                              session_id="cs_existing", customer_id="cus_existing")
        with store.engine.begin() as conn:
            conn.execute(update(store.customers).values(
                status="trialing", entitled=True, stripe_subscription_id="sub_existing", current_period_end=1999999999))
        app = create_app(store)
        self.client = app.test_client()

        def snapshot():
            with store.engine.connect() as conn:
                return {t.name: [dict(row._mapping) for row in conn.execute(select(t))]
                        for t in store.metadata.tables.values()}

        before = snapshot()
        with patch("billing_service._stripe_module", side_effect=AssertionError("must not call Stripe")):
            self.assertEqual(self.post_event().status_code, 202)
            self.post_event(event_type="identity.registered")
            self.assertTrue(self.status().json["entitlement_linked"])
            self.post_event()
        self.assertEqual(snapshot(), before)
        self.assertEqual(store.get_customer("member1")["current_period_end"], 1999999999)
        store.engine.dispose()


if __name__ == "__main__":
    unittest.main()
