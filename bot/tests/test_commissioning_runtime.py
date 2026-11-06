"""Offline tests for inert production commissioning adapters."""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bot.account_order_admission import AdmissionDenied
from bot.broker_manager import BrokerType, KrakenBroker
from bot.commissioning_runtime import (
    CommissioningCompositionDenied,
    CommissioningDispatchAdapter,
    SigningKeyCustodian,
    install_commissioning_dispatch_adapter,
    load_operator_public_keys,
    load_status_public_key,
    make_observations,
)
from bot.execution_dispatch_contract import is_internal_dispatch_failure
from bot.execution_pipeline import ExecutionPipeline
from bot.order_admission_policy import Candidate
from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot.startup_verification_plan import StartupVerificationPlan


class CommissioningRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.plan = StartupVerificationPlan(
            account_fingerprint="a" * 64, api_key_fingerprint="b" * 128,
            symbol="BTC-USD", pair="XXBTZUSD", budget_usd="25", entry_limit="1000",
            base_quantity="0.020", fee_rate_max="0.01", fee_cash_reserve_usd="0.20",
            stop_trigger="950", stop_limit="900", close_limit="990", base_quantum="0.001",
            minimum_base="0.001", minimum_quote="1", expires_at_epoch=2_000_000_000,
        )
        self.candidate = Candidate(
            "platform:kraken", self.plan.api_key_fingerprint, 1, self.plan.digest(),
        )
        self.gate = SimpleNamespace(
            ledger=Path("/tmp/commissioning-test.db"),
            account_scope="platform:kraken",
            collector=lambda *_: None,
            fence=lambda *_: True,
            consume_first_trade=self.consume,
        )
        self.consumed = []
        self.request = SimpleNamespace(
            symbol="BTC-USD", side="buy", preferred_broker="kraken",
            allowed_brokers=("kraken",), intent_type="entry", order_type="limit",
            time_in_force="FOK", reduce_only=False, short_sell=False,
            borrow_intent=None, margin_mode=None, leverage=None,
            limit_price="1000", size_usd="20", shares="0.020", units=None,
            quantity_mode="shares",
        )

    def consume(self, candidate, plan):
        self.consumed.append((candidate, plan))

    def adapter(self, *, enabled=False):
        return CommissioningDispatchAdapter(
            self.gate, self.plan, lambda _request: self.candidate, enabled,
        )

    @staticmethod
    def _raw_public_key(private_key):
        return private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )

    def _private_json(self, path: Path, value) -> Path:
        path.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    def test_pretrade_dispatch_adapter_is_disabled_by_default(self):
        adapter = self.adapter()
        with self.assertRaisesRegex(AdmissionDenied, "pipeline_request_binding_mismatch"):
            adapter.consume(self.request)
        self.assertEqual(self.consumed, [])

    def test_pipeline_request_must_match_exact_approved_entry(self):
        adapter = self.adapter(enabled=True)
        adapter.consume(self.request)
        self.assertEqual(self.consumed, [(self.candidate, self.plan)])

        for field, value in (
            ("symbol", "ETH-USD"), ("side", "sell"), ("preferred_broker", "coinbase"),
            ("allowed_brokers", ("kraken", "coinbase")), ("order_type", "market"),
            ("time_in_force", "GTC"), ("limit_price", "1001"), ("size_usd", "20.1"),
            ("shares", "0.019"), ("leverage", 2),
        ):
            changed = vars(self.request).copy()
            changed[field] = value
            with self.subTest(field=field):
                with self.assertRaises(AdmissionDenied):
                    adapter.consume(SimpleNamespace(**changed))

    def test_overlapping_consumers_only_consume_one_permission(self) -> None:
        """Hold the winner inside durable consumption until the loser arrives.

        The second caller signals either at lock entry (correct ordering) or
        inside the durable gate (old ordering). Neither schedule uses sleeps:
        both calls overlap while the first gate call is deliberately paused.
        """
        adapter = self.adapter(enabled=True)
        first_in_gate = threading.Event()
        second_progress = threading.Event()
        release_first = threading.Event()
        real_lock = threading.Lock()
        outcomes = {}
        calls = []

        class ObservedLock:
            """Observe contention without changing mutual exclusion."""

            def __enter__(self) -> ObservedLock:
                if threading.current_thread().name == "second-consumer":
                    second_progress.set()
                real_lock.acquire()
                return self

            def __exit__(self, *_exc: object) -> None:
                real_lock.release()

        def consume_permission(candidate: Candidate, plan: StartupVerificationPlan) -> None:
            calls.append((candidate, plan))
            if threading.current_thread().name == "first-consumer":
                first_in_gate.set()
                if not release_first.wait(timeout=10):
                    raise AssertionError("first consumer was not released")
            else:
                # With consume-before-lock, the loser reaches this point
                # before it can observe that the transport is already armed.
                second_progress.set()

        def consume(name: str) -> None:
            try:
                adapter.consume(self.request)
                outcomes[name] = "admitted"
            except Exception as error:
                outcomes[name] = error

        adapter._lock = ObservedLock()
        self.gate.consume_first_trade = consume_permission
        threads = [
            threading.Thread(target=consume, args=(name,), name=name, daemon=True)
            for name in ("first-consumer", "second-consumer")
        ]
        try:
            threads[0].start()
            self.assertTrue(first_in_gate.wait(timeout=5), "winner never reached durable gate")
            threads[1].start()
            self.assertTrue(second_progress.wait(timeout=5), "loser never reached gate or lock")
        finally:
            release_first.set()
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=5)
            self.assertFalse(any(thread.is_alive() for thread in threads), "consumer thread leaked")

        self.assertEqual(calls, [(self.candidate, self.plan)])
        self.assertEqual(outcomes["first-consumer"], "admitted")
        loser = outcomes["second-consumer"]
        self.assertIsInstance(loser, AdmissionDenied)
        self.assertEqual(str(loser), "commissioning_transport_attempt_already_armed")
        self.assertTrue(adapter._armed)

        # Validate the winner's single armed attempt locally; no broker call.
        exact = self.plan.order_parameters("entry")
        exact.update({
            "close[ordertype]": "stop-loss-limit",
            "close[price]": self.plan.stop_trigger,
            "close[price2]": self.plan.stop_limit,
        })
        adapter.validate_kraken_order_request("AddOrder", exact)
        self.assertFalse(adapter._armed)
        with self.assertRaisesRegex(AdmissionDenied, "commissioning_transport_attempt_not_armed"):
            adapter.validate_kraken_order_request("AddOrder", exact)

    def test_kraken_transport_payload_is_bound_to_exact_plan(self):
        adapter = self.adapter(enabled=True)
        exact = self.plan.order_parameters("entry")
        exact.update({
            "close[ordertype]": "stop-loss-limit",
            "close[price]": self.plan.stop_trigger,
            "close[price2]": self.plan.stop_limit,
        })
        adapter.consume(self.request)
        adapter.validate_kraken_order_request("AddOrder", exact)
        for method, params in (
            ("QueryOrders", exact),
            ("AddOrder", {**exact, "leverage": "2"}),
            ("AddOrder", {**exact, "price": "1001"}),
        ):
            with self.subTest(method=method, params=params):
                with self.assertRaises(AdmissionDenied):
                    adapter.validate_kraken_order_request(method, params)

    def test_armed_first_trade_cannot_be_substituted_with_a_sell(self):
        adapter = self.adapter(enabled=True)
        adapter.consume(self.request)
        with self.assertRaisesRegex(AdmissionDenied, "parameters_mismatch"):
            adapter.validate_kraken_order_request("AddOrder", {"type": "sell"})
        with self.assertRaisesRegex(AdmissionDenied, "not_armed"):
            adapter.validate_kraken_order_request(
                "AddOrder", self.plan.order_parameters("entry"),
            )

    def test_slow_admission_does_not_block_exit_or_authorize_entry(self):
        for denied in (False, True):
            with self.subTest(admission_denied=denied):
                adapter = self.adapter(enabled=True)
                entered = threading.Event()
                release = threading.Event()
                exit_done = threading.Event()
                buy_done = threading.Event()
                outcomes = []
                errors = []

                def slow_admission(candidate, plan):
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError("test_admission_release_timeout")
                    if denied:
                        raise AdmissionDenied("test_admission_denied")
                    self.consume(candidate, plan)

                def consume():
                    try:
                        adapter.consume(self.request)
                        outcomes.append("admitted")
                    except AdmissionDenied:
                        outcomes.append("denied")
                    except BaseException as exc:
                        errors.append(exc)

                def validate_sell():
                    try:
                        adapter.validate_kraken_order_request("AddOrder", {"type": "sell"})
                        exit_done.set()
                    except BaseException as exc:
                        errors.append(exc)

                def validate_buy():
                    try:
                        with self.assertRaisesRegex(AdmissionDenied, "not_armed"):
                            adapter.validate_kraken_order_request(
                                "AddOrder", self.plan.order_parameters("entry"),
                            )
                        buy_done.set()
                    except BaseException as exc:
                        errors.append(exc)

                self.gate.consume_first_trade = slow_admission
                consumer = threading.Thread(target=consume)
                validators = [threading.Thread(target=validate_sell), threading.Thread(target=validate_buy)]
                consumer.start()
                try:
                    self.assertTrue(entered.wait(2))
                    for validator in validators:
                        validator.start()
                    # These must finish while admission remains explicitly paused.
                    # No elapsed-time race or sleep determines the interleaving.
                    self.assertTrue(exit_done.wait(2), "protective exit waited for admission")
                    self.assertTrue(buy_done.wait(2), "unauthorized buy waited for admission")
                finally:
                    release.set()
                    consumer.join(5)
                    for validator in validators:
                        if validator.ident is not None:
                            validator.join(5)
                self.assertFalse(consumer.is_alive())
                self.assertTrue(all(not validator.is_alive() for validator in validators))
                self.assertEqual(errors, [])
                self.assertEqual(outcomes, ["denied" if denied else "admitted"])
                if denied:
                    with self.assertRaisesRegex(AdmissionDenied, "not_armed"):
                        adapter.validate_kraken_order_request("AddOrder", self.plan.order_parameters("entry"))
                else:
                    exact = self.plan.order_parameters("entry")
                    exact.update({
                        "close[ordertype]": "stop-loss-limit",
                        "close[price]": self.plan.stop_trigger,
                        "close[price2]": self.plan.stop_limit,
                    })
                    adapter.validate_kraken_order_request("AddOrder", exact)
                    with self.assertRaisesRegex(AdmissionDenied, "not_armed"):
                        adapter.validate_kraken_order_request("AddOrder", exact)

    def test_provider_composition_is_complete_and_collects_once(self):
        calls = {field: 0 for field in REQUIRED}
        providers = {
            field: (lambda field=field: calls.__setitem__(field, calls[field] + 1) or {"field": field})
            for field in REQUIRED
        }
        observe = make_observations(providers)
        rows = observe(self.candidate, None)
        self.assertEqual(set(rows), set(REQUIRED))
        self.assertEqual(set(calls.values()), {1})
        with self.assertRaises(CommissioningCompositionDenied):
            make_observations({field: providers[field] for field in REQUIRED[:-1]})

    def test_public_key_files_are_owner_only_and_public_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            operator = Ed25519PrivateKey.generate()
            status = Ed25519PrivateKey.generate()
            operator_path = self._private_json(root / "operators.json", {
                "operator": base64.b64encode(self._raw_public_key(operator)).decode("ascii"),
            })
            status_path = self._private_json(root / "status.json", {
                "status_public_key": base64.b64encode(self._raw_public_key(status)).decode("ascii"),
            })
            self.assertEqual(load_operator_public_keys(operator_path)["operator"], self._raw_public_key(operator))
            self.assertEqual(load_status_public_key(status_path), self._raw_public_key(status))
            os.chmod(operator_path, 0o644)
            with self.assertRaises(CommissioningCompositionDenied):
                load_operator_public_keys(operator_path)

    def test_signing_custodian_uses_opaque_signer_and_verifies_signature(self):
        key = Ed25519PrivateKey.generate()
        public = self._raw_public_key(key)

        class Hsm:
            def sign(self, key_id, message):
                self.key_id = key_id
                return key.sign(message)

        signer = Hsm()
        custodian = SigningKeyCustodian(signer, {"operator": public})
        envelope = custodian.sign("operator", {"contract": "test", "approved": True})
        key.public_key().verify(
            base64.b64decode(envelope["signature"]),
            json.dumps(envelope["payload"], sort_keys=True, separators=(",", ":")).encode(),
        )
        self.assertEqual(signer.key_id, "operator")

        class BadHsm:
            def sign(self, _key_id, _message):
                return bytes(64)

        with self.assertRaisesRegex(CommissioningCompositionDenied, "signature_verification_failed"):
            SigningKeyCustodian(BadHsm(), {"operator": public}).sign("operator", {"approved": True})

    def test_pipeline_install_requires_review_and_existing_admission_bindings(self):
        adapter = self.adapter(enabled=True)
        admission = SimpleNamespace(
            collector=self.gate.collector, fence=self.gate.fence, ledger=self.gate.ledger,
        )
        broker = KrakenBroker.__new__(KrakenBroker)
        broker.broker_type = BrokerType.KRAKEN
        broker.account_type = "platform"
        broker.user_id = None
        broker._gateway_url = ""
        broker._gateway_only_mode = False
        pipeline = SimpleNamespace(
            _dispatch=lambda *_: None, _account_order_admission=admission,
            _trusted_entry_candidate_provider=adapter.candidate_for_request,
        )
        with self.assertRaises(CommissioningCompositionDenied):
            install_commissioning_dispatch_adapter(pipeline, adapter, broker)
        install_commissioning_dispatch_adapter(
            pipeline, adapter, broker, activation_reviewed=True,
        )
        self.assertIs(pipeline._commissioning_dispatch_adapter, adapter)
        self.assertIs(broker._commissioning_order_request_validator, adapter)
        with self.assertRaises(CommissioningCompositionDenied):
            install_commissioning_dispatch_adapter(
                pipeline, adapter, broker, activation_reviewed=True,
            )

        mismatched = SimpleNamespace(
            _dispatch=lambda *_: None,
            _account_order_admission=SimpleNamespace(
                collector=lambda *_: None, fence=self.gate.fence, ledger=self.gate.ledger,
            ),
            _trusted_entry_candidate_provider=adapter.candidate_for_request,
        )
        with self.assertRaisesRegex(CommissioningCompositionDenied, "binding_mismatch"):
            install_commissioning_dispatch_adapter(
                mismatched, adapter, broker, activation_reviewed=True,
            )

    def test_broker_manager_enforces_exact_entry_before_gateway_or_api_calls(self):
        adapter = self.adapter(enabled=True)
        adapter.consume(self.request)
        broker = SimpleNamespace(
            _hard_stopped=False,
            _commissioning_order_request_validator=adapter,
            _gateway_url="",
            _gateway_only_mode=False,
            api=None,
        )
        exact = self.plan.order_parameters("entry")
        exact.update({
            "close[ordertype]": "stop-loss-limit",
            "close[price]": self.plan.stop_trigger,
            "close[price2]": self.plan.stop_limit,
        })
        with self.assertRaisesRegex(Exception, "API not initialized"):
            KrakenBroker._kraken_private_call(broker, "AddOrder", exact)

        adapter.consume(self.request)
        wrong = dict(exact, price="1001")
        with self.assertRaisesRegex(AdmissionDenied, "parameters_mismatch") as denied:
            KrakenBroker._kraken_private_call(broker, "AddOrder", wrong)
        self.assertTrue(is_internal_dispatch_failure(str(denied.exception)))

    def test_pipeline_dispatch_does_not_fall_back_when_commissioning_is_disabled(self):
        adapter = self.adapter()
        admission = SimpleNamespace(
            collector=self.gate.collector, fence=self.gate.fence, ledger=self.gate.ledger,
        )
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        pipeline._account_order_admission = admission
        pipeline._trusted_entry_candidate_provider = adapter.candidate_for_request
        pipeline._commissioning_dispatch_adapter = adapter
        pipeline._multi_router = None
        pipeline._router = None

        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=SimpleNamespace(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(self.request, 0.0)
        self.assertFalse(result.success)
        self.assertIn("commissioning_reservation_unavailable", result.error)
        self.assertEqual(self.consumed, [])

    def test_private_dispatch_call_cannot_skip_execute_gate_context(self):
        adapter = self.adapter(enabled=True)
        adapter._terminal_broker = SimpleNamespace(
            _commissioning_order_request_validator=adapter,
            _gateway_url="",
            _gateway_only_mode=False,
        )
        admission = SimpleNamespace(
            collector=self.gate.collector, fence=self.gate.fence, ledger=self.gate.ledger,
        )
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        pipeline._account_order_admission = admission
        pipeline._trusted_entry_candidate_provider = adapter.candidate_for_request
        pipeline._commissioning_dispatch_adapter = adapter
        pipeline._multi_router = None
        pipeline._router = None

        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=SimpleNamespace(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(self.request, 0.0)
        self.assertFalse(result.success)
        self.assertIn("commissioning_reservation_unavailable", result.error)
        self.assertEqual(self.consumed, [])


if __name__ == "__main__":
    unittest.main()
