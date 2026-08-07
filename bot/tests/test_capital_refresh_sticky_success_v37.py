from __future__ import annotations

import importlib.util
import logging
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

BOT_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


guard = _load("capital_refresh_stall_guard_v35", "capital_refresh_stall_guard_v35.py")
hotfix = _load("capital_refresh_sticky_success_v37_patch_test", "capital_refresh_sticky_success_v37_patch.py")
sys.modules["bot.capital_refresh_stall_guard_v35"] = guard
hotfix._patch_guard(guard)


class _Broker:
    def __init__(self, value=None, release=None):
        self._last_known_balance = value
        self._balance_fetch_errors = 0
        self._release = release
        self.calls = 0

    def get_account_balance(self):
        self.calls += 1
        if self._release is not None:
            self._release.wait(1.0)
        return self._last_known_balance


def _reset() -> None:
    guard._IN_FLIGHT.clear()
    guard._BROKER_SEQUENCE.clear()
    guard._OBSERVATIONS.clear()
    guard._LAST_TIMEOUT_LOGGED.clear()
    guard._WAS_TIMING_OUT.clear()
    guard._begin_refresh_context()
    hotfix._CTX.cycle_id = 1
    hotfix._CTX.decisions = {}


def test_successful_batch_payload_is_sticky_for_repeat_reads():
    _reset()
    broker = _Broker(123.45)
    batch = guard._BalanceFetchBatch({"coinbase": broker})
    assert batch.result_for("coinbase", broker) == 123.45

    started = time.monotonic()
    assert batch.result_for("coinbase", broker) == 123.45
    assert time.monotonic() - started < 0.05
    assert broker.calls == 1
    assert hotfix._CTX.decisions["coinbase"]["include"] is True


def test_precoordinator_okx_success_survives_later_timeout():
    _reset()
    broker = _Broker(144.96)
    started = time.monotonic()
    hotfix._capture_success(
        broker,
        "okx",
        144.96,
        started,
        started + 0.01,
        time.time(),
    )

    release = threading.Event()
    broker._release = release
    try:
        with patch.object(guard, "_broker_timeout_seconds", return_value=0.05), patch.object(
            guard, "_cycle_deadline_seconds", return_value=0.10
        ):
            batch = guard._BalanceFetchBatch({"okx": broker})
            assert batch.result_for("okx", broker) == 144.96
    finally:
        release.set()

    status = guard.current_refresh_fallback_status()
    assert "okx" not in status.get("excluded_brokers", {})
    assert hotfix._CTX.decisions["okx"]["include"] is True


def test_timeout_without_any_usable_payload_is_excluded():
    _reset()
    release = threading.Event()
    broker = _Broker(None, release)
    try:
        with patch.object(guard, "_broker_timeout_seconds", return_value=0.05), patch.object(
            guard, "_cycle_deadline_seconds", return_value=0.10
        ):
            batch = guard._BalanceFetchBatch({"okx": broker})
            assert batch.result_for("okx", broker) == 0.0
    finally:
        release.set()

    status = guard.current_refresh_fallback_status()
    assert "okx" in status.get("excluded_brokers", {})
    assert hotfix._CTX.decisions["okx"]["include"] is False


def test_fallback_age_uses_monotonic_not_wall_clock():
    _reset()
    now_mono = time.monotonic()
    guard._OBSERVATIONS["coinbase"] = guard._Observation(
        50.0,
        now_mono - 5.0,
        time.time() - 999999.0,
        1,
    )
    batch = object.__new__(guard._BalanceFetchBatch)
    batch._nija_v37_resolved = {}
    batch._nija_v37_lock = threading.Lock()
    batch._flights = {}
    batch._cycle_deadline = now_mono + 1.0

    assert batch._handle_failure("coinbase", "exception:test") == 50.0
    status = guard.current_refresh_fallback_status()
    assert 4.0 <= status["brokers"]["coinbase"]["age_s"] <= 10.0


def test_success_telemetry_contains_decision(caplog):
    _reset()
    caplog.set_level(logging.INFO)
    broker = _Broker(75.0)
    batch = guard._BalanceFetchBatch({"coinbase": broker})
    assert batch.result_for("coinbase", broker) == 75.0

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "CAPITAL_REFRESH_FETCH_SUCCESS" in text
    assert "CAPITAL_REFRESH_DECISION" in text
    assert "broker=coinbase" in text
    assert "include=true" in text
