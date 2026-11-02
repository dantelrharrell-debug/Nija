"""Synthetic signatures only: no production approval, keys or authority."""
import base64
import copy
import hashlib
import json
import time
import unittest
from functools import partial
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bot.kraken_operator_authorization import (
    GeneralApprovalBinding, OperatorAuthorizationDenied,
    make_general_operator_authorization_provider,
)
from bot.pretrade_attestation_validation_v452 import evaluate_pretrade_certificate, REQUIRED
from bot.pretrade_multi_account_registration_v474 import register_reviewed_account_registry
from bot.pretrade_composition_bridge_v465 import make_collector
from bot.pretrade_independent_attestation import inspect_authenticated_attestations
from bot.pretrade_attestation_validation_v452 import SOURCES, PROOF_BY_SOURCE, IndependentEvidenceRejected
from bot.pretrade_authenticated_provider_adapter_v453 import collect_independent_pretrade_evidence


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class OperatorAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.operator = Ed25519PrivateKey.generate()
        self.revoker = Ed25519PrivateKey.generate()
        self.binding = GeneralApprovalBinding(
            "platform:kraken", "a" * 64, "b" * 64, "spot",
            ("general_live_orders",), "release-reviewed-sha", "operator-provider",
        )
        self.approval = {
            "contract": "nija.general-live-approval.v1", "approval_id": "test-approval",
            "broker": "kraken", "account": self.binding.account,
            "account_iiban_sha256": self.binding.account_iiban_sha256,
            "api_key_sha256": self.binding.api_key_sha256, "mode": "spot",
            "scope": ["general_live_orders"], "operator_id": "test-operator",
            "approved_at_epoch": 950, "expires_at_epoch": 1100,
            "release_id": self.binding.release_id,
        }
        self.status = {
            "contract": "nija.general-live-approval-status.v1", "approval_id": "test-approval",
            "approval_sha256": hashlib.sha256(canonical(self.approval)).hexdigest(),
            "status": "active", "generation": 2, "observed_at_epoch": 999,
            "expires_at_epoch": 1010,
        }
        self.records = {}
        self.resign()

    def sign(self, value, key):
        return {"payload": copy.deepcopy(value),
                "signature": base64.b64encode(key.sign(canonical(value))).decode()}

    def resign(self):
        self.status["approval_sha256"] = hashlib.sha256(canonical(self.approval)).hexdigest()
        self.records = {"approval": self.sign(self.approval, self.operator),
                        "status": self.sign(self.status, self.revoker)}

    def public(self, key):
        return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def provider(self, **overrides):
        args = {
            "binding": self.binding, "operator_public_keys": {"test-operator": self.public(self.operator)},
            "revocation_public_key": self.public(self.revoker),
            "read_records": lambda: self.records, "independently_reviewed": True,
            "clock": lambda: 1000,
        }
        args.update(overrides)
        return make_general_operator_authorization_provider(**args)

    def assert_denied(self, row):
        self.assertIs(row["verified"], False)
        self.assertIs(row["authorizes_orders"], False)
        self.assertIn("failure_reason", row)

    def test_signed_approval_is_non_authorizing_and_v452_compatible(self):
        row = self.provider()()
        self.assertTrue(row["verified"])
        self.assertFalse(row["authorizes_orders"])
        self.assertTrue(row["provenance"]["operator_approval_verified"])
        ids = {field: field for field in REQUIRED}
        ids["operator_authorization"] = self.binding.provider_id
        result = evaluate_pretrade_certificate(
            {"operator_authorization": row}, account=self.binding.account,
            trusted_provider_ids=ids, now_epoch=1000,
        )
        self.assertNotIn("operator_authorization", result["missing"])
        self.assertFalse(result["certified"])
        self.assertFalse(result["authorizes_orders"])

    def test_missing_and_startup_approval_rejected(self):
        for records in ({}, {"approved": True, "plan": {}}, {"approval": self.records["approval"]}):
            with self.subTest(records=records):
                self.assert_denied(self.provider(read_records=lambda: records)())

    def test_wrong_signed_binding_and_operator(self):
        changes = {
            "account": "user:someone:kraken", "account_iiban_sha256": "c" * 64,
            "api_key_sha256": "d" * 64, "mode": "margin", "scope": ["startup_only"],
            "release_id": "another-release", "operator_id": "untrusted",
            "contract": "nija.startup-approval.v1", "broker": "coinbase",
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                original = self.approval[field]
                self.approval[field] = value
                self.resign()
                self.assert_denied(self.provider()())
                self.approval[field] = original

    def test_expired_future_invalid_approval_timestamps(self):
        for field, values in {
            "approved_at_epoch": [1001, True, float("inf"), 0],
            "expires_at_epoch": [1000, 999, False],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    original = self.approval[field]
                    self.approval[field] = value
                    if value == float("inf"):
                        self.records["approval"]["payload"][field] = value
                    else:
                        self.resign()
                    self.assert_denied(self.provider()())
                    self.approval[field] = original

    def test_forged_signature_or_payload_rejected(self):
        for change in ("signature", "payload", "wrong_key", "revocation"):
            self.resign()
            if change == "signature":
                self.records["approval"]["signature"] = "invalid"
            elif change == "payload":
                self.records["approval"]["payload"]["scope"] = ["all_orders"]
            elif change == "wrong_key":
                self.records["approval"] = self.sign(self.approval, self.revoker)
            else:
                self.records["status"]["payload"]["status"] = "active-forged"
            self.assert_denied(self.provider()())

    def test_explicit_revocation_missing_stale_and_wrong_membership(self):
        changes = {
            "status": ["revoked", "unknown", None],
            "observed_at_epoch": [939, 1001, True],
            "expires_at_epoch": [1000, False],
            "approval_id": ["another-approval"],
            "approval_sha256": ["e" * 64],
            "generation": [0, -1, True, "1"],
        }
        for field, values in changes.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    records = copy.deepcopy(self.records)
                    status = copy.deepcopy(self.status)
                    status[field] = value
                    records["status"] = self.sign(status, self.revoker)
                    self.assert_denied(self.provider(read_records=lambda: records)())

    def test_concurrent_record_replacement_is_denied(self):
        calls = iter([self.records, {}])
        self.assert_denied(self.provider(read_records=lambda: next(calls))())

    def test_expiration_during_read_is_denied(self):
        ticks = iter([1000, 1010])
        self.assert_denied(self.provider(clock=lambda: next(ticks))())

    def test_provider_exception_does_not_leak_details(self):
        def broken():
            raise RuntimeError("sensitive-example-not-a-credential")
        row = self.provider(read_records=broken)()
        self.assert_denied(row)
        self.assertNotIn("sensitive-example", repr(row))

    def test_clock_exception_and_invalid_clock_deny(self):
        def broken():
            raise RuntimeError("clock failure")
        for clock in (broken, lambda: True, lambda: float("nan"), lambda: -1):
            self.assert_denied(self.provider(clock=clock)())

    def test_no_review_or_self_revocation_trust_root_rejected(self):
        with self.assertRaises(OperatorAuthorizationDenied):
            self.provider(independently_reviewed=False)
        with self.assertRaises(OperatorAuthorizationDenied):
            self.provider(revocation_public_key=self.public(self.operator))

    def test_partial_collector_registration_cannot_install_or_authorize(self):
        with patch("bot.pretrade_multi_account_registration_v474.install_authenticated_collector") as install:
            with self.assertRaises(PermissionError):
                register_reviewed_account_registry(
                    providers_by_account={self.binding.account: {"operator_authorization": self.provider()}},
                    trusted_provider_ids={}, independently_reviewed=False,
                )
            with self.assertRaises(ValueError):
                register_reviewed_account_registry(
                    providers_by_account={self.binding.account: {"operator_authorization": self.provider()}},
                    trusted_provider_ids={}, independently_reviewed=True,
                )
            install.assert_not_called()

    def complete_providers(self):
        ids = {field: field for field in REQUIRED}
        ids["operator_authorization"] = self.binding.provider_id
        rows = {
            field: {
                "account": self.binding.account, "source": SOURCES[field],
                "provider_id": ids[field], "evidence_id": field,
                "observed_at_epoch": 1000, "verified": True, "read_only": True, "scope_verified": True,
                "provenance": {
                    "account_scope_verified": True, "collector_identity_verified": True,
                    "snapshot_complete": True, "complete_pagination_verified": True,
                    PROOF_BY_SOURCE[SOURCES[field]]: True,
                },
            } for field in REQUIRED
        }
        rows["operator_authorization"] = self.provider()()
        return {field: lambda row=row: copy.deepcopy(row) for field, row in rows.items()}, ids

    def test_expiry_survives_collector_and_cached_diagnostic_read(self):
        providers, ids = self.complete_providers()
        collector = make_collector({self.binding.account: providers}, trusted_provider_ids=ids)
        adapter = partial(collect_independent_pretrade_evidence, clock=lambda: time.time())
        with patch("bot.pretrade_composition_bridge_v465.collect_independent_pretrade_evidence", adapter):
            with patch("time.time", return_value=1000):
                raw = collector(self.binding.account)
        self.assertEqual(raw["expires_at_epoch"], 1010)
        with patch("bot.pretrade_independent_attestation._COLLECTOR", lambda account: raw):
            row = inspect_authenticated_attestations(self.binding.account, now=1010)
        self.assertFalse(any(row["checks"].values()))
        self.assertEqual(row["producer_status"], "observation_expired")
        self.assertFalse(row["authorizes_orders"])
        with patch("bot.pretrade_composition_bridge_v465.collect_independent_pretrade_evidence", adapter):
            with patch("time.time", return_value=1010):
                with self.assertRaises(IndependentEvidenceRejected) as denied:
                    collector(self.binding.account)
                self.assertEqual(denied.exception.failure_reasons, {"operator_authorization": "observation_expired"})

    def test_expiry_during_registration_rejects_collector_install(self):
        providers, ids = self.complete_providers()
        collector = make_collector({self.binding.account: providers}, trusted_provider_ids=ids)
        adapter = partial(collect_independent_pretrade_evidence, clock=lambda: time.time())
        with patch("bot.pretrade_composition_bridge_v465.collect_independent_pretrade_evidence", adapter):
            with patch("time.time", return_value=1000):
                raw = collector(self.binding.account)
        with patch("bot.pretrade_multi_account_registration_v474.make_collector", return_value=lambda _: raw):
            with patch("time.time", return_value=1010):
                with patch("bot.pretrade_multi_account_registration_v474.install_authenticated_collector") as install:
                    with self.assertRaises(ValueError):
                        register_reviewed_account_registry(
                            providers_by_account={self.binding.account: providers},
                            trusted_provider_ids=ids, independently_reviewed=True,
                        )
                    install.assert_not_called()

    def test_signed_approval_cannot_consume_live_dispatch_without_admission_store(self):
        from bot.account_admission_dispatch_boundary_v470 import consume_verified_entry
        from bot.account_order_admission import AdmissionDenied
        from bot.order_admission_policy import Candidate
        self.assertTrue(self.provider()()["verified"])
        with self.assertRaises(AdmissionDenied):
            consume_verified_entry(
                None, Candidate(self.binding.account, self.binding.api_key_sha256, 1, "a" * 64),
            )


if __name__ == "__main__":
    unittest.main()
