from __future__ import annotations

import importlib
import threading
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

from bot import runtime_capital_direct_refresh_downgrade_v180_patch as patch


def _authority(*, balances: dict[str, float], expected: int = 3, registered: bool = True):
    gate = threading.Event()
    if registered:
        gate.set()
    return SimpleNamespace(
        _broker_balances=dict(balances),
        _expected_brokers=expected,
        _broker_registration_complete=gate,
        _lock=threading.RLock(),
        last_updated=datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc),
    )


def test_complete_post_bootstrap_state_suppresses_private_partial_fallback() -> None:
    authority = _authority(
        balances={"kraken": 154.49, "coinbase": 95.12, "okx": 0.0}
    )

    suppress, details = patch._should_suppress_direct_fallback(
        authority,
        {"coinbase": object(), "okx": object()},
        bypass_startup_lock=True,
    )

    assert suppress is True
    assert details["expected"] == 3
    assert details["existing_complete"] is True
    assert details["incoming_complete"] is False
    assert details["missing"] == ["kraken"]


def test_complete_post_bootstrap_state_also_suppresses_complete_private_fallback() -> None:
    authority = _authority(
        balances={"kraken": 154.49, "coinbase": 95.12, "okx": 0.0}
    )

    suppress, details = patch._should_suppress_direct_fallback(
        authority,
        {"kraken": object(), "coinbase": object(), "okx": object()},
        bypass_startup_lock=True,
    )

    assert suppress is True
    assert details["existing_complete"] is True
    assert details["incoming_complete"] is True
    assert details["missing"] == []


def test_registered_incomplete_authority_rejects_private_partial_bootstrap_fallback() -> None:
    authority = _authority(balances={"coinbase": 95.12})

    suppress, details = patch._should_suppress_direct_fallback(
        authority,
        {"coinbase": object(), "okx": object()},
        bypass_startup_lock=True,
    )

    assert suppress is True
    assert details["existing_complete"] is False
    assert details["incoming_complete"] is False


def test_registered_incomplete_authority_allows_complete_private_bootstrap_fallback() -> None:
    authority = _authority(balances={"coinbase": 95.12})

    suppress, details = patch._should_suppress_direct_fallback(
        authority,
        {"kraken": object(), "coinbase": object(), "okx": object()},
        bypass_startup_lock=True,
    )

    assert suppress is False
    assert details["existing_complete"] is False
    assert details["incoming_complete"] is True


def test_non_bypass_refresh_is_outside_v180_scope() -> None:
    authority = _authority(balances={"coinbase": 95.12})

    suppress, _ = patch._should_suppress_direct_fallback(
        authority,
        {"coinbase": object(), "okx": object()},
        bypass_startup_lock=False,
    )

    assert suppress is False


def test_registration_incomplete_keeps_bootstrap_fallback_available() -> None:
    authority = _authority(balances={"coinbase": 95.12}, registered=False)

    suppress, _ = patch._should_suppress_direct_fallback(
        authority,
        {"coinbase": object(), "okx": object()},
        bypass_startup_lock=True,
    )

    assert suppress is False


def test_actual_wrapper_does_not_call_base_for_registered_partial_input(monkeypatch) -> None:
    calls = []

    class CapitalAuthority:
        def __init__(self) -> None:
            self._broker_balances = {"coinbase": 95.12}
            self._expected_brokers = 3
            self._broker_registration_complete = threading.Event()
            self._broker_registration_complete.set()
            self._lock = threading.RLock()
            self.last_updated = datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc)

        def refresh(self, broker_map, open_exposure_usd=0.0, _bypass_startup_lock=False):
            calls.append((broker_map, open_exposure_usd, _bypass_startup_lock))
            self._broker_balances = {key: 1.0 for key in broker_map}

    fake = ModuleType("bot.capital_authority")
    fake.CapitalAuthority = CapitalAuthority
    real_import = importlib.import_module
    monkeypatch.setattr(
        patch.importlib,
        "import_module",
        lambda name: fake if name == "bot.capital_authority" else real_import(name),
    )

    assert patch._patch_capital_authority() is True
    authority = CapitalAuthority()
    before = dict(authority._broker_balances)
    before_updated = authority.last_updated

    result = authority.refresh(
        {"coinbase": object(), "okx": object()},
        _bypass_startup_lock=True,
    )

    assert result is None
    assert calls == []
    assert authority._broker_balances == before
    assert authority.last_updated == before_updated


def test_actual_wrapper_allows_complete_first_bootstrap_input(monkeypatch) -> None:
    calls = []

    class CapitalAuthority:
        def __init__(self) -> None:
            self._broker_balances = {"coinbase": 95.12}
            self._expected_brokers = 3
            self._broker_registration_complete = threading.Event()
            self._broker_registration_complete.set()
            self._lock = threading.RLock()
            self.last_updated = datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc)

        def refresh(self, broker_map, open_exposure_usd=0.0, _bypass_startup_lock=False):
            calls.append((tuple(sorted(broker_map)), open_exposure_usd, _bypass_startup_lock))
            self._broker_balances = {key: 1.0 for key in broker_map}
            return "base-called"

    fake = ModuleType("bot.capital_authority")
    fake.CapitalAuthority = CapitalAuthority
    real_import = importlib.import_module
    monkeypatch.setattr(
        patch.importlib,
        "import_module",
        lambda name: fake if name == "bot.capital_authority" else real_import(name),
    )

    assert patch._patch_capital_authority() is True
    authority = CapitalAuthority()
    result = authority.refresh(
        {"kraken": object(), "coinbase": object(), "okx": object()},
        _bypass_startup_lock=True,
    )

    assert result == "base-called"
    assert calls == [(("coinbase", "kraken", "okx"), 0.0, True)]
    assert set(authority._broker_balances) == {"kraken", "coinbase", "okx"}


def test_v180_exposes_no_freshness_or_execution_bypass_api() -> None:
    for forbidden in (
        "extend_freshness",
        "accept_partial_snapshot",
        "force_activation",
        "grant_execution_authority",
        "clear_kill_switch",
    ):
        assert not hasattr(patch, forbidden)
