from __future__ import annotations

import threading
from datetime import datetime, timezone
from types import SimpleNamespace

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
    assert details["missing"] == []


def test_cold_or_incomplete_authority_keeps_bootstrap_fallback_available() -> None:
    authority = _authority(balances={"coinbase": 95.12})

    suppress, _ = patch._should_suppress_direct_fallback(
        authority,
        {"coinbase": object(), "okx": object()},
        bypass_startup_lock=True,
    )

    assert suppress is False


def test_non_bypass_refresh_is_outside_v180_scope() -> None:
    authority = _authority(
        balances={"kraken": 154.49, "coinbase": 95.12, "okx": 0.0}
    )

    suppress, _ = patch._should_suppress_direct_fallback(
        authority,
        {"coinbase": object(), "okx": object()},
        bypass_startup_lock=False,
    )

    assert suppress is False


def test_registration_must_be_complete_before_runtime_suppression() -> None:
    authority = _authority(
        balances={"kraken": 154.49, "coinbase": 95.12, "okx": 0.0},
        registered=False,
    )

    suppress, _ = patch._should_suppress_direct_fallback(
        authority,
        {"coinbase": object(), "okx": object()},
        bypass_startup_lock=True,
    )

    assert suppress is False


def test_v180_exposes_no_freshness_or_execution_bypass_api() -> None:
    for forbidden in (
        "extend_freshness",
        "accept_partial_snapshot",
        "force_activation",
        "grant_execution_authority",
        "clear_kill_switch",
    ):
        assert not hasattr(patch, forbidden)
