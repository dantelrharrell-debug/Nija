"""Tune startup position-fetch timeout without weakening position-sync safety.

Production logs on 2026-08-15 showed authoritative Kraken position snapshots
crossing the v95 five-second default. v95 correctly failed closed, but the
short default caused repeated timeout/invalidation during otherwise healthy
broker startup.

v98 changes only the *default* timeout to 12 seconds. An explicit
NIJA_POSITION_FETCH_TIMEOUT_S value remains authoritative. v99 is installed
from the same canonical slot so platform readiness is isolated from slow user
position snapshots while each user execution path remains fail closed. v105 is
installed before strategy recovery so the canonical TradingStrategy class is
published before cycle-prone optional dependencies are hydrated. v106 guards
the shared MultiAccountBrokerManager capital-refresh choke point against
same-thread recursive startup callbacks while preserving only already-published
authoritative capital truth. v107 serializes Kraken nonce rebuild recovery and
adds import-hook reentry hardening. v108 dispatches connected platform broker
position snapshots independently of capital readiness while preserving the
existing bounded/fail-closed v95/v98 position-sync contract. v116 closes the
activation/writer/readiness convergence races, and v117 adds bounded stale
position-fetch generations plus supervised-pending THREADS_STARTING liveness
without granting execution authority. v104 remains as the narrow legacy
import-cycle guard. v100/v102 retain bounded fail-closed class recovery, and
v103 retains the runtime reconciliation single-flight guard.
"""
from __future__ import annotations

import logging
import os

LOGGER = logging.getLogger("nija.position_sync_timeout_v98")
MARKER = "20260815-position-sync-timeout-v98"
_DEFAULT_TIMEOUT_S = 12.0
_INSTALLED = False


def _timeout_s_v98() -> float:
    raw = os.environ.get("NIJA_POSITION_FETCH_TIMEOUT_S")
    if raw is None or not str(raw).strip():
        return _DEFAULT_TIMEOUT_S
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_S


def _install_module(name: str) -> bool:
    try:
        module = __import__(f"bot.{name}", fromlist=[name])
    except ImportError:
        module = __import__(name)
    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    return callable(installer) and installer() is not False


def install() -> bool:
    global _INSTALLED
    try:
        from bot import position_sync_core_handoff_v95_patch as v95
    except ImportError:
        import position_sync_core_handoff_v95_patch as v95  # type: ignore[import]

    setattr(v95, "_timeout_s", _timeout_s_v98)
    ordered = [
        ("position_sync_account_isolation_v99_patch", "V99"),
        ("startup_publication_bootstrap_v105_patch", "V105"),
        ("capital_refresh_reentrancy_v106_patch", "V106"),
        ("startup_hook_nonce_v107_patch", "V107"),
        ("platform_position_sync_v108_patch", "V108"),
        ("runtime_convergence_v116_patch", "V116"),
        ("position_fetch_generation_v117_patch", "V117"),
        ("startup_strategy_import_cycle_v104_patch", "V104"),
        ("canonical_strategy_class_recovery_v100_patch", "V100"),
        ("canonical_strategy_class_recovery_v102_patch", "V102"),
        ("startup_convergence_v103_patch", "V103"),
    ]
    for module_name, label in ordered:
        if not _install_module(module_name):
            LOGGER.critical(
                "POSITION_SYNC_TIMEOUT_V98_%s_INSTALL_FAILED marker=%s trading_fail_closed=true",
                label,
                MARKER,
            )
            return False

    if _INSTALLED:
        return True
    os.environ["NIJA_POSITION_SYNC_TIMEOUT_V98_INSTALLED"] = "1"
    _INSTALLED = True
    LOGGER.critical(
        "POSITION_SYNC_TIMEOUT_V98_INSTALLED marker=%s default_timeout_s=%.1f explicit_env_override_preserved=true account_isolation_v99=true startup_publication_bootstrap_v105=true capital_refresh_reentrancy_v106=true startup_hook_nonce_v107=true platform_position_sync_v108=true runtime_convergence_v116=true position_fetch_generation_v117=true strategy_import_cycle_v104=true strategy_class_recovery_v100=true passive_strategy_recovery_v102=true startup_convergence_v103=true safety_gates_unchanged=true",
        MARKER,
        _DEFAULT_TIMEOUT_S,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_timeout_s_v98"]
