"""
Tests for the 10 downstream execution blockers.

Each test validates that the corresponding blocker is correctly identified,
classified, and handled (either gracefully returned or properly raised).
"""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1–2. BlockerType enum and ExchangeErrorClassifier
# ---------------------------------------------------------------------------

from bot.downstream_blocker_guard import (
    BlockerType,
    ExchangeErrorClassifier,
    DownstreamBlockerGuard,
    get_downstream_blocker_guard,
)


class TestBlockerTypeEnum(unittest.TestCase):
    def test_all_10_blockers_present(self):
        expected = {
            "broker_auth", "order_sizing", "insufficient_balance",
            "slippage_spread", "post_only_reject", "min_notional",
            "risk_governor", "adapter_exception", "ack_timeout",
            "reconciliation",
        }
        actual = {b.value for b in BlockerType if b != BlockerType.UNKNOWN}
        self.assertEqual(actual, expected)

    def test_unknown_not_in_soft_set(self):
        self.assertFalse(ExchangeErrorClassifier.is_soft_blocker(BlockerType.UNKNOWN))

    def test_all_10_are_soft_blockers(self):
        soft = [
            BlockerType.BROKER_AUTH, BlockerType.ORDER_SIZING,
            BlockerType.INSUFFICIENT_BALANCE, BlockerType.SLIPPAGE_SPREAD,
            BlockerType.POST_ONLY_REJECT, BlockerType.MIN_NOTIONAL,
            BlockerType.RISK_GOVERNOR, BlockerType.ADAPTER_EXCEPTION,
            BlockerType.ACK_TIMEOUT, BlockerType.RECONCILIATION,
        ]
        for bt in soft:
            self.assertTrue(
                ExchangeErrorClassifier.is_soft_blocker(bt),
                f"{bt.value} should be a soft blocker",
            )


# ---------------------------------------------------------------------------
# 3. Broker auth errors
# ---------------------------------------------------------------------------

class TestBrokerAuthClassification(unittest.TestCase):
    def _classify(self, msg: str) -> BlockerType:
        return ExchangeErrorClassifier.classify(msg)

    def test_invalid_api_key(self):
        self.assertEqual(self._classify("Invalid API Key"), BlockerType.BROKER_AUTH)

    def test_401_response(self):
        self.assertEqual(self._classify("HTTP 401 Unauthorized"), BlockerType.BROKER_AUTH)

    def test_403_response(self):
        self.assertEqual(self._classify("403 Forbidden"), BlockerType.BROKER_AUTH)

    def test_signature_mismatch(self):
        self.assertEqual(self._classify("signature mismatch in request"), BlockerType.BROKER_AUTH)

    def test_authentication_failed(self):
        self.assertEqual(self._classify("Authentication failed"), BlockerType.BROKER_AUTH)


# ---------------------------------------------------------------------------
# 4. Order sizing errors
# ---------------------------------------------------------------------------

class TestOrderSizingClassification(unittest.TestCase):
    def test_invalid_base_size(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("INVALID_BASE_SIZE: 0.001 does not meet step"),
            BlockerType.ORDER_SIZING,
        )

    def test_lot_size(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("lot size not met"),
            BlockerType.ORDER_SIZING,
        )


# ---------------------------------------------------------------------------
# 5. Insufficient balance
# ---------------------------------------------------------------------------

class TestInsufficientBalanceClassification(unittest.TestCase):
    def test_coinbase_message(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("Insufficient funds"),
            BlockerType.INSUFFICIENT_BALANCE,
        )

    def test_kraken_ebalance(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("EBalance:Insufficient funds"),
            BlockerType.INSUFFICIENT_BALANCE,
        )


# ---------------------------------------------------------------------------
# 6. Post-only rejects
# ---------------------------------------------------------------------------

class TestPostOnlyClassification(unittest.TestCase):
    def test_post_only_string(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("Order is post_only but would immediately match"),
            BlockerType.POST_ONLY_REJECT,
        )

    def test_maker_only(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("maker only order rejected"),
            BlockerType.POST_ONLY_REJECT,
        )

    def test_kraken_post_only(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("post only order would trade against resting"),
            BlockerType.POST_ONLY_REJECT,
        )


# ---------------------------------------------------------------------------
# 7. Exchange min notional
# ---------------------------------------------------------------------------

