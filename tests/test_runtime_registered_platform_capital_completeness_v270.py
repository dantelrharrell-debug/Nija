from __future__ import annotations

import os
import threading
from types import SimpleNamespace

from bot import runtime_registered_platform_capital_completeness_v270_patch as v270


class _Broker:
    def __init__(self, connected: bool) -> None:
        self.connected = connected


class _Authority:
    def __init__(self, *, expected: int = 2, accepted: bool = True, stale: bool = False, complete: bool = True) -> None:
        self.expected_brokers = expected
        self._accepted = accepted
        self._stale = stale
        self._complete = complete
        self.set_calls = []

    def set_expected_brokers(self, count: int) -> None:
        self.expected_brokers = max(self.expected_brokers, int(count))
        self.set_calls.append(int(count))

    def get_snapshot_publication_status(self):
        return SimpleNamespace(accepted=self._accepted, stale=self._stale)

    def is_stale(self) -> bool:
        return self._stale

    def is_brokers_complete(self) -> bool:
        return self._complete


class _Manager:
    def __init__(self, connected=(True, True, False)) -> None:
        self._platform_brokers = {
            "coinbase": _Broker(connected[0]),
            "okx": _Broker(connected[1]),
            "kraken": _Broker(connected[2]),
        }
        self._capital_state_lock = threading.RLock()
        self._capital_ready = True
        self._trading_halted_due_to_capital = False


def test_platform_counts_preserve_registered_denominator() -> None:
    manager = _Manager((True, True, False))
    assert v270._platform_counts(manager) == (3, 2)


def test_three_registered_two_connected_forces_ready_false() -> None:
    manager = _Manager((True, True, False))
    result = {
        "ready": 1.0,
        "total_capital": 103.35,
        # Simulate a previously accepted/stale 3-broker snapshot being read back.
        "valid_brokers": 3.0,
    }

    corrected = v270._fail_closed_result(
        manager,
        result,
        registered=3,
        connected=2,
    )

    assert corrected["ready"] == 0.0
    assert corrected["pending"] == 1.0
    assert corrected["registered_platform_brokers"] == 3.0
    assert corrected["connected_platform_brokers"] == 2.0
    assert manager._capital_ready is False
    assert manager._trading_halted_due_to_capital is True


def test_three_registered_three_connected_three_valid_remains_ready() -> None:
    manager = _Manager((True, True, True))
    result = {"ready": 1.0, "total_capital": 103.35, "valid_brokers": 3.0}

    corrected = v270._fail_closed_result(
        manager,
        result,
        registered=3,
        connected=3,
    )

    assert corrected is result
    assert manager._capital_ready is True


def test_current_publication_rejects_stale_or_incomplete() -> None:
    assert v270._current_publication_accepted_and_fresh(
        _Authority(accepted=True, stale=False, complete=True)
    ) is True
    assert v270._current_publication_accepted_and_fresh(
        _Authority(accepted=True, stale=True, complete=True)
    ) is False
    assert v270._current_publication_accepted_and_fresh(
        _Authority(accepted=False, stale=False, complete=True)
    ) is False
    assert v270._current_publication_accepted_and_fresh(
        _Authority(accepted=True, stale=False, complete=False)
    ) is False


def test_expected_floor_only_raises_to_registered_count(monkeypatch) -> None:
    manager = _Manager((True, True, False))
    authority = _Authority(expected=2)
    monkeypatch.setattr(v270, "_authority", lambda: authority)

    registered, connected, expected = v270._raise_expected_floor(manager)

    assert (registered, connected, expected) == (3, 2, 3)
    assert authority.expected_brokers == 3
    assert authority.set_calls == [3]


def test_expected_floor_never_lowers_existing_stricter_threshold(monkeypatch) -> None:
    manager = _Manager((True, True, True))
    authority = _Authority(expected=4)
    monkeypatch.setattr(v270, "_authority", lambda: authority)

    registered, connected, expected = v270._raise_expected_floor(manager)

    assert (registered, connected, expected) == (3, 3, 4)
    assert authority.expected_brokers == 4
    assert authority.set_calls == []


def test_install_helper_does_not_mutate_execution_safety_environment(monkeypatch) -> None:
    names = (
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
        "NIJA_NONCE_READY",
        "NIJA_KILL_SWITCH_ACTIVE",
        "NIJA_CAPITAL_FRESHNESS_TTL_S",
    )
    values = ("0", "0", "1", "90")
    for name, value in zip(names, values):
        monkeypatch.setenv(name, value)
    before = {name: os.environ[name] for name in names}

    manager = _Manager((True, True, False))
    authority = _Authority(expected=2)
    monkeypatch.setattr(v270, "_authority", lambda: authority)
    v270._raise_expected_floor(manager)
    v270._fail_closed_result(
        manager,
        {"ready": 1.0, "total_capital": 100.0, "valid_brokers": 3.0},
        registered=3,
        connected=2,
    )

    assert {name: os.environ[name] for name in names} == before
