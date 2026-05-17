"""
Tests for ExecutionStateController FSM transitions.

Covers every taxonomy-driven edge in the state graph:
- NONCE  → RETRYING → SUBMITTING → COMPLETED
- NONCE exhausted → FAILED
- RATE_LIMIT → BACKING_OFF → SUBMITTING → COMPLETED
- RATE_LIMIT exhausted → FAILED
- AUTH → HALTED_AUTH  (authority FSM reset + gate-fail callback invoked)
- PERMISSION → HALTED_CONFIG (gate-fail callback invoked)
- FUNDS → HALTED_FUNDS
- unknown/unrecognised error → FAILED
- happy-path success → COMPLETED
- broker raises exception → classified via taxonomy
- ExecutionResult fields (status, retry_policy, order_id)
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from bot.execution_state_controller import ExecutionOrderState, ExecutionStateController
from bot.execution_result import ExecutionResult, OrderStatus
from bot.kraken_error_taxonomy import (
    KrakenErrorCategory,
    KrakenRetryPolicy,
    classify_kraken_error,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_sleep(seconds: float) -> None:
    """Drop-in for time.sleep that does nothing — keeps tests fast."""


def _make_controller(**kwargs) -> ExecutionStateController:
    """Return a controller with no-op sleep injected."""
    kwargs.setdefault("sleep_fn", _no_sleep)
    return ExecutionStateController(**kwargs)


def _kraken_error_response(error_text: str) -> dict:
    """Kraken-style error response dict."""
    return {"error": [error_text]}


def _order_accepted_response(order_id: str = "ORD-001") -> dict:
    """Broker response for a successful order placement."""
    return {"status": "pending", "order_id": order_id}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):
    """Successful submission → COMPLETED."""

    def test_completed_on_first_attempt(self):
        broker_fn = MagicMock(return_value=_order_accepted_response("ORD-42"))
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.COMPLETED)
        self.assertEqual(broker_fn.call_count, 1)
        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(result.status, OrderStatus.ACCEPTED)
        self.assertEqual(result.exchange_order_id, "ORD-42")
        self.assertIsNone(result.retry_policy)

    def test_success_fn_override(self):
        """Custom success_fn that checks for Kraken 'result' key."""
        response = {"result": {"XXBTZUSD": "100.0"}}
        broker_fn = MagicMock(return_value=response)
        ctrl = _make_controller()
        result = ctrl.submit(
            "BTC-USD", "query", 0.0, broker_fn,
            success_fn=lambda r: bool(r and "result" in r),
        )
        self.assertEqual(ctrl.state, ExecutionOrderState.COMPLETED)
        self.assertEqual(result.status, OrderStatus.ACCEPTED)

    def test_completed_sets_last_broker_response(self):
        resp = _order_accepted_response("ORD-99")
        ctrl = _make_controller()
        ctrl.submit("ETH-USD", "sell", 20.0, MagicMock(return_value=resp))
        self.assertEqual(ctrl.last_broker_response, resp)

    def test_no_taxonomy_on_success(self):
        ctrl = _make_controller()
        ctrl.submit("BTC-USD", "buy", 10.0,
                    MagicMock(return_value=_order_accepted_response()))
        self.assertIsNone(ctrl.last_taxonomy)


# ---------------------------------------------------------------------------
# NONCE → RETRY
# ---------------------------------------------------------------------------


class TestNonceRetry(unittest.TestCase):
    """NONCE error drives RETRYING → SUBMITTING loop until success or exhaustion."""

    def test_nonce_then_success(self):
        """First call returns nonce error; second succeeds → COMPLETED."""
        call_count = 0

        def broker_fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _kraken_error_response("EAPI:Invalid nonce")
            return _order_accepted_response("ORD-7")

        ctrl = _make_controller()
        result = ctrl.submit("SOL-USD", "buy", 30.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.COMPLETED)
        self.assertEqual(call_count, 2)
        self.assertEqual(result.status, OrderStatus.ACCEPTED)
        self.assertEqual(result.exchange_order_id, "ORD-7")

    def test_nonce_uses_taxonomy_delay(self):
        """sleep() is called with the taxonomy-specified delay, not a hardcoded one."""
        nonce_taxonomy = classify_kraken_error("EAPI:Invalid nonce")
        expected_delay = nonce_taxonomy.retry_delay_s

        sleep_calls: list[float] = []

        def _tracking_sleep(s: float) -> None:
            sleep_calls.append(s)

        call_count = 0

        def broker_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return _kraken_error_response("EAPI:Invalid nonce")
            return _order_accepted_response()

        ctrl = ExecutionStateController(sleep_fn=_tracking_sleep)
        ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        self.assertGreater(len(sleep_calls), 0)
        for delay in sleep_calls:
            self.assertEqual(delay, expected_delay)

    def test_nonce_exhausted_fails(self):
        """Nonce errors every attempt → FAILED when max_retries exceeded."""
        taxonomy = classify_kraken_error("EAPI:Invalid nonce")
        # One more than max_retries so every attempt returns nonce error.
        total_calls = taxonomy.max_retries + 1

        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAPI:Invalid nonce")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.FAILED)
        self.assertEqual(broker_fn.call_count, total_calls)
        self.assertEqual(result.status, OrderStatus.FAILED)

    def test_nonce_retry_policy_on_result(self):
        """ExecutionResult carries RETRY policy when nonce errors exhaust retries."""
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAPI:Invalid nonce")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        self.assertEqual(result.retry_policy, KrakenRetryPolicy.RETRY)


# ---------------------------------------------------------------------------
# RATE_LIMIT → BACKING_OFF
# ---------------------------------------------------------------------------


class TestRateLimitBackoff(unittest.TestCase):
    """RATE_LIMIT error drives exponential BACKING_OFF → SUBMITTING loop."""

    def test_rate_limit_then_success(self):
        call_count = 0

        def broker_fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _kraken_error_response("EAPI:Rate limit exceeded")
            return _order_accepted_response("ORD-RL")

        ctrl = _make_controller()
        result = ctrl.submit("ETH-USD", "sell", 100.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.COMPLETED)
        self.assertEqual(call_count, 2)
        self.assertEqual(result.status, OrderStatus.ACCEPTED)

    def test_rate_limit_exponential_backoff(self):
        """Each successive back-off uses a longer delay (multiplier * base)."""
        delays: list[float] = []

        def _tracking_sleep(s: float) -> None:
            delays.append(s)

        taxonomy = classify_kraken_error("EAPI:Rate limit exceeded")
        base_delay = taxonomy.retry_delay_s
        max_backoffs = taxonomy.max_retries

        # Return rate-limit every time to exhaust retries.
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAPI:Rate limit exceeded")
        )
        ctrl = ExecutionStateController(
            sleep_fn=_tracking_sleep,
            backoff_multiplier=2.0,
        )
        ctrl.submit("BTC-USD", "sell", 10.0, broker_fn)

        self.assertEqual(len(delays), max_backoffs)
        # Each delay should be >= the previous (exponential or equal).
        for i in range(1, len(delays)):
            self.assertGreaterEqual(delays[i], delays[i - 1])

    def test_rate_limit_exhausted_fails(self):
        taxonomy = classify_kraken_error("EAPI:Rate limit exceeded")
        total_calls = taxonomy.max_retries + 1

        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAPI:Rate limit exceeded")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.FAILED)
        self.assertEqual(broker_fn.call_count, total_calls)
        self.assertEqual(result.status, OrderStatus.FAILED)

    def test_rate_limit_retry_policy_on_result(self):
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAPI:Rate limit exceeded")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        self.assertEqual(result.retry_policy, KrakenRetryPolicy.BACKOFF)


# ---------------------------------------------------------------------------
# AUTH → HALTED_AUTH
# ---------------------------------------------------------------------------


class TestAuthHalt(unittest.TestCase):
    """AUTH errors transition to HALTED_AUTH with no retries."""

    def test_auth_halts_immediately(self):
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAuth:Invalid key")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.HALTED_AUTH)
        self.assertEqual(broker_fn.call_count, 1, "no retries on AUTH failure")
        self.assertEqual(result.status, OrderStatus.FAILED)
        self.assertEqual(result.retry_policy, KrakenRetryPolicy.STOP)

    def test_auth_invokes_gate_fail_callback(self):
        """gate_fail_callback is called exactly once with the taxonomy."""
        callback = MagicMock()
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAuth:Invalid signature")
        )
        ctrl = _make_controller(gate_fail_callback=callback)
        ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        callback.assert_called_once()
        taxonomy_arg = callback.call_args[0][0]
        self.assertEqual(taxonomy_arg.category, KrakenErrorCategory.AUTH)
        self.assertEqual(taxonomy_arg.policy, KrakenRetryPolicy.STOP)

    def test_auth_resets_authority_fsm(self):
        """authority_fsm.reset() is called when HALTED_AUTH is entered."""
        mock_fsm = MagicMock()
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAuth:Invalid key")
        )
        ctrl = _make_controller(authority_fsm=mock_fsm)
        ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        mock_fsm.reset.assert_called_once()

    def test_auth_does_not_retry(self):
        """Auth errors must never be retried regardless of retry_count."""
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAuth:Locked")
        )
        ctrl = _make_controller()
        ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        self.assertEqual(broker_fn.call_count, 1)

    def test_auth_via_exception(self):
        """Auth errors raised as exceptions are also classified and halt."""
        broker_fn = MagicMock(
            side_effect=Exception("EAuth:Invalid key — connection refused")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.HALTED_AUTH)
        self.assertEqual(result.status, OrderStatus.FAILED)


# ---------------------------------------------------------------------------
# PERMISSION → HALTED_CONFIG
# ---------------------------------------------------------------------------


class TestPermissionHalt(unittest.TestCase):
    """PERMISSION errors transition to HALTED_CONFIG with no retries."""

    def test_permission_halts_immediately(self):
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EGeneral:Permission denied")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.HALTED_CONFIG)
        self.assertEqual(broker_fn.call_count, 1)
        self.assertEqual(result.retry_policy, KrakenRetryPolicy.CONFIG_FAIL)

    def test_permission_invokes_gate_fail_callback(self):
        callback = MagicMock()
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EGeneral:Permission denied")
        )
        ctrl = _make_controller(gate_fail_callback=callback)
        ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        callback.assert_called_once()
        taxonomy_arg = callback.call_args[0][0]
        self.assertEqual(taxonomy_arg.category, KrakenErrorCategory.PERMISSION)

    def test_permission_resets_authority_fsm(self):
        mock_fsm = MagicMock()
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAPI:Invalid permission")
        )
        ctrl = _make_controller(authority_fsm=mock_fsm)
        ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        mock_fsm.reset.assert_called_once()

    def test_feature_disabled_halts_config(self):
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAPI:Feature disabled")
        )
        ctrl = _make_controller()
        ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.HALTED_CONFIG)


# ---------------------------------------------------------------------------
# FUNDS → HALTED_FUNDS
# ---------------------------------------------------------------------------


class TestFundsHalt(unittest.TestCase):
    """Insufficient-funds errors transition to HALTED_FUNDS."""

    def test_funds_halts_immediately(self):
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EOrder:Insufficient funds")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.HALTED_FUNDS)
        self.assertEqual(broker_fn.call_count, 1)
        self.assertEqual(result.status, OrderStatus.FAILED)

    def test_funds_does_not_call_gate_fail_callback(self):
        """gate_fail_callback is NOT called for HALTED_FUNDS (non-auth failure)."""
        callback = MagicMock()
        broker_fn = MagicMock(
            return_value=_kraken_error_response("EOrder:Insufficient funds")
        )
        ctrl = _make_controller(gate_fail_callback=callback)
        ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        callback.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown error → FAILED
# ---------------------------------------------------------------------------


class TestUnknownError(unittest.TestCase):
    """Unrecognised errors transition directly to FAILED."""

    def test_unknown_error_fails(self):
        broker_fn = MagicMock(
            return_value=_kraken_error_response("some completely unrecognised xyz error")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.FAILED)
        self.assertEqual(result.status, OrderStatus.FAILED)
        self.assertEqual(broker_fn.call_count, 1)

    def test_none_response_fails(self):
        broker_fn = MagicMock(return_value=None)
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.FAILED)
        self.assertEqual(result.status, OrderStatus.FAILED)

    def test_exception_unknown_error_fails(self):
        broker_fn = MagicMock(
            side_effect=Exception("completely unknown exchange error xyz")
        )
        ctrl = _make_controller()
        result = ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.FAILED)
        self.assertEqual(result.status, OrderStatus.FAILED)
        # Exception text should be surfaced in error_code
        self.assertIsNotNone(result.error_code)

    def test_unknown_does_not_invoke_callback(self):
        callback = MagicMock()
        broker_fn = MagicMock(return_value=None)
        ctrl = _make_controller(gate_fail_callback=callback)
        ctrl.submit("BTC-USD", "buy", 10.0, broker_fn)

        callback.assert_not_called()


# ---------------------------------------------------------------------------
# ExecutionResult contract
# ---------------------------------------------------------------------------


class TestExecutionResultContract(unittest.TestCase):
    """Verify ExecutionResult fields are populated correctly in all branches."""

    def test_accepted_result_has_order_id(self):
        ctrl = _make_controller()
        ctrl.submit(
            "BTC-USD", "buy", 10.0,
            MagicMock(return_value=_order_accepted_response("ORD-XYZ")),
        )
        result = ctrl._build_execution_result("BTC-USD", "buy", 0.0)
        self.assertEqual(result.exchange_order_id, "ORD-XYZ")

    def test_failed_result_has_no_order_id(self):
        ctrl = _make_controller()
        ctrl.submit(
            "BTC-USD", "buy", 10.0,
            MagicMock(return_value=_kraken_error_response("EAuth:Invalid key")),
        )
        result = ctrl._build_execution_result("BTC-USD", "buy", 0.0)
        self.assertIsNone(result.exchange_order_id)

    def test_latency_ms_positive(self):
        ctrl = _make_controller()
        result = ctrl.submit(
            "BTC-USD", "buy", 10.0,
            MagicMock(return_value=_order_accepted_response()),
        )
        self.assertGreaterEqual(result.latency_ms, 0)


# ---------------------------------------------------------------------------
# Authority FSM integration
# ---------------------------------------------------------------------------


class TestAuthorityFSMIntegration(unittest.TestCase):
    """Verify that the real ExecutionAuthorityConvergenceFSM is reset on AUTH halt."""

    def test_convergence_fsm_reset_on_auth(self):
        from bot.trading_state_machine import ExecutionAuthorityConvergenceFSM, ExecutionProgressState

        fsm = ExecutionAuthorityConvergenceFSM(timeout_s=5.0)
        # Prime the FSM to a non-LOCKED progress state (ARMED).
        fsm.evaluate(
            intent_present=True,
            bootstrap_running_supervised=False,
            capital_running=False,
            trading_live=False,
            activation_committed=False,
            execution_authority=False,
            can_dispatch_trades=False,
            gates_ok=True,
        )
        # Confirm it advanced beyond LOCKED.
        snap_before = fsm.evaluate(
            intent_present=True,
            bootstrap_running_supervised=False,
            capital_running=False,
            trading_live=False,
            activation_committed=False,
            execution_authority=False,
            can_dispatch_trades=False,
            gates_ok=True,
        )
        self.assertEqual(snap_before.progress_state, ExecutionProgressState.ARMED)

        broker_fn = MagicMock(
            return_value=_kraken_error_response("EAuth:Invalid key")
        )
        ctrl = _make_controller(authority_fsm=fsm)
        ctrl.submit("BTC-USD", "buy", 50.0, broker_fn)

        self.assertEqual(ctrl.state, ExecutionOrderState.HALTED_AUTH)
        # After reset(), the FSM is LOCKED — evaluate() with no intent stays LOCKED.
        snap_after = fsm.evaluate(
            intent_present=False,
            bootstrap_running_supervised=True,
            capital_running=True,
            trading_live=True,
            activation_committed=True,
            execution_authority=True,
            can_dispatch_trades=True,
            gates_ok=True,
        )
        self.assertEqual(snap_after.progress_state, ExecutionProgressState.LOCKED)


if __name__ == "__main__":
    unittest.main()