class TestMinNotionalClassification(unittest.TestCase):
    def test_coinbase_min_funds(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("Order value too small, below minimum notional"),
            BlockerType.MIN_NOTIONAL,
        )

    def test_kraken_eordermin(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("EOrderMin:Order minimum not met"),
            BlockerType.MIN_NOTIONAL,
        )

    def test_below_minimum(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("order size below minimum"),
            BlockerType.MIN_NOTIONAL,
        )


# ---------------------------------------------------------------------------
# 8. ACK timeout
# ---------------------------------------------------------------------------

class TestACKTimeoutClassification(unittest.TestCase):
    def test_ack_timeout_string(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("ack_timeout: broker did not respond within 30s"),
            BlockerType.ACK_TIMEOUT,
        )

    def test_order_not_found(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("Order not found after submission"),
            BlockerType.ACK_TIMEOUT,
        )

    def test_gateway_timeout_504(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("504 gateway timeout"),
            BlockerType.ACK_TIMEOUT,
        )


# ---------------------------------------------------------------------------
# 9. Adapter exceptions
# ---------------------------------------------------------------------------

class TestAdapterExceptionClassification(unittest.TestCase):
    def test_connection_error(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("ConnectionError: Remote end closed connection"),
            BlockerType.ADAPTER_EXCEPTION,
        )

    def test_ssl_error(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("SSLError: certificate verify failed"),
            BlockerType.ADAPTER_EXCEPTION,
        )


# ---------------------------------------------------------------------------
# 10. Reconciliation failures
# ---------------------------------------------------------------------------

class TestReconciliationClassification(unittest.TestCase):
    def test_reconciliation_string(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("reconciliation failure detected"),
            BlockerType.RECONCILIATION,
        )

    def test_discrepancy(self):
        self.assertEqual(
            ExchangeErrorClassifier.classify("position discrepancy found"),
            BlockerType.RECONCILIATION,
        )


# ---------------------------------------------------------------------------
# 11. DownstreamBlockerGuard – risk governor gate
# ---------------------------------------------------------------------------

class TestDownstreamBlockerGuardRiskGovernor(unittest.TestCase):
    def test_governor_blocks_when_halted(self):
        guard = DownstreamBlockerGuard.__new__(DownstreamBlockerGuard)
        guard._governor_enabled = True
        guard._slippage_enabled = False
        guard._slippage = None

        mock_gov = MagicMock()
        mock_decision = MagicMock()
        mock_decision.allowed = False
        mock_decision.reason = "daily loss limit exceeded"
        mock_gov.approve_entry.return_value = mock_decision
        guard._governor = mock_gov

        ok, reason, bt = guard.check_risk_governor("BTC-USD", 250.0)
        self.assertFalse(ok)
        self.assertIn("daily loss limit", reason)
        self.assertEqual(bt, BlockerType.RISK_GOVERNOR)

    def test_governor_allows_when_green(self):
        guard = DownstreamBlockerGuard.__new__(DownstreamBlockerGuard)
        guard._governor_enabled = True
        guard._slippage_enabled = False
        guard._slippage = None

        mock_gov = MagicMock()
        mock_decision = MagicMock()
        mock_decision.allowed = True
        mock_decision.reason = "All risk gates GREEN"
        mock_gov.approve_entry.return_value = mock_decision
        guard._governor = mock_gov

        ok, reason, bt = guard.check_risk_governor("BTC-USD", 250.0)
        self.assertTrue(ok)
        self.assertEqual(bt, BlockerType.RISK_GOVERNOR)

    def test_governor_unavailable_passes_through(self):
        guard = DownstreamBlockerGuard.__new__(DownstreamBlockerGuard)
        guard._governor = None
        guard._slippage = None

        ok, reason, bt = guard.check_risk_governor("BTC-USD", 250.0)
        self.assertTrue(ok)
        self.assertIn("pass-through", reason)


# ---------------------------------------------------------------------------
# 12. DownstreamBlockerGuard – slippage gate
# ---------------------------------------------------------------------------

