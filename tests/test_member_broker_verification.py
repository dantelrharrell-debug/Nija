"""Offline HTTP-to-vault-to-Kraken regressions using synthetic credentials only."""
import base64
from contextlib import nullcontext
import copy
import unittest
from unittest.mock import Mock, patch

import requests

from member_broker_http_api import BILLING_SETTINGS, REVIEW_FLAGS, create_app
from member_broker_onboarding import MemberBrokerOnboarding
from member_broker_vault import BrokerVault, VaultError


class MemberVerificationTests(unittest.TestCase):
    """Exercise real encryption and authorization boundaries without provider access."""

    def setUp(self):
        self.session = Mock()
        self.entitlement = Mock(return_value=True)
        self.vault = BrokerVault(
            "https://example.test", base64.b64encode(bytes(range(32))).decode(),
            self.entitlement, session=self.session,
        )
        self.credentials = {
            "api_key": "synthetic-kraken-key",
            "api_secret": base64.b64encode(b"synthetic-kraken-secret").decode(),
        }
        self.record = {
            "id": "ownedrecord", "user_id": "member123", "broker": "kraken", "environment": "live",
            "ciphertext": self.vault.encrypt("member123", "kraken", "live", self.credentials),
        }
        self.identity = {"record": {"id": "member123", "verified": True}}
        self.rows = [self.record]
        self.session.request.side_effect = self.backend
        onboarding = MemberBrokerOnboarding(self.vault, verification_enabled=True)
        self.client = create_app(onboarding=onboarding).test_client()
        self.headers = {
            "Origin": "https://nijaaitrading.com", "Authorization": "Bearer " + "synthetic-member-token",
        }
        self.kraken_response = Mock(status_code=200)
        self.kraken_response.json.return_value = {"error": [], "result": {"ZUSD": "sensitive-balance"}}
        self.kraken = patch("member_broker_kraken_readonly.requests.post",
                            return_value=self.kraken_response).start()
        # HTTP contract tests inject nonce authority as well as transport;
        # production must still obtain the canonical writer's real authority.
        patch("member_broker_kraken_readonly.coordinated_kraken_nonce",
              side_effect=lambda _key: nullcontext(123456789)).start()
        self.addCleanup(patch.stopall)

    def backend(self, method, url, **kwargs):
        response = Mock(status_code=200)
        if url.endswith("/auth-refresh"):
            response.json.return_value = self.identity
        else:
            self.assertEqual(method, "GET")
            self.assertEqual(kwargs["params"]["filter"], 'user_id="member123"')
            response.json.return_value = {"totalPages": 1, "items": copy.deepcopy(self.rows)}
        return response

    def verify(self, payload=None, headers=None):
        return self.client.post(
            "/api/member/brokers/verify",
            headers=self.headers if headers is None else headers,
            json={"broker": "kraken", "environment": "live"} if payload is None else payload,
        )

    def assert_safe_denial(self, status=403):
        response = self.verify()
        self.assertEqual(response.status_code, status)
        self.kraken.assert_not_called()
        self.assert_no_secrets(response)

    def assert_no_secrets(self, response):
        for value in (*self.credentials.values(), "sensitive-balance", self.record["ciphertext"],
                      "synthetic-member-token"):
            self.assertNotIn(value.encode(), response.data)

    def test_success_authenticates_owner_and_entitlement_without_writes_or_orders(self):
        response = self.verify()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "broker": "kraken", "environment": "live", "credentials_stored": True,
            "broker_verified": True, "membership_access": True, "trading_authorized": False,
        })
        self.entitlement.assert_called_once_with("member123")
        self.assertEqual(self.session.request.call_count, 2)
        self.assertEqual(self.kraken.call_count, 1)
        self.assertEqual(self.kraken.call_args.args, ("https://api.kraken.com/0/private/Balance",))
        self.assertEqual(set(self.kraken.call_args.kwargs["data"]), {"nonce"})
        self.assertFalse(self.kraken.call_args.kwargs["allow_redirects"])
        self.assert_no_secrets(response)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_every_request_rechecks_entitlement_and_identity(self):
        self.assertEqual(self.verify().status_code, 200)
        self.entitlement.return_value = False
        self.assertEqual(self.verify().status_code, 403)
        self.assertEqual(self.entitlement.call_count, 2)
        self.assertEqual(self.kraken.call_count, 1)
        self.assertEqual(self.session.request.call_count, 3)

    def test_missing_or_invalid_bearer(self):
        for auth in ("", "Basic synthetic", "Bearer", "****** two"):
            with self.subTest(auth=auth):
                headers = dict(self.headers, Authorization=auth)
                self.assertEqual(self.verify(headers=headers).status_code, 401)
        self.session.request.assert_not_called()
        self.kraken.assert_not_called()

    def test_backend_rejects_forged_or_expired_token(self):
        self.session.request.side_effect = None
        self.session.request.return_value.status_code = 401
        self.assert_safe_denial()

    def test_unverified_missing_or_malformed_identity(self):
        for identity in ({}, {"record": []}, {"record": "invalid"},
                         {"record": {"id": "member123", "verified": False}},
                         {"record": {"id": 'x" || true', "verified": True}}):
            with self.subTest(identity=identity):
                self.identity = identity
                self.assert_safe_denial()
        self.entitlement.assert_not_called()

    def test_no_membership_or_non_boolean_approval(self):
        for value in (False, None, "true", 1):
            self.entitlement.return_value = value
            self.assert_safe_denial()

    def test_missing_duplicate_and_cross_member_records(self):
        for rows in ([], [self.record, self.record],
                     [dict(self.record, user_id="member456")],
                     [self.record, dict(self.record, id="duplicate")],
                     [self.record, dict(self.record, broker="alpaca")]):
            with self.subTest(rows=len(rows)):
                self.rows = rows
                self.assert_safe_denial()

    def test_malformed_or_missing_ciphertext(self):
        for envelope in ("", None, "not-json", "x" * 8193):
            self.rows = [dict(self.record, ciphertext=envelope)]
            self.assert_safe_denial()

    def test_ciphertext_cannot_be_replayed_across_owners_or_scopes(self):
        for scope in (("member456", "kraken", "live"), ("member123", "kraken", "paper"),
                      ("member123", "alpaca", "live")):
            envelope = self.vault.encrypt(*scope, self.credentials)
            self.rows = [dict(self.record, ciphertext=envelope)]
            self.assert_safe_denial()

    def test_wrong_key_and_tampering_fail_before_kraken(self):
        alternate = BrokerVault("https://example.test", base64.b64encode(b"x" * 32).decode(), lambda _: True)
        self.rows = [dict(self.record, ciphertext=alternate.encrypt(
            "member123", "kraken", "live", self.credentials))]
        self.assert_safe_denial()
        self.rows = [dict(self.record, ciphertext=self.record["ciphertext"].replace('"v":1', '"v":2'))]
        self.assert_safe_denial()

    def test_incomplete_pagination_rejected(self):
        self.session.request.side_effect = None
        self.session.request.return_value.status_code = 200
        self.session.request.return_value.json.side_effect = [
            self.identity, {"totalPages": 2, "items": [self.record]},
        ]
        self.assert_safe_denial()

    def test_invalid_stored_fields_rejected(self):
        for credentials in ({}, {"api_key": "dummy", "secret": "wrong-field"},
                            dict(self.credentials, passphrase="extra"),
                            dict(self.credentials, api_key=" ")):
            self.rows = [dict(self.record, ciphertext=self.vault.encrypt(
                "member123", "kraken", "live", credentials or {"invalid": "dummy"}))]
            self.assert_safe_denial()

    def test_kraken_provider_errors_and_malformed_json_do_not_expose_details(self):
        for status, body in ((429, {}), (503, {}), (302, {}),
                             (200, {"error": ["EAPI:Invalid key"], "result": {}}),
                             (200, {"error": [], "result": None}),
                             (200, ["malformed"])):
            with self.subTest(status=status, body=body):
                self.kraken_response.status_code = status
                self.kraken_response.json.return_value = body
                response = self.verify()
                self.assertEqual(response.status_code, 502)
                self.assertFalse(response.get_json()["broker_verified"])
                self.assert_no_secrets(response)
        self.kraken_response.status_code = 200
        self.kraken_response.json.side_effect = ValueError("sensitive-balance")
        response = self.verify()
        self.assertEqual(response.status_code, 502)
        self.assert_no_secrets(response)

    def test_kraken_timeout_does_not_retry_or_expose_details(self):
        self.kraken.side_effect = requests.Timeout("synthetic-kraken-key")
        response = self.verify()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.kraken.call_count, 1)
        self.assert_no_secrets(response)

    def test_vault_unavailable_fails_closed(self):
        self.session.request.side_effect = requests.Timeout("synthetic-member-token")
        self.assert_safe_denial()

    def test_wrong_origin_and_preflight(self):
        self.assertEqual(self.verify(headers=dict(self.headers, Origin="https://evil.test")).status_code, 403)
        for origin, expected in (("https://evil.test", 403), ("https://nijaaitrading.com", 204)):
            self.assertEqual(self.client.options(
                "/api/member/brokers/verify", headers={"Origin": origin}).status_code, expected)
        self.kraken.assert_not_called()
        self.session.request.assert_not_called()

    def test_client_cannot_choose_owner_record_or_submit_keys(self):
        for extra in ({"user_id": "member456"}, {"record_id": "other"}, {"credentials": self.credentials}):
            response = self.verify({"broker": "kraken", "environment": "live", **extra})
            self.assertEqual(response.status_code, 400)
        for broker, environment in (("alpaca", "live"), ("kraken", "paper"), ([], "live")):
            self.assertEqual(self.verify({"broker": broker, "environment": environment}).status_code, 403)
        self.kraken.assert_not_called()
        self.session.request.assert_not_called()

    def test_invalid_json_and_content_type(self):
        self.assertEqual(self.client.post(
            "/api/member/brokers/verify", headers=self.headers, data="text").status_code, 415)
        self.assertEqual(self.client.post(
            "/api/member/brokers/verify", headers=self.headers,
            content_type="application/json", data="{").status_code, 403)
        self.assertEqual(self.verify(["not-an-object"]).status_code, 400)
        self.kraken.assert_not_called()

    def test_disabled_verification_never_reads_secrets(self):
        client = create_app(onboarding=MemberBrokerOnboarding(self.vault)).test_client()
        self.assertEqual(client.post("/api/member/brokers/verify", headers=self.headers,
                                     json={"broker": "kraken", "environment": "live"}).status_code, 403)
        self.session.request.assert_not_called()
        self.kraken.assert_not_called()

    def test_metadata_never_reuses_past_verification_as_authority(self):
        self.assertEqual(self.verify().status_code, 200)
        response = self.client.get("/api/member/brokers", headers=self.headers)
        row = response.get_json()["connections"][0]
        self.assertTrue(row["credentials_stored"])
        self.assertFalse(row["broker_verified"])
        self.assertFalse(row["trading_authorized"])
        self.assert_no_secrets(response)

    def test_readiness_can_enable_verification_without_intake(self):
        settings = {name: "true" for name in REVIEW_FLAGS}
        settings.update({name: "synthetic-setting" for name in BILLING_SETTINGS})
        with patch.dict("os.environ", settings, clear=True):
            response = self.client.get("/readyz")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {
                "status": "ready", "credential_intake_enabled": False, "verification_enabled": True,
            })
            for name in REVIEW_FLAGS:
                with patch.dict("os.environ", {name: "false"}):
                    self.assertEqual(self.client.get("/readyz").status_code, 503)

    def test_production_factory_never_enables_intake_or_verification_without_reviews(self):
        settings = {name: "true" for name in REVIEW_FLAGS}
        settings.update({name: "synthetic-setting" for name in BILLING_SETTINGS})
        settings.update({"NIJA_VAULT_INTAKE_ENABLED": "true", "NIJA_VAULT_VERIFICATION_ENABLED": "true"})
        for name in REVIEW_FLAGS:
            with patch.dict("os.environ", dict(settings, **{name: "false"}), clear=True):
                with patch("member_broker_http_api.BrokerVault.from_environment", return_value=self.vault):
                    client = create_app().test_client()
                    self.assertEqual(client.get("/readyz").status_code, 503)
                    self.assertEqual(client.post("/api/member/brokers/verify", headers=self.headers,
                                                 json={"broker": "kraken", "environment": "live"}).status_code, 403)
                    self.assertEqual(client.post("/api/member/brokers/connect", headers=self.headers, json={
                        "broker": "kraken", "environment": "live", "credentials": self.credentials,
                    }).status_code, 403)
        self.session.request.assert_not_called()
        self.kraken.assert_not_called()


if __name__ == "__main__":
    unittest.main()
