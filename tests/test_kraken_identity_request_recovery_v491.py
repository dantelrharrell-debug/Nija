"""Offline one-shot identity recovery and real worker-routing regressions."""
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bot import kraken_identity_request_recovery_v491 as recovery
from bot.kraken_authenticated_identity_v480 import _fingerprint_iban
from bot.kraken_live_history_recovery import collect_requested_history
from bot.kraken_exact_pending_order_recovery_v466 import collect_requested_exact_pending_orders

ROOT = Path(__file__).resolve().parents[1]
KEY = "fixture-only-key"
IBAN = "fixture-only-account"
CATEGORY = object()


class IdentityRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.calls = []
        self.response = {"error": [], "result": {
            "apiKey": KEY, "iban": IBAN, "validUntil": "0",
        }}
        self.broker = SimpleNamespace(
            broker_type="kraken", account_type="platform", user_id=None,
            connected=True, _kraken_private_call=self.read,
        )
        self.binding = {
            "account_scope": "platform:kraken",
            "approval_source": "offline-fixture-only",
            "approved_account_iiban_sha256": _fingerprint_iban(IBAN),
            "approved_api_key_sha256": hashlib.sha256(KEY.encode()).hexdigest(),
            "approved_at_utc": dt.datetime.fromtimestamp(
                time.time() - 30, dt.timezone.utc,
            ).isoformat(),
            "authenticated_identity_match_verified": False,
            "independent_statement_reference": "offline-fixture-reference",
            "runtime_collector_installed": False, "trading_authorized": False,
        }
        self.write(recovery.BINDING_NAME, self.binding)

    def read(self, endpoint, params, *, category):
        self.assertEqual(endpoint, "GetApiKeyInfo")
        self.assertEqual(params, {})
        self.assertIs(category, CATEGORY)
        self.calls.append(endpoint)
        return self.response

    def write(self, name, value):
        p = self.root / name
        p.write_text(json.dumps(value))
        p.chmod(0o600)

    def request(self, **extra):
        row = {"request_id": "a" * 32, "account_scope": "platform:kraken",
               "max_pages": 1, "created_at": time.time() - 1}
        row.update(extra)
        self.write("identity_request.json", row)

    def run_request(self, brokers=None, category=CATEGORY):
        return recovery.collect_requested_identity(
            self.root, [self.broker] if brokers is None else brokers,
            monitoring_category=category,
        )

    def receipt(self):
        return json.loads((self.root / (("a" * 32) + ".identity.evidence.json")).read_text())

    def test_explicit_native_mode_is_forwarded_but_missing_native_proof_still_denies(self):
        self.binding["identity_method"] = "native_signed_request_v1"
        self.write(recovery.BINDING_NAME, self.binding)
        self.request()
        original = recovery.make_kraken_account_identity_provider
        with patch.object(recovery, "make_kraken_account_identity_provider", wraps=original) as factory:
            self.assertTrue(self.run_request())
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["identity_method"], "native_signed_request_v1")
        row = self.receipt()
        self.assertFalse(row["collection_succeeded"])
        self.assertFalse(row["trading_authorized"])
        self.assertFalse(row["collector_installed"])

    def test_invalid_saved_identity_modes_deny_before_broker_read(self):
        for value in (None, True, "fallback", "native_signed_request_v1 ", 1):
            with self.subTest(value=value):
                self.binding["identity_method"] = value
                self.write(recovery.BINDING_NAME, self.binding)
                with self.assertRaises(ValueError):
                    recovery._binding(self.root, time.time())
        self.assertEqual(self.calls, [])

    def test_no_request_never_reads_or_creates_a_request(self):
        self.assertFalse(self.run_request())
        self.assertFalse((self.root / "identity_request.json").exists())
        self.assertEqual(self.calls, [])

    def test_success_uses_existing_broker_once_and_preserves_non_authority(self):
        self.request()
        before = (self.root / recovery.BINDING_NAME).read_bytes()
        self.assertTrue(self.run_request([self.broker, self.broker]))
        row = self.receipt()
        self.assertEqual(self.calls, ["GetApiKeyInfo"])
        self.assertTrue(row["configured_account_and_key_match"])
        self.assertFalse(row["trading_authorized"])
        self.assertFalse(row["collector_installed"])
        self.assertFalse(row["independent_certification_complete"])
        self.assertTrue(row["diagnostic_only"])
        self.assertEqual(before, (self.root / recovery.BINDING_NAME).read_bytes())
        self.assertNotIn(KEY, json.dumps(row))
        self.assertNotIn(IBAN, json.dumps(row))
        self.assertEqual((self.root / (("a" * 32) + ".identity.evidence.json")).stat().st_mode & 0o077, 0)
        self.assertFalse(self.run_request())
        self.assertEqual(len(self.calls), 1)

    def test_consumed_success_and_failure_are_never_replayed(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.setUp()
                if fail:
                    self.response = {"error": ["credential-and-account-material"]}
                self.request()
                self.run_request()
                self.assertEqual(self.receipt()["collection_succeeded"], not fail)
                self.request()
                with self.assertRaisesRegex(ValueError, "replay"):
                    self.run_request()
                self.assertEqual(len(self.calls), 1)

    def test_duplicate_binding_keys_and_symlinks_are_rejected_before_api_read(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                self.setUp()
                p = self.root / recovery.BINDING_NAME
                if symlink:
                    target = self.root / "binding-copy.json"
                    p.rename(target)
                    p.symlink_to(target)
                else:
                    p.write_text('{"account_scope":"platform:kraken","account_scope":"platform:kraken"}')
                self.request()
                self.run_request()
                self.assertFalse(self.receipt()["collection_succeeded"])
                self.assertEqual(self.calls, [])

    def test_wrong_key_account_and_expired_key_fail_closed(self):
        for field, value, code in (
            ("apiKey", "different-fixture-key", "approved_api_key_identity_mismatch"),
            ("iban", "different-fixture-account", "approved_broker_account_mismatch"),
            ("validUntil", "1", "key_expired"),
        ):
            with self.subTest(field=field):
                self.setUp()
                self.request()
                self.response["result"][field] = value
                self.run_request()
                row = self.receipt()
                self.assertFalse(row["collection_succeeded"])
                self.assertFalse(row["trading_authorized"])
                self.assertEqual(row["failure_code"], code)
                self.assertEqual(len(self.calls), 1)

    def test_missing_identity_receipt_contains_only_safe_field_shapes(self):
        self.request()
        del self.response["result"]["apiKey"]
        self.response["result"]["private-fixture-secret"] = "do-not-persist"  # pragma: allowlist secret (offline fixture)
        self.run_request()
        row = self.receipt()
        self.assertFalse(row["collection_succeeded"])
        self.assertEqual(row["failure_code"], "authenticated_api_key_identity_missing")
        self.assertEqual(row["identity_response_shape"], {
            "apiKey": "missing", "iban": "string", "validUntil": "string", "permissions": "missing",  # pragma: allowlist secret (offline fixture)
        })
        for secret in (KEY, IBAN, "private-fixture-secret", "do-not-persist"):
            self.assertNotIn(secret, json.dumps(row))
        self.assertFalse(row["trading_authorized"])


    def test_parsed_field_presence_records_missing_identity_without_secrets(self):
        for absent, expected in (
            (("apiKey",), (False, True)),
            (("validUntil",), (True, False)),
            (("apiKey", "validUntil"), (False, False)),
        ):
            with self.subTest(absent=absent):
                self.setUp()
                for field in absent:
                    self.response["result"].pop(field)
                self.request()
                self.assertTrue(self.run_request())
                row = self.receipt()
                self.assertFalse(row["collection_succeeded"])
                presence = row["parsed_identity_field_presence"]
                self.assertEqual(
                    tuple(presence[name] for name in ("apiKey", "validUntil")), expected,
                )
                self.assertEqual(set(presence), {"apiKey", "validUntil"})
                self.assertFalse(row["trading_authorized"])
                self.assertFalse(row["collector_installed"])
                self.assertEqual(self.calls, ["GetApiKeyInfo"])
                self.assertNotIn(KEY, json.dumps(row))
                self.assertNotIn(IBAN, json.dumps(row))


    def test_identity_shape_whitelist_cannot_export_values(self):
        from bot.kraken_authenticated_identity_v480 import KrakenIdentityDenied, _identity_response_shape
        for value, expected in ((None, "null"), ("", "empty_string"),
                                (["secret"], "list"), ({"secret": "value"}, "other")):  # pragma: allowlist secret (offline fixture)
            with self.subTest(expected=expected):
                shape = _identity_response_shape({"apiKey": value})
                self.assertEqual(shape["apiKey"], expected)
                self.assertNotIn("secret", json.dumps(shape))
        exc = KrakenIdentityDenied("fixed-denial", response_shape={
            "apiKey": "sensitive-value", "unknown-secret-field": "string", "iban": "missing",  # pragma: allowlist secret (offline fixture)
        })
        self.assertEqual(exc.response_shape, {"iban": "missing"})

    def test_missing_binding_and_shared_binding_do_not_call_the_broker(self):
        for shared in (False, True):
            with self.subTest(shared=shared):
                self.setUp()
                p = self.root / recovery.BINDING_NAME
                if shared:
                    p.chmod(0o644)
                else:
                    p.unlink()
                self.request()
                self.run_request()
                self.assertFalse(self.receipt()["collection_succeeded"])
                self.assertEqual(self.calls, [])

    def test_binding_replacement_during_read_is_rejected(self):
        original = self.read

        def read(*args, **kwargs):
            result = original(*args, **kwargs)
            self.binding["approval_source"] = "changed-fixture"
            self.write(recovery.BINDING_NAME, self.binding)
            return result

        self.broker._kraken_private_call = read
        self.request()
        self.run_request()
        self.assertFalse(self.receipt()["collection_succeeded"])
        self.assertEqual(len(self.calls), 1)

    def test_identical_content_binding_replacement_during_read_is_rejected(self):
        original = self.read

        def read(*args, **kwargs):
            result = original(*args, **kwargs)
            p = self.root / recovery.BINDING_NAME
            replacement = self.root / "replacement.json"
            replacement.write_bytes(p.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(p)
            return result

        self.broker._kraken_private_call = read
        self.request()
        self.run_request()
        self.assertFalse(self.receipt()["collection_succeeded"])
        self.assertEqual(len(self.calls), 1)

    def test_each_collector_rechecks_conflicting_modes_under_shared_lock(self):
        self.request()
        self.write("request.json", {})
        self.write("exact_request.json", {})
        for fn in (recovery.collect_requested_identity, collect_requested_history,
                   collect_requested_exact_pending_orders):
            with self.subTest(collector=fn.__name__):
                self.assertFalse(fn(self.root, [self.broker], monitoring_category=CATEGORY))
                self.assertTrue((self.root / "identity_request.json").exists())
                self.assertTrue((self.root / "request.json").exists())
                self.assertTrue((self.root / "exact_request.json").exists())
                self.assertEqual(self.calls, [])

    def test_exception_text_and_upstream_rows_are_never_persisted(self):
        def read(*args, **kwargs):
            self.calls.append("GetApiKeyInfo")
            raise RuntimeError("sensitive-fixture-do-not-persist")

        self.broker._kraken_private_call = read
        self.request()
        self.run_request()
        self.assertNotIn("sensitive-fixture", json.dumps(self.receipt()))
        self.assertEqual(len(self.calls), 1)

    def test_ambiguous_or_missing_live_client_defers_without_consumption(self):
        self.request()
        other = SimpleNamespace(**vars(self.broker))
        for brokers, category in [([], CATEGORY), ([self.broker, other], CATEGORY), ([self.broker], None)]:
            with self.subTest(count=len(brokers), category=category):
                self.assertFalse(self.run_request(brokers, category))
                self.assertTrue((self.root / "identity_request.json").exists())
                self.assertEqual(self.calls, [])

    def test_expired_wrong_scope_and_invalid_budget_never_read(self):
        for extra in ({"created_at": time.time() - 301}, {"max_pages": 2},
                      {"account_scope": "user:fixture:kraken"}, {"use_cursor": True}):
            with self.subTest(extra=extra):
                self.request(**extra)
                with self.assertRaises(ValueError):
                    self.run_request()
                self.assertEqual(self.calls, [])

    def worker(self):
        source = (ROOT / "bot/runtime_kraken_deferred_fill_proof_recovery_v363_patch.py").read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == "_start_requested_history_collection")

        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                self.target()

            def is_alive(self):
                return False

        ns = {"os": os, "Path": Path, "_HISTORY_THREAD": None,
              "LOGGER": Mock(), "_LOCK": threading.RLock(),
              "threading": SimpleNamespace(Thread=ImmediateThread),
              "_kraken_brokers": lambda: [self.broker],
              "_v357": lambda: SimpleNamespace(_monitoring_category=lambda: CATEGORY)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<worker>", "exec"), ns)
        return ns

    def test_existing_worker_routes_opt_in_identity_request(self):
        self.request()
        ns = self.worker()
        with patch.dict(os.environ, {"NIJA_KRAKEN_HISTORY_RECOVERY_DIR": str(self.root)}):
            ns["_start_requested_history_collection"]()
        self.assertEqual(self.calls, ["GetApiKeyInfo"])
        self.assertTrue(self.receipt()["configured_account_and_key_match"])

    def test_worker_defers_concurrent_recovery_modes(self):
        self.request()
        self.write("request.json", {})
        ns = self.worker()
        with patch.dict(os.environ, {"NIJA_KRAKEN_HISTORY_RECOVERY_DIR": str(self.root)}):
            ns["_start_requested_history_collection"]()
        self.assertEqual(self.calls, [])
        self.assertIsNone(ns["_HISTORY_THREAD"])
        self.assertTrue((self.root / "identity_request.json").exists())


if __name__ == "__main__":
    unittest.main()