class TestDownstreamBlockerGuardSlippage(unittest.TestCase):
    def test_slippage_blocked(self):
        guard = DownstreamBlockerGuard.__new__(DownstreamBlockerGuard)
        guard._governor = None
        guard._slippage_enabled = True

        mock_prot = MagicMock()
        mock_result = MagicMock()
        mock_result.approved = False
        mock_result.reason = "worst-case slippage 1.200% exceeds max 0.80%"
        mock_prot.check.return_value = mock_result
        guard._slippage = mock_prot

        ok, reason, bt = guard.check_slippage("ETH-USD", "buy", 1000.0, bid=3000.0, ask=3010.0)
        self.assertFalse(ok)
        self.assertIn("worst-case slippage", reason)
        self.assertEqual(bt, BlockerType.SLIPPAGE_SPREAD)

    def test_slippage_passes_without_bid_ask(self):
        guard = DownstreamBlockerGuard.__new__(DownstreamBlockerGuard)
        guard._slippage = MagicMock()

        ok, reason, bt = guard.check_slippage("BTC-USD", "buy", 500.0, bid=0.0, ask=0.0)
        self.assertTrue(ok)
        self.assertIn("pass-through", reason)

    def test_slippage_unavailable_passes_through(self):
        guard = DownstreamBlockerGuard.__new__(DownstreamBlockerGuard)
        guard._slippage = None

        ok, reason, bt = guard.check_slippage("BTC-USD", "sell", 200.0, bid=50000.0, ask=50010.0)
        self.assertTrue(ok)
        self.assertIn("pass-through", reason)


# ---------------------------------------------------------------------------
# 13. ExecutionPipeline – soft reject does NOT raise SystemError
# ---------------------------------------------------------------------------

class TestExecutionPipelineSoftReject(unittest.TestCase):
    def _make_pipeline_with_mocked_router(self, router_error: str):
        """Return an ExecutionPipeline whose router always returns *router_error*."""
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest, PipelineResult

        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._lock = __import__("threading").Lock()
        pipeline._ecel = None
        pipeline._ecel_mod = None
        pipeline._ecel_required = False
        pipeline._ecel_fail_closed = False
        pipeline._ecel_refresh_stop = __import__("threading").Event()
        pipeline._ecel_refresh_thread = None
        pipeline._throttler = None
        pipeline._router = None
        pipeline._multi_router = None
        pipeline._pre_trade_risk_engine = None
        pipeline._exchange_normalizer = None
        pipeline._allocation_clamp = None
        pipeline._execution_observer = None
        pipeline._downstream_guard = None
        pipeline._ack_timeout_s = 5.0
        pipeline._run_count = 0
        pipeline._blocked_count = 0
        pipeline._last_run = None

        # Inject a mock router that returns a failed result
        mock_router = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.success = False
        mock_exec_result.fill_price = 0.0
        mock_exec_result.filled_size_usd = 0.0
        mock_exec_result.error = router_error
        mock_router.execute.return_value = mock_exec_result
        pipeline._router = mock_router

        return pipeline

    def _build_request(self):
        from bot.execution_pipeline import PipelineRequest
        return PipelineRequest(
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            validated=True,
        )

    def test_auth_error_does_not_raise(self):
        from bot.execution_pipeline import ExecutionPipeline
        pipeline = self._make_pipeline_with_mocked_router("Invalid API Key")
        request = self._build_request()
        # Should not raise SystemError
        try:
            pipeline._on_order_rejected(request, "Invalid API Key")
        except SystemError:
            self.fail("_on_order_rejected raised SystemError for a soft (auth) error")

    def test_post_only_does_not_raise(self):
        from bot.execution_pipeline import ExecutionPipeline
        pipeline = self._make_pipeline_with_mocked_router("post_only reject")
        request = self._build_request()
        try:
            pipeline._on_order_rejected(request, "post_only reject")
        except SystemError:
            self.fail("_on_order_rejected raised SystemError for post-only soft error")

    def test_ack_timeout_does_not_raise(self):
        from bot.execution_pipeline import ExecutionPipeline
        pipeline = self._make_pipeline_with_mocked_router("ack_timeout: broker silent")
        request = self._build_request()
        try:
            pipeline._on_order_rejected(request, "ack_timeout: broker silent")
        except SystemError:
            self.fail("_on_order_rejected raised SystemError for ACK timeout soft error")

    def test_unknown_error_raises_system_error(self):
        from bot.execution_pipeline import ExecutionPipeline
        pipeline = self._make_pipeline_with_mocked_router("some completely unknown error xyz")
        request = self._build_request()
        with self.assertRaises(SystemError):
            pipeline._on_order_rejected(request, "some completely unknown error xyz")


