from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bot import operator_emergency_stop_clear_patch as recovery


class _TradingState:
    EMERGENCY_STOP = "EMERGENCY_STOP"
    OFF = "OFF"


class _FakeStateMachine:
    def __init__(self, reason: str) -> None:
        import threading
        self._lock = threading.Lock()
        self._current_state = _TradingState.EMERGENCY_STOP
        self._state_history = [
            {"from": "LIVE_ACTIVE", "to": "EMERGENCY_STOP", "reason": reason}
        ]
        self.transitions: list[tuple[object, str]] = []

    def transition_to(self, state, reason: str = "") -> bool:
        self.transitions.append((state, reason))
        self._current_state = state
        return True


class AuthorityHeartbeatStopRecoveryV90Tests(unittest.TestCase):
    def test_heartbeat_origin_stop_recovers_only_to_off(self) -> None:
        sm = _FakeStateMachine("AUTHORITY_HEARTBEAT_EXPIRED: transient redis timeout")
        fake_tsm = SimpleNamespace(
            get_state_machine=lambda: sm,
            TradingState=_TradingState,
        )
        with patch.dict("sys.modules", {"bot.trading_state_machine": fake_tsm}), patch.object(
            recovery, "_kill_switch_explicitly_clear", return_value=(True, "kill_switch_clear")
        ), patch.object(
            recovery, "_exact_writer_recovery_proof", return_value=(True, "exact_writer_renewal_proof")
        ):
            self.assertTrue(recovery._recover_authority_heartbeat_stop())
        self.assertEqual(sm._current_state, _TradingState.OFF)
        self.assertEqual(len(sm.transitions), 1)
        self.assertEqual(sm.transitions[0][0], _TradingState.OFF)

    def test_manual_emergency_stop_is_never_auto_cleared(self) -> None:
        sm = _FakeStateMachine("manual operator emergency stop")
        fake_tsm = SimpleNamespace(
            get_state_machine=lambda: sm,
            TradingState=_TradingState,
        )
        with patch.dict("sys.modules", {"bot.trading_state_machine": fake_tsm}), patch.object(
            recovery, "_kill_switch_explicitly_clear", return_value=(True, "kill_switch_clear")
        ), patch.object(
            recovery, "_exact_writer_recovery_proof", return_value=(True, "exact_writer_renewal_proof")
        ):
            self.assertFalse(recovery._recover_authority_heartbeat_stop())
        self.assertEqual(sm._current_state, _TradingState.EMERGENCY_STOP)
        self.assertEqual(sm.transitions, [])

    def test_kill_switch_active_blocks_recovery(self) -> None:
        sm = _FakeStateMachine("AUTHORITY_HEARTBEAT_EXPIRED: timeout")
        fake_tsm = SimpleNamespace(get_state_machine=lambda: sm, TradingState=_TradingState)
        with patch.dict("sys.modules", {"bot.trading_state_machine": fake_tsm}), patch.object(
            recovery, "_kill_switch_explicitly_clear", return_value=(False, "kill_switch_active")
        ), patch.object(
            recovery, "_exact_writer_recovery_proof", return_value=(True, "exact_writer_renewal_proof")
        ):
            self.assertFalse(recovery._recover_authority_heartbeat_stop())
        self.assertEqual(sm.transitions, [])

    def test_missing_exact_writer_proof_blocks_recovery(self) -> None:
        sm = _FakeStateMachine("AUTHORITY_HEARTBEAT_EXPIRED: timeout")
        fake_tsm = SimpleNamespace(get_state_machine=lambda: sm, TradingState=_TradingState)
        with patch.dict("sys.modules", {"bot.trading_state_machine": fake_tsm}), patch.object(
            recovery, "_kill_switch_explicitly_clear", return_value=(True, "kill_switch_clear")
        ), patch.object(
            recovery, "_exact_writer_recovery_proof", return_value=(False, "writer_renewal_unhealthy")
        ):
            self.assertFalse(recovery._recover_authority_heartbeat_stop())
        self.assertEqual(sm.transitions, [])

    def test_tick_wrapper_only_attempts_recovery_after_healthy_tick(self) -> None:
        calls: list[str] = []

        class Monitor:
            def __init__(self) -> None:
                self._locked_down = False
                self._consecutive_failures = 0

            def _tick(self):
                os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"

        module = SimpleNamespace(AuthorityHeartbeatMonitor=Monitor, __name__="bot.authority_heartbeat")
        self.assertTrue(recovery._patch_authority_heartbeat_module(module))
        with patch.object(recovery, "_recover_authority_heartbeat_stop", side_effect=lambda: calls.append("recover") or False):
            Monitor()._tick()
        self.assertEqual(calls, ["recover"])


if __name__ == "__main__":
    unittest.main()
