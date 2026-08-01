from __future__ import annotations

import sys
import types

import bot.capital_authority as capital_authority_module
from bot.broker_manager import AccountType, BaseBroker, BrokerType
from bot.capital_authority import (
    get_capital_authority,
    reset_capital_authority_singleton,
)
from bot.capital_csm_v2 import get_csm_v2, reset_csm_v2_singleton
from bot.multi_account_broker_manager import (
    MultiAccountBrokerManager,
    get_broker_manager,
    reset_broker_manager_singleton,
)


class _ReadyBroker(BaseBroker):
    def __init__(self) -> None:
        super().__init__(BrokerType.COINBASE, AccountType.PLATFORM)
        self.connected = True
        self._last_known_balance = 100.0

    def connect(self):
        self.connected = True
        return True

    def get_account_balance(self):
        return 100.0

    def has_balance_payload_for_capital(self):
        return True

    def is_ready_for_capital(self):
        return True

    def get_positions(self):
        return []

    def get_available_markets(self):
        return ["BTC-USD"]

    def place_market_order(self, symbol, side, quantity, **kwargs):
        return {
            "status": "filled",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
        }


def test_seed_handoff_hydrates_csm_even_without_capital_fsm(monkeypatch):
    snapshot = types.SimpleNamespace(real_capital=371.07, broker_count=2)
    calls = []
    csm = types.SimpleNamespace(is_hydrated=False)

    def ingest(received):
        calls.append(received)
        csm.is_hydrated = True
        return types.SimpleNamespace(value="READY")

    csm.ingest_snapshot = ingest
    module = types.SimpleNamespace(get_csm_v2=lambda: csm)
    monkeypatch.setitem(sys.modules, "bot.capital_csm_v2", module)

    manager = object.__new__(MultiAccountBrokerManager)

    assert manager._ingest_canonical_csm_snapshot(snapshot, "unit_test") is True
    assert calls == [snapshot]


def test_seed_handoff_fails_closed_when_csm_rejects_snapshot(monkeypatch):
    snapshot = types.SimpleNamespace(real_capital=371.07, broker_count=2)

    def reject(_received):
        raise RuntimeError("snapshot rejected")

    csm = types.SimpleNamespace(is_hydrated=False, ingest_snapshot=reject)
    module = types.SimpleNamespace(get_csm_v2=lambda: csm)
    monkeypatch.setitem(sys.modules, "bot.capital_csm_v2", module)

    manager = object.__new__(MultiAccountBrokerManager)

    assert manager._ingest_canonical_csm_snapshot(snapshot, "unit_test") is False


def test_real_bootstrap_seed_path_hydrates_authority_and_csm(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("NIJA_LOCK_ACQUIRED", "true")
    monkeypatch.setattr(capital_authority_module, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(
        capital_authority_module,
        "_STATE_FILE",
        tmp_path / "capital_authority_state.json",
    )

    reset_capital_authority_singleton(clear_disk_cache=True)
    reset_csm_v2_singleton()
    reset_broker_manager_singleton()
    try:
        manager = get_broker_manager()
        manager.register_platform_broker_instance(
            BrokerType.COINBASE,
            _ReadyBroker(),
            mark_connected_state=False,
        )

        result = manager.refresh_capital_authority(
            trigger="platform_connect:coinbase:attempt_1"
        )
        authority = get_capital_authority()
        csm = get_csm_v2()

        assert result["ready"] == 1.0
        assert authority.is_hydrated is True
        assert authority.first_snap_accepted is True
        assert csm.is_hydrated is True
        assert csm.first_snap_accepted is True
        assert csm.state.value == "READY"
    finally:
        reset_broker_manager_singleton()
        reset_csm_v2_singleton()
        reset_capital_authority_singleton(clear_disk_cache=True)


def test_seed_path_does_not_advance_when_csm_handoff_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("NIJA_LOCK_ACQUIRED", "true")
    monkeypatch.setattr(capital_authority_module, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(
        capital_authority_module,
        "_STATE_FILE",
        tmp_path / "capital_authority_state.json",
    )

    reset_capital_authority_singleton(clear_disk_cache=True)
    reset_csm_v2_singleton()
    reset_broker_manager_singleton()
    try:
        manager = get_broker_manager()
        manager.register_platform_broker_instance(
            BrokerType.COINBASE,
            _ReadyBroker(),
            mark_connected_state=False,
        )
        manager._capital_bootstrap_fsm = types.SimpleNamespace(state="TEST_READY")
        advance_calls = []
        monkeypatch.setattr(
            manager,
            "_ingest_canonical_csm_snapshot",
            lambda snapshot, source: False,
        )
        monkeypatch.setattr(
            manager,
            "_advance_seed_capital_bootstrap_ready",
            lambda: advance_calls.append(True) or True,
        )

        manager.refresh_capital_authority(
            trigger="platform_connect:coinbase:attempt_1"
        )

        assert get_capital_authority().first_snap_accepted is True
        assert advance_calls == []
    finally:
        reset_broker_manager_singleton()
        reset_csm_v2_singleton()
        reset_capital_authority_singleton(clear_disk_cache=True)