# ---------------------------------------------------------------------------
# 14. ExecutionPipeline – ACK timeout in _dispatch
# ---------------------------------------------------------------------------

class TestExecutionPipelineACKTimeout(unittest.TestCase):
    def _install_offline_admission(self, pipeline):
        """Isolate transport tests after the separately tested admission boundary."""
        from bot.account_order_admission import AccountOrderAdmission, Reservation
        from bot.order_admission_policy import Candidate

        candidate = Candidate("platform:kraken", "offline-credential", 1, "a" * 64)
        reservation = Reservation("offline-reservation", candidate)
        admission = AccountOrderAdmission.__new__(AccountOrderAdmission)
        admission.reserve = MagicMock(return_value=reservation)
        admission.consume = MagicMock()
        pipeline._account_order_admission = admission
        pipeline._trusted_entry_candidate_provider = MagicMock(return_value=candidate)

    def _assert_admission_consumed(self, pipeline, request):
        """Assert the real durable fixture, not the replaced mock admission."""
        import sqlite3

        provider = pipeline._trusted_entry_candidate_provider
        candidate = provider(request)
        self.assertIsNotNone(candidate)
        self.assertIsNone(provider(object()))
        admission = pipeline._account_order_admission
        with sqlite3.connect(admission.ledger) as conn:
            rows = conn.execute(
                "SELECT account, credential_fingerprint, writer_generation, intent_digest, state "
                "FROM account_entry_reservations"
            ).fetchall()
        self.assertEqual(rows, [(
            candidate.account, candidate.credential_fingerprint,
            candidate.writer_generation, candidate.intent_digest, "submitting",
        )])
    """Exercise real durable entry admission with *offline* broker-less facts.

    The mocked ACK responses below must reach dispatch only after the same
    on-disk reservation boundary as production. These fixtures are synthetic
    local CI evidence, not authenticated brokerage observations or an
    installation of production collectors.
    """

    def _install_offline_entry_admission(self, pipeline, request):
        import hashlib
        import sqlite3
        import tempfile
        from pathlib import Path

        from bot.account_order_admission import AccountOrderAdmission
        from bot.order_admission_policy import (
            Candidate, CurrentFact, OrderOutcome, REQUIRED_CONTROLS,
        )

        folder = tempfile.TemporaryDirectory(prefix="nija-ack-offline-")
        self.addCleanup(folder.cleanup)
        ledger = Path(folder.name) / "test-ledger.sqlite3"
        with sqlite3.connect(ledger) as conn:
            for table in ("open_positions", "completed_trades", "strategy_order_intents"):
                conn.execute("CREATE TABLE " + table + " (id INTEGER)")
            conn.execute(
                "CREATE TABLE trade_ledger "
                "(user_id TEXT, order_id TEXT, position_id TEXT, action TEXT)"
            )
            conn.execute(
                "CREATE TABLE pending_kraken_closes "
                "(broker TEXT, account_scope TEXT, user_id TEXT, order_id TEXT, "
                "state TEXT, matched_position_id TEXT)"
            )

        digest = hashlib.sha256(
            (self.id() + ":" + str(request.request_id)).encode("utf-8")
        ).hexdigest()
        candidate = Candidate(
            account="platform:kraken",
            credential_fingerprint="synthetic-ci-credential-only",
            writer_generation=1,
            intent_digest=digest,
        )

        def read_only_test_collector(bound_candidate, conn):
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone(), (1,))
            conn.execute("SELECT COUNT(*) FROM trade_ledger").fetchone()
            facts = {
                key: CurrentFact(bound_candidate, True, time.time(), "offline-ci-fixture")
                for key in REQUIRED_CONTROLS
            }
            return facts, OrderOutcome(bound_candidate.account, "none")

        def test_writer_fence(bound_candidate):
            return bound_candidate == candidate

        store = AccountOrderAdmission(
            ledger, read_only_test_collector, test_writer_fence
        )
        store.install_schema()
        pipeline._account_order_admission = store
        # Exact object identity: another request cannot inherit this test
        # candidate; no caller metadata or runtime flags supply authority.
        pipeline._trusted_entry_candidate_provider = (
            lambda observed: candidate if observed is request else None
        )
        self._offline_ack_ledger = ledger

    def _assert_durable_entry_consumed(self):
        import sqlite3
        with sqlite3.connect(self._offline_ack_ledger) as conn:
            rows = conn.execute(
                "SELECT state FROM account_entry_reservations"
            ).fetchall()
        # Timeout and reconciliation never silently release a reservation.
        self.assertEqual(rows, [("submitting",)])

    def test_dispatch_returns_failure_on_timeout(self):
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest

        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        self._install_offline_admission(pipeline)
        pipeline._ack_timeout_s = 0.05   # very short for test

        def _slow_router_factory():
            mock_router = MagicMock()
            mock_router.execute.side_effect = lambda _: (time.sleep(2), None)[1]  # hangs
            return mock_router

        pipeline._multi_router = None
        pipeline._router = _slow_router_factory()

        request = PipelineRequest(
            symbol="ETH-USD",
            side="buy",
            size_usd=200.0,
            validated=True,
        )

        # _dispatch should return a failure PipelineResult rather than hanging
        self._install_offline_entry_admission(pipeline, request)
        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=MagicMock(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())
        self._assert_durable_entry_consumed()
        self.assertFalse(result.success)
        self.assertIn("confirmed_order_rejected", result.error.lower())

    def test_dispatch_timeout_reconciles_to_confirmed_fill(self):
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest

        class _SlowRouter:
            def route(self, _request):
                time.sleep(2)

        class _ReconBroker:
            def get_order_status(self, _order_id):
                return {
                    "status": "filled",
                    "filled_price": 2100.0,
                    "filled_size_usd": 200.0,
                }

        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        self._install_offline_admission(pipeline)
        pipeline._ack_timeout_s = 0.05
        pipeline._multi_router = _SlowRouter()
        pipeline._router = None

        request = PipelineRequest(
            symbol="ETH-USD",
            side="buy",
            size_usd=200.0,
            preferred_broker="kraken",
            request_id="ord-timeout-fill",
            validated=True,
            metadata={"broker_client": _ReconBroker()},
        )

        self._install_offline_entry_admission(pipeline, request)
        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=MagicMock(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())
        self._assert_durable_entry_consumed()
        self.assertTrue(result.success)
        self.assertEqual(result.fill_price, 2100.0)
        self.assertEqual(result.filled_size_usd, 200.0)

    def test_dispatch_timeout_final_status_without_fill_notional_stays_fail_closed(self):
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest

        class _SlowRouter:
            def route(self, _request):
                time.sleep(2)

        class _ReconBroker:
            def get_order_status(self, _order_id):
                return {
                    "status": "filled",
                    "filled_price": 2100.0,
                    # Deliberately no filled quantity/notional. The requested
                    # $200 must never be promoted to execution evidence.
                }

        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        self._install_offline_admission(pipeline)
        pipeline._ack_timeout_s = 0.05
        pipeline._multi_router = _SlowRouter()
        pipeline._router = None

        request = PipelineRequest(
            symbol="ETH-USD",
            side="buy",
            size_usd=200.0,
            preferred_broker="kraken",
            request_id="ord-timeout-no-fill-size",
            validated=True,
            metadata={"broker_client": _ReconBroker()},
        )

        self._install_offline_entry_admission(pipeline, request)
        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=MagicMock(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())
        self._assert_durable_entry_consumed()

        self.assertFalse(result.success)
        self.assertEqual(result.filled_size_usd, 0.0)
        self.assertIn("ack_timeout_no_confirmed_fill", result.error.lower())

    def test_dispatch_timeout_can_compute_notional_from_explicit_fill_quantity(self):
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest

        class _SlowRouter:
            def route(self, _request):
                time.sleep(2)

        class _ReconBroker:
            def get_order_status(self, _order_id):
                return {
                    "status": "closed",
                    "filled_price": 2000.0,
                    "filled_volume": 0.1,
                }

        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        self._install_offline_admission(pipeline)
        pipeline._ack_timeout_s = 0.05
        pipeline._multi_router = _SlowRouter()
        pipeline._router = None

        request = PipelineRequest(
            symbol="ETH-USD",
            side="buy",
            size_usd=250.0,
            preferred_broker="kraken",
            request_id="ord-timeout-fill-qty",
            validated=True,
            metadata={"broker_client": _ReconBroker()},
        )

        self._install_offline_entry_admission(pipeline, request)
        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=MagicMock(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())
        self._assert_durable_entry_consumed()

        self.assertTrue(result.success)
        self.assertEqual(result.fill_price, 2000.0)
        self.assertEqual(result.filled_size_usd, 200.0)

    def test_dispatch_timeout_reconciles_to_confirmed_reject(self):
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest

        class _SlowRouter:
            def route(self, _request):
                time.sleep(2)

        class _ReconBroker:
            def get_order_status(self, _order_id):
                return {"status": "rejected"}

        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        self._install_offline_admission(pipeline)
        pipeline._ack_timeout_s = 0.05
        pipeline._multi_router = _SlowRouter()
        pipeline._router = None

        request = PipelineRequest(
            symbol="ETH-USD",
            side="buy",
            size_usd=200.0,
            preferred_broker="kraken",
            request_id="ord-timeout-reject",
            validated=True,
            metadata={"broker_client": _ReconBroker()},
        )

        self._install_offline_entry_admission(pipeline, request)
        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=MagicMock(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())
        self._assert_durable_entry_consumed()
        self.assertFalse(result.success)
        self.assertIn("confirmed_order_rejected:rejected", result.error.lower())


    def test_missing_offline_admission_still_denies_entry_before_router(self):
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest

        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        pipeline._ack_timeout_s = 0.05
        pipeline._multi_router = None
        mock_router = MagicMock()
        pipeline._router = mock_router
        request = PipelineRequest(
            symbol="ETH-USD", side="buy", size_usd=200.0, validated=True,
        )
        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=MagicMock(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())
        self.assertFalse(result.success)
        self.assertIn("authenticated_reservation_unavailable", result.error)
        mock_router.execute.assert_not_called()

    def test_dispatch_blocks_when_dispatch_enabled_false(self):
        from bot.execution_pipeline import ExecutionPipeline, PipelineRequest

        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._ecel_required = False
        self._install_offline_admission(pipeline)
        pipeline._ack_timeout_s = 0.05
        pipeline._multi_router = None
        pipeline._router = None

        request = PipelineRequest(
            symbol="ETH-USD",
            side="buy",
            size_usd=200.0,
            validated=True,
        )

        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=MagicMock(dispatch_enabled=False, lifecycle_phase="WARM"),
        ):
            result = pipeline._dispatch(request, time.monotonic())

        pipeline._account_order_admission.reserve.assert_not_called()
        pipeline._account_order_admission.consume.assert_not_called()
        self.assertFalse(result.success)
        self.assertIn("dispatch_disabled", result.error)


