#!/usr/bin/env python3
"""Offline fail-closed transport-error contract for NIJA's Kraken read retry.

This test injects exceptions into NIJA's existing local read-contention helper.
No network requests, real broker credentials, orders, trades, or production
configurations are accessed. Passing is NOT proof of end-to-end connectivity,
protective exits, authenticated fill reconciliation, or trading readiness.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from unittest import mock


class KrakenReadLockBusy(RuntimeError):
    """Synthetic exception with the canonical local-lock contention name."""


def _check_one_shot(module, exception_type: type[Exception]) -> None:
    attempts = 0
    injected = exception_type("synthetic_transport_fault")

    def fail() -> None:
        nonlocal attempts
        attempts += 1
        raise injected

    try:
        module._retry_read(fail, "synthetic_offline_account", "ReadOnlyBalance")
    except exception_type as observed:
        assert observed is injected, "original transport exception must be preserved"
    else:
        raise AssertionError("transport failure incorrectly treated as success")
    assert attempts == 1, "non-lock transport failure must not enter local-lock retry"


def _check_bounded_lock_retry(module) -> None:
    attempts = 0

    def recover() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise KrakenReadLockBusy("synthetic local lock contention")
        return "synthetic_read_success"

    # Avoid waiting for the real backoff in a deterministic isolated test.
    with mock.patch.object(module.time, "sleep", return_value=None):
        observed = module._retry_read(
            recover, "synthetic_offline_account", "ReadOnlyBalance"
        )
    assert observed == "synthetic_read_success"
    assert attempts == 2, "only classified local contention should be retried"


def _check_exhausted_local_lock_budget(module) -> None:
    """A permanently blocked read must propagate its original exception."""
    attempts = 0
    injected = KrakenReadLockBusy("synthetic local lock busy")

    def always_busy() -> None:
        nonlocal attempts
        attempts += 1
        raise injected

    # Force the first proposed backoff past the existing configured budget.
    # No real sleeping, broker I/O, or retries should occur.
    with mock.patch.object(module, "_retry_sleep_s", return_value=1000.0):
        try:
            module._retry_read(always_busy, "synthetic_offline_account", "ReadOnlyBalance")
        except KrakenReadLockBusy as observed:
            assert observed is injected, "exhaustion must propagate actual failure"
        else:
            raise AssertionError("exhausted lock retry incorrectly returned success")
    assert attempts == 1


def _load_pure_kraken_retry_module():
    """Import only the stateless file, never bot.__init__ or startup hooks."""
    source = Path(__file__).resolve().parents[2] / "bot" / "runtime_kraken_read_contention_recovery_v290_patch.py"
    spec = importlib.util.spec_from_file_location("offline_kraken_retry_v290", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the read-only retry helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    args = parser.parse_args()
    if not 0.0 < args.timeout_seconds <= 120.0:
        parser.error("--timeout-seconds must be within (0, 120]")

    names = ["timeout_fail_closed", "connection_fail_closed",
             "permission_fail_closed", "local_lock_retry", "local_lock_budget_fail_closed"]
    results: dict[str, bool] = {name: False for name in names}
    try:
        module = _load_pure_kraken_retry_module()

        for name, error_type in (
            ("timeout_fail_closed", TimeoutError),
            ("connection_fail_closed", ConnectionError),
            ("permission_fail_closed", PermissionError),
        ):
            _check_one_shot(module, error_type)
            results[name] = True
        _check_bounded_lock_retry(module)
        results["local_lock_retry"] = True
        _check_exhausted_local_lock_budget(module)
        results["local_lock_budget_fail_closed"] = True
    except Exception as exc:
        # Record only the exception type; never emit credentials or private data.
        print("Offline transport safety contract failed:", type(exc).__name__)

    passed = all(results.values())
    report = {
        "test": "kraken_read_transport_fault_contract",
        "scope": "offline_synthetic_exception_injection",
        "real_broker_network_tested": False,
        "execution_authorized": False,
        "production_observation_eligible": False,
        "checks": results,
        "passed": passed,
    }
    output = Path("chaos-results/network/kraken_timeout_contract.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(run())
