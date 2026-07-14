"""NIJA runtime release manifest and critical repair convergence audit."""

from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from typing import Callable

logger = logging.getLogger("nija.runtime_release_manifest")
RELEASE_ID = "20260714-runtime-convergence-v6"
_INSTALLED = False
_LOCK = threading.RLock()

# Installation order is intentional. Cost-basis compatibility must be active
# before exact snapshots reconcile legacy positions. Dynamic Kraken valuation is
# installed before the metadata and double-count guards that constrain its output.
# Profit realization is installed after every account/exit guard so it sees the
# final verified-cost and writer-authorized decision chain.
_INSTALLERS = (
    ("scan_wrapper_convergence_repair_patch", "install"),
    ("bot.position_cost_basis_legacy_repair_patch", "install_import_hook"),
    ("bot.position_sync_runtime_repair_patch", "install_import_hook"),
    ("bot.kraken_equity_runtime_patch", "install_import_hook"),
    ("bot.kraken_equity_metadata_guard_patch", "install_import_hook"),
    ("bot.kraken_equity_double_count_guard_patch", "install_import_hook"),
    ("bot.kraken_margin_auto_runtime_patch", "install_import_hook"),
    ("bot.kraken_all_account_exit_runtime_patch", "install_import_hook"),
    ("bot.kraken_exit_safety_convergence_patch", "install_import_hook"),
    ("bot.kraken_exit_final_guards_patch", "install_import_hook"),
    ("bot.kraken_exit_execution_safety_patch", "install_import_hook"),
    ("bot.kraken_exit_margin_cost_patch", "install_import_hook"),
    ("bot.kraken_profit_realization_guard_patch", "install_import_hook"),
    ("bot.coinbase_pem_quarantine_patch", "install_import_hook"),
)


def _deployment_sha() -> str:
    for name in (
        "RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "SOURCE_VERSION", "RENDER_GIT_COMMIT",
        "HEROKU_SLUG_COMMIT",
    ):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return "unknown"


def _invoke(module_name: str, function_name: str) -> tuple[bool, str]:
    try:
        module = importlib.import_module(module_name)
        installer: Callable = getattr(module, function_name)
        installer()
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def _expected_scan_wrapper_release() -> str:
    """Read the release contract from the installed scan-owner module itself.

    The previous manifest hard-coded an older release string. A legitimate scan
    owner upgrade from ``20260713-scan-wrapper-v2`` to ``20260714a`` therefore
    made the entire runtime fail closed even though every installer succeeded.
    Binding the audit to the module's own marker keeps the contract strict without
    making routine compatible upgrades look unsafe.
    """

    try:
        module = importlib.import_module("scan_wrapper_convergence_repair_patch")
        return str(getattr(module, "_MARKER", "") or "").strip()
    except Exception:
        return ""


def _scan_release_compatible(actual: str, expected: str) -> bool:
    actual = str(actual or "").strip()
    expected = str(expected or "").strip()
    return bool(actual and expected and actual == expected)


def _audit() -> tuple[bool, dict[str, str]]:
    results: dict[str, str] = {}
    ready = True
    for module_name, function_name in _INSTALLERS:
        ok, reason = _invoke(module_name, function_name)
        results[module_name] = reason
        ready = ready and ok

    scan_release = str(os.environ.get("NIJA_SCAN_WRAPPER_RELEASE", "") or "").strip()
    expected_scan_release = _expected_scan_wrapper_release()
    if not _scan_release_compatible(scan_release, expected_scan_release):
        ready = False
        results["scan_wrapper_release"] = (
            f"actual={scan_release or 'missing'};expected={expected_scan_release or 'missing'}"
        )
    else:
        results["scan_wrapper_release"] = scan_release

    profit_guard = str(os.environ.get("NIJA_KRAKEN_PROFIT_REALIZATION_GUARD_INSTALLED", "") or "").strip()
    if profit_guard != "1":
        ready = False
        results["profit_realization_guard"] = profit_guard or "missing"
    else:
        results["profit_realization_guard"] = "ready"
    return ready, results


def _publish(ready: bool, details: dict[str, str]) -> None:
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_READY"] = "1" if ready else "0"
    logger.critical(
        "NIJA_RUNTIME_RELEASE_MANIFEST release=%s deployment_sha=%s ready=%s python_pid=%s details=%s",
        RELEASE_ID,
        _deployment_sha(),
        str(ready).lower(),
        os.getpid(),
        details,
    )
    if not ready:
        logger.critical(
            "RUNTIME_RELEASE_INCOMPLETE_EXECUTION_UNSAFE release=%s action=keep_broker_order_gates_fail_closed",
            RELEASE_ID,
        )


def _watchdog() -> None:
    while True:
        try:
            ready, details = _audit()
            _publish(ready, details)
        except Exception as exc:
            logger.critical("RUNTIME_RELEASE_AUDIT_FAILED release=%s error=%s", RELEASE_ID, exc)
        time.sleep(max(30.0, float(os.environ.get("NIJA_RUNTIME_RELEASE_AUDIT_INTERVAL_S", "120") or 120)))


def install_import_hook() -> None:
    global _INSTALLED
    with _LOCK:
        ready, details = _audit()
        _publish(ready, details)
        if not _INSTALLED:
            _INSTALLED = True
            threading.Thread(target=_watchdog, name="RuntimeReleaseManifest", daemon=True).start()
    logger.critical("NIJA_RUNTIME_RELEASE_MANIFEST_INSTALLED release=%s", RELEASE_ID)


__all__ = [
    "RELEASE_ID",
    "install_import_hook",
    "_audit",
    "_deployment_sha",
    "_expected_scan_wrapper_release",
    "_scan_release_compatible",
]