# ---------------------------------------------------------------------------
# 15. New exception types are importable
# ---------------------------------------------------------------------------

class TestNewExceptionTypes(unittest.TestCase):
    def test_broker_auth_error_is_execution_error(self):
        from bot.exceptions import BrokerAuthError, ExecutionError
        self.assertTrue(issubclass(BrokerAuthError, ExecutionError))

    def test_ack_timeout_error_is_execution_error(self):
        from bot.exceptions import ACKTimeoutError, ExecutionError
        self.assertTrue(issubclass(ACKTimeoutError, ExecutionError))

    def test_post_only_reject_error_is_execution_error(self):
        from bot.exceptions import PostOnlyRejectError, ExecutionError
        self.assertTrue(issubclass(PostOnlyRejectError, ExecutionError))

    def test_slippage_guard_error_is_execution_error(self):
        from bot.exceptions import SlippageGuardError, ExecutionError
        self.assertTrue(issubclass(SlippageGuardError, ExecutionError))

    def test_risk_governor_blocked_error_is_execution_error(self):
        from bot.exceptions import RiskGovernorBlockedError, ExecutionError
        self.assertTrue(issubclass(RiskGovernorBlockedError, ExecutionError))

    def test_reconciliation_gate_error_is_execution_error(self):
        from bot.exceptions import ReconciliationGateError, ExecutionError
        self.assertTrue(issubclass(ReconciliationGateError, ExecutionError))


if __name__ == "__main__":
    unittest.main()
