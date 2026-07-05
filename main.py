"""Production Python entrypoint for NIJA."""

import sys as _sys

print("🔥 PYTHON ENTRYPOINT HIT", flush=True)

import importlib
import logging
import os
import runpy
import traceback
import threading

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

logger = logging.getLogger(__name__)


def _install_logging_format_guard() -> None:
    """Install logging format protection before any startup modules emit logs."""

    try:
        guard = importlib.import_module("bot.logging_format_guard_patch")
        installer = getattr(guard, "install_import_hook", None) or getattr(guard, "install", None)
        if callable(installer):
            installer()
            print("LOGGING_FORMAT_GUARD_INSTALL_REQUESTED", flush=True)
            logger.warning("LOGGING_FORMAT_GUARD_INSTALL_REQUESTED")
        else:
            logger.warning("LOGGING_FORMAT_GUARD_INSTALL_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("LOGGING_FORMAT_GUARD_INSTALL_FAILED err=%s", exc)


def _run_pre_startup_sanitization() -> None:
    """Sanitize live Redis bypass flags before startup safety initializes."""

    try:
        sanitizer = importlib.import_module("bot.strict_live_startup_sanitizer")
        sanitizer.sanitize("main_pre_startup_runtime_safety")
    except Exception as exc:
        logger.warning("Strict live startup sanitizer unavailable before startup safety init: %s", exc)


def _install_strategy_publication() -> None:
    """Install the live strategy publication hook before bot.py is executed."""

    try:
        publisher = importlib.import_module("bot.strategy_publication_patch")
        installer = getattr(publisher, "install_import_hook", None)
        if callable(installer):
            installer()
            print("STRATEGY_PUBLICATION_INSTALL_REQUESTED", flush=True)
            logger.warning("STRATEGY_PUBLICATION_INSTALL_REQUESTED")
        else:
            logger.warning("STRATEGY_PUBLICATION_INSTALL_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("STRATEGY_PUBLICATION_INSTALL_FAILED err=%s", exc)


def _install_authority_readiness_repair() -> None:
    """Install the post-LIVE_ACTIVE authority-readiness repair hook."""

    try:
        repair = importlib.import_module("bot.execution_authority_readiness_repair_patch")
        installer = getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("AUTHORITY_READY_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("AUTHORITY_READY_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("AUTHORITY_READY_REPAIR_INSTALL_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR_INSTALL_FAILED err=%s", exc)


def _install_execution_bootstrap_authority_repair() -> None:
    """Install the live execution bootstrap-authority repair hook."""

    try:
        repair = importlib.import_module("bot.execution_bootstrap_authority_repair_patch")
        installer = getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_INSTALL_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_INSTALL_FAILED err=%s", exc)


def _install_forced_fallback_payload_repair() -> None:
    """Install the forced-fallback payload construction repair hook."""

    try:
        repair = importlib.import_module("bot.forced_fallback_payload_repair_patch")
        installer = getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_FAILED err=%s", exc)


def _install_execution_pipeline_gate_repair() -> None:
    """Install the stale LIVE_ACTIVE execution-pipeline gate repair hook."""

    try:
        repair = importlib.import_module("bot.execution_pipeline_gate_repair_patch")
        installer = getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("EXECUTION_PIPELINE_GATE_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("EXECUTION_PIPELINE_GATE_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("EXECUTION_PIPELINE_GATE_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("EXECUTION_PIPELINE_GATE_REPAIR_FAILED err=%s", exc)


def _install_hard_controls_csm_repair() -> None:
    """Install hard-controls stale CSM-v2 capital-readiness repair hook."""

    try:
        repair = importlib.import_module("bot.hard_controls_csm_repair_patch")
        installer = getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("HARD_CONTROLS_CSM_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("HARD_CONTROLS_CSM_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("HARD_CONTROLS_CSM_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("HARD_CONTROLS_CSM_REPAIR_FAILED err=%s", exc)


def _install_trading_state_dispatch_latch_repair() -> None:
    """Install LIVE_ACTIVE dispatch-latch repair on TradingStateMachine."""

    try:
        repair = importlib.import_module("bot.trading_state_dispatch_latch_repair_patch")
        installer = getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("TRADING_STATE_DISPATCH_LATCH_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_FAILED err=%s", exc)


def _install_downstream_risk_governor_equity_repair() -> None:
    """Install portfolio-equity repair for downstream RiskGovernor checks."""

    try:
        repair = importlib.import_module("bot.downstream_risk_governor_equity_repair_patch")
        installer = getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_FAILED err=%s", exc)


def _install_usdt_kraken_ecel_routing_repair() -> None:
    """Legacy installer intentionally disabled.

    The old module blindly rewrote coinbase/auto *-USDT orders to Kraken.  That
    caused OKX-selected USDT entries to route to Kraken and fail after the venue
    guard had already selected the correct broker.  Venue preservation is now
    handled by bot.venue_route_guard_patch, bot.execution_pipeline_runtime_patch,
    bot.ecel_contract_route_repair_patch, order_normalizer, and
    exchange_normalizer.
    """

    logger.warning("USDT_KRAKEN_ECEL_ROUTING_REPAIR_INSTALL_SKIPPED reason=legacy_blind_reroute_disabled")
    print("USDT_KRAKEN_ECEL_ROUTING_REPAIR_INSTALL_SKIPPED reason=legacy_blind_reroute_disabled", flush=True)


def _install_live_entry_completion_repair() -> None:
    """Install live signal-to-execution completion, nonce-wait, and OKX log repairs."""

    try:
        repair = importlib.import_module("bot.live_entry_completion_repair_patch")
        installer = getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("LIVE_ENTRY_COMPLETION_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("LIVE_ENTRY_COMPLETION_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("LIVE_ENTRY_COMPLETION_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("LIVE_ENTRY_COMPLETION_REPAIR_FAILED err=%s", exc)


_install_logging_format_guard()
_run_pre_startup_sanitization()
_install_strategy_publication()
_install_authority_readiness_repair()
_install_execution_bootstrap_authority_repair()
_install_forced_fallback_payload_repair()
_install_execution_pipeline_gate_repair()
_install_hard_controls_csm_repair()
_install_trading_state_dispatch_latch_repair()
_install_downstream_risk_governor_equity_repair()
_install_usdt_kraken_ecel_routing_repair()
_install_live_entry_completion_repair()
from bot.startup_runtime_safety import normalize_runtime_startup_env

normalize_runtime_startup_env()

# Re-apply strict sanitizer after runtime startup normalization so unsafe flags
# cannot be reintroduced by startup defaults.
_run_pre_startup_sanitization()

try:
    from bot.generation_sync_timing_patch import install_import_hook as _install_generation_sync_timing_patch
    _install_generation_sync_timing_patch()
    print("GENERATION_SYNC_TIMING_PATCH_INSTALL_REQUESTED", flush=True)
    logger.warning("GENERATION_SYNC_TIMING_PATCH_INSTALL_REQUESTED")
except Exception as _gen_sync_exc:
    logger.warning("GENERATION_SYNC_TIMING_PATCH_INSTALL_FAILED err=%s", _gen_sync_exc)

# Ensure the live execution authority blocker patch is loaded before bot.py creates
# or checks the TradingStateMachine.  It removes stale heartbeat-stage assumptions
# and makes dispatch authority depend on the live writer-lock generation.
try:
    from bot.live_execution_authority_blocker_patch import install_import_hook as _install_live_execution_authority_blocker_patch
    _install_live_execution_authority_blocker_patch()
    print("LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_REQUESTED", flush=True)
    logger.warning("LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_REQUESTED")
except Exception as _live_auth_exc:
    logger.warning("LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_FAILED err=%s", _live_auth_exc)

# Execute the real bot module as if it were run directly.  This preserves the
# normal __main__ startup path while allowing Railway to use ``python main.py``.
try:
    runpy.run_module("bot.bot", run_name="__main__")
except Exception:
    print("🔥 MAIN WRAPPER CAUGHT EXCEPTION", flush=True)
    traceback.print_exc()
    raise
