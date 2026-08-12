from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

from bot import final_production_activation_repair_v58_patch as repair


class _FakeReadiness(types.ModuleType):
    def __init__(self):
        super().__init__("bot.readiness_table")
        self.table = {key: False for key in repair._READINESS_KEYS}

    def snapshot(self):
        return dict(self.table)

    def mark_ready(self, key):
        self.table[key] = True


def test_incremental_readiness_publishes_independent_truth(monkeypatch):
    fake = _FakeReadiness()
    monkeypatch.setitem(sys.modules, "bot.readiness_table", fake)
    monkeypatch.setitem(sys.modules, "readiness_table", fake)
    monkeypatch.setattr(repair, "_emit_readiness_diagnostics", lambda proofs: None)

    proofs = {
        "broker_connected": True,
        "balance_hydrated": True,
        "authority_ready": True,
        "capital_ready": True,
        "risk_ready": False,
        "strategy_ready": True,
        "execution_ready": True,
        "nonce_ready": True,
        "bootstrap_ready": False,
    }

    ready, pending = repair._incremental_mark_proven_readiness(proofs)

    assert ready is False
    assert pending == ["risk_ready", "bootstrap_ready"]
    assert fake.table == proofs
    assert os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] == "0"
    assert os.environ["NIJA_AUTHORITY_READY"] == "1"
    assert os.environ["NIJA_NONCE_READY"] == "1"
    assert os.environ["NIJA_RUNTIME_NONCE_READY"] == "1"


def test_incremental_readiness_never_marks_false_proof(monkeypatch):
    fake = _FakeReadiness()
    fake.table["broker_connected"] = True
    monkeypatch.setitem(sys.modules, "bot.readiness_table", fake)
    monkeypatch.setitem(sys.modules, "readiness_table", fake)
    monkeypatch.setattr(repair, "_emit_readiness_diagnostics", lambda proofs: None)

    proofs = {key: False for key in repair._READINESS_KEYS}
    proofs["strategy_ready"] = True

    ready, pending = repair._incremental_mark_proven_readiness(proofs)

    assert ready is False
    assert fake.table["broker_connected"] is True  # monotonic pre-existing truth
    assert fake.table["strategy_ready"] is True
    assert fake.table["risk_ready"] is False
    assert "risk_ready" in pending


def test_canonical_core_registered_requires_current_writer_and_exact_live_core(monkeypatch):
    core = MagicMock()
    core.is_alive.return_value = True
    runtime = types.SimpleNamespace(acquired=True, lost=False, _core_thread=core)
    bot_main = types.SimpleNamespace(_writer_authority_runtime=runtime)

    assert repair._canonical_core_registered(bot_main) is True

    runtime.lost = True
    assert repair._canonical_core_registered(bot_main) is False

    runtime.lost = False
    core.is_alive.return_value = False
    assert repair._canonical_core_registered(bot_main) is False


def test_terminal_classifier_accepts_exact_production_core_dead_reason(monkeypatch):
    import bot.terminal_writer_loss_latch as latch

    original_keywords = latch._TERMINAL_REASON_KEYWORDS
    original_classifier = latch._is_terminal_proof
    try:
        assert repair._patch_terminal_writer_loss() is True
        reason = (
            "writer_lock_released_for_reelection:core_thread_dead "
            "name=TradingLoop ident=129727785187008"
        )
        assert latch._is_terminal_proof(reason) is True
        assert latch._is_terminal_proof("redis_timeout_on_probe") is False
        assert latch._is_terminal_proof("exchange_error") is False
    finally:
        latch._TERMINAL_REASON_KEYWORDS = original_keywords
        latch._is_terminal_proof = original_classifier


def test_canonical_fast_path_is_diagnostic_only_contract(monkeypatch):
    monkeypatch.setenv("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH", "1")
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    assert repair._canonical_fast_path() is True


def test_strict_live_proofs_rejects_dead_core_before_any_dispatch(monkeypatch):
    core = MagicMock()
    core.is_alive.return_value = False
    runtime = types.SimpleNamespace(acquired=True, lost=False)

    allowed, blockers = repair._strict_live_proofs(runtime, core)

    assert allowed is False
    assert "core_thread_alive" in blockers


def test_installer_declared_on_canonical_fast_path():
    source = open(os.path.join(os.path.dirname(__file__), "..", "bot.py"), encoding="utf-8").read()
    assert "bot.final_production_activation_repair_v58_patch" in source
    assert "FINAL_PRODUCTION_ACTIVATION_V58" in source


def test_repair_does_not_change_trade_thresholds():
    source = open(
        os.path.join(os.path.dirname(__file__), "..", "final_production_activation_repair_v58_patch.py"),
        encoding="utf-8",
    ).read()
    forbidden_assignments = (
        "MIN_ENTRY_SCORE =",
        "MIN_TRADE_USD =",
        "FORCE_TRADE =",
        "NIJA_FORCE_ACTIVATION =",
    )
    for assignment in forbidden_assignments:
        assert assignment not in source
