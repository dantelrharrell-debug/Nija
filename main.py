"""Production Python entrypoint for NIJA."""

import sys as _sys

print("🔥 PYTHON ENTRYPOINT HIT", flush=True)

import importlib
import importlib.util
import logging
import os
import runpy
import traceback
import threading

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

logger = logging.getLogger(__name__)
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled", "y"}
_CANONICAL_PREHANDOFF_MARKER = "20260811-main-canonical-prehandoff-v60"


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY_ENV_VALUES


def _canonical_fast_path_enabled() -> bool:
    return bool(
        _truthy("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH")
        and _truthy("NIJA_DEFER_RUNTIME_SITE_HOOKS")
        and os.environ.get("NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY") == "1"
    )


def _load_repo_module_by_path(module_name: str, relative_path: str):
    """Load a startup helper directly from disk without importing bot.__init__."""
    path = os.path.join(_ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_global_runtime_startup_guards() -> None:
    """Install global position protection/cap guards before the bot package starts."""

    try:
        guards = _load_repo_module_by_path(
            "nija_global_runtime_startup_guards_prebot",
            os.path.join("bot", "global_runtime_startup_guards.py"),
        )
        installer = getattr(guards, "install_import_hook", None) or getattr(guards, "install", None)
        if callable(installer):
            installer()
            print("GLOBAL_RUNTIME_STARTUP_GUARDS_PREBOT_INSTALL_REQUESTED", flush=True)
            logger.warning("GLOBAL_RUNTIME_STARTUP_GUARDS_PREBOT_INSTALL_REQUESTED")
        else:
            logger.warning("GLOBAL_RUNTIME_STARTUP_GUARDS_PREBOT_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("GLOBAL_RUNTIME_STARTUP_GUARDS_PREBOT_FAILED err=%s", exc)


def _install_preactivation_runtime_identity_guard_v36() -> None:
    """Install canonical capital/strategy identity probes before bot startup."""

    try:
        guard = _load_repo_module_by_path(
            "nija_preactivation_runtime_identity_guard_v36_prebot",
            os.path.join("bot", "preactivation_runtime_identity_guard_v36.py"),
        )
        installer = getattr(guard, "install_import_hook", None) or getattr(guard, "install", None)
        if not callable(installer) or not bool(installer()):
            raise RuntimeError("preactivation runtime identity v36 installer unavailable or returned false")
        if os.environ.get("NIJA_PREACTIVATION_RUNTIME_IDENTITY_V36_INSTALLED") != "1":
            raise RuntimeError("preactivation runtime identity v36 did not publish installed marker")
        print("PREACTIVATION_RUNTIME_IDENTITY_V36_INSTALL_REQUESTED", flush=True)
        logger.critical("PREACTIVATION_RUNTIME_IDENTITY_V36_INSTALL_REQUESTED verified=true")
    except Exception as exc:
        logger.critical("PREACTIVATION_RUNTIME_IDENTITY_V36_INSTALL_FAILED err=%s", exc, exc_info=True)
        live = (
            str(os.environ.get("LIVE_TRADING", "")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("LIVE_CAPITAL_VERIFIED", "")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("NIJA_EXECUTION_ACTIVE", "")).lower() in {"1", "true", "yes", "on"}
        ) and str(os.environ.get("DRY_RUN_MODE", "")).lower() not in {"1", "true", "yes", "on"} and str(os.environ.get("PAPER_MODE", "")).lower() not in {"1", "true", "yes", "on"}
        if live:
            raise


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


def _install_runtime_auth_endpoint_repair() -> None:
    """Install Coinbase/OKX auth recursion guards on the canonical path."""

    try:
        repair = importlib.import_module("runtime_auth_recursion_endpoint_repair_patch")
        installer = getattr(repair, "install", None) or getattr(repair, "install_import_hook", None)
        if callable(installer):
            installer()
            print("RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("RUNTIME_AUTH_ENDPOINT_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("RUNTIME_AUTH_ENDPOINT_REPAIR_FAILED err=%s", exc)


def _install_current_capital_snapshot_freshness_repair() -> None:
    """Install current live-snapshot freshness repair before capital refresh."""

    try:
        repair = importlib.import_module("bot.current_capital_snapshot_freshness_repair_patch")
        installer = getattr(repair, "install_import_hook", None) or getattr(repair, "install", None)
        if callable(installer) and bool(installer()):
            print("CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR_INSTALL_REQUESTED", flush=True)
            logger.warning("CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR_INSTALL_REQUESTED")
        else:
            logger.warning("CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR_SKIPPED installer_missing_or_false")
    except Exception as exc:
        logger.warning("CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR_FAILED err=%s", exc)


def _install_authority_heartbeat_timeout_grace_repair() -> None:
    """Install soft authority-heartbeat timeout grace before the monitor starts."""

    try:
        repair = importlib.import_module("bot.authority_heartbeat_timeout_grace_patch")
        installer = getattr(repair, "install_import_hook", None) or getattr(repair, "install", None)
        if callable(installer) and bool(installer()):
            print("AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_INSTALL_REQUESTED", flush=True)
            logger.warning("AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_INSTALL_REQUESTED")
        else:
            logger.warning("AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_SKIPPED installer_missing_or_false")
    except Exception as exc:
        logger.warning("AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_FAILED err=%s", exc)


def _install_live_broker_profit_exit_v25() -> None:
    """Install fill-confirmed, fee-aware broker and engine exits."""

    try:
        repair = importlib.import_module("bot.live_broker_profit_exit_convergence_v25")
        installer = getattr(repair, "install_import_hook", None) or getattr(repair, "install", None)
        if not callable(installer) or not bool(installer()):
            raise RuntimeError("broker v25 installer unavailable or returned false")
        engine_repair = importlib.import_module("bot.live_engine_profit_exit_convergence_v25")
        engine_installer = getattr(engine_repair, "install_import_hook", None) or getattr(engine_repair, "install", None)
        if not callable(engine_installer) or not bool(engine_installer()):
            raise RuntimeError("engine v25 installer unavailable or returned false")
        print("LIVE_BROKER_PROFIT_EXIT_V25_INSTALL_REQUESTED", flush=True)
        logger.critical("LIVE_BROKER_PROFIT_EXIT_V25_INSTALL_REQUESTED broker_and_engine=true")
    except Exception as exc:
        logger.critical("LIVE_BROKER_PROFIT_EXIT_V25_INSTALL_FAILED err=%s", exc, exc_info=True)
        live = (
            str(os.environ.get("LIVE_TRADING", "")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("LIVE_CAPITAL_VERIFIED", "")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("NIJA_EXECUTION_ACTIVE", "")).lower() in {"1", "true", "yes", "on"}
        ) and str(os.environ.get("DRY_RUN_MODE", "")).lower() not in {"1", "true", "yes", "on"} and str(os.environ.get("PAPER_MODE", "")).lower() not in {"1", "true", "yes", "on"}
        if live:
            raise


def _install_all_in_profitability_authority_v324() -> None:
    """Install current-cost entry/exit economics on every production startup path."""

    try:
        authority = importlib.import_module("bot.runtime_all_in_profitability_authority_v324_patch")
        installer = getattr(authority, "install_import_hook", None) or getattr(authority, "install", None)
        if not callable(installer) or not bool(installer()):
            raise RuntimeError("all-in profitability v324 installer unavailable or returned false")
        if os.environ.get("NIJA_RUNTIME_ALL_IN_PROFITABILITY_V324_READY") != "1":
            raise RuntimeError("all-in profitability v324 did not attest ready")
        print("RUNTIME_ALL_IN_PROFITABILITY_AUTHORITY_V324_INSTALL_REQUESTED", flush=True)
        logger.critical(
            "RUNTIME_ALL_IN_PROFITABILITY_AUTHORITY_V324_INSTALL_REQUESTED "
            "verified=true current_costs=true short_carry=true short_borrow_proof=true "
            "protective_exits_unchanged=true safety_gates_bypassed=false"
        )
    except Exception as exc:
        logger.critical(
            "RUNTIME_ALL_IN_PROFITABILITY_AUTHORITY_V324_INSTALL_FAILED err=%s",
            exc,
            exc_info=True,
        )
        live = (
            str(os.environ.get("LIVE_TRADING", "")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("LIVE_CAPITAL_VERIFIED", "")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("NIJA_EXECUTION_ACTIVE", "")).lower() in {"1", "true", "yes", "on"}
        ) and str(os.environ.get("DRY_RUN_MODE", "")).lower() not in {"1", "true", "yes", "on"} and str(os.environ.get("PAPER_MODE", "")).lower() not in {"1", "true", "yes", "on"}
        if live:
            raise


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
            logger.warning("AUTHORITY_READY_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR_FAILED err=%s", exc)


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
            logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_FAILED err=%s", exc)


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


def _normalize_runtime_startup_env() -> None:
    module = importlib.import_module("bot.startup_runtime_safety")
    normalize_runtime_startup_env = getattr(module, "normalize_runtime_startup_env", None)
    if not callable(normalize_runtime_startup_env):
        raise RuntimeError("startup_runtime_safety.normalize_runtime_startup_env unavailable")
    startup_notes = normalize_runtime_startup_env(os.environ)
    if startup_notes:
        logger.warning("STARTUP_RUNTIME_SAFETY_NORMALIZED notes=%s", ",".join(startup_notes))


def _install_generation_sync_timing_patch() -> None:
    try:
        module = importlib.import_module("bot.generation_sync_timing_patch")
        installer = getattr(module, "install_import_hook", None)
        if callable(installer):
            installer()
            print("GENERATION_SYNC_TIMING_PATCH_INSTALL_REQUESTED", flush=True)
            logger.warning("GENERATION_SYNC_TIMING_PATCH_INSTALL_REQUESTED")
        else:
            logger.warning("GENERATION_SYNC_TIMING_PATCH_INSTALL_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("GENERATION_SYNC_TIMING_PATCH_INSTALL_FAILED err=%s", exc)


def _install_live_execution_authority_blocker_patch() -> None:
    """Install the live execution-authority blocker before the legacy handoff."""

    try:
        module = importlib.import_module("bot.live_execution_authority_blocker_patch")
        installer = getattr(module, "install_import_hook", None)
        if callable(installer):
            installer()
            print("LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_REQUESTED", flush=True)
            logger.warning("LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_REQUESTED")
        else:
            logger.warning("LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_SKIPPED installer_missing")
    except Exception as exc:
        logger.warning("LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_FAILED err=%s", exc)


def _run_legacy_preactivation_fanout() -> None:
    """Preserve the historical ``main.py`` fanout for direct/non-canonical runs."""

    _install_global_runtime_startup_guards()
    _install_preactivation_runtime_identity_guard_v36()
    _install_logging_format_guard()
    _install_runtime_auth_endpoint_repair()
    _install_current_capital_snapshot_freshness_repair()
    _install_authority_heartbeat_timeout_grace_repair()
    _install_live_broker_profit_exit_v25()
    _install_all_in_profitability_authority_v324()
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
    _normalize_runtime_startup_env()

    # Re-apply strict sanitizer after runtime startup normalization so unsafe flags
    # cannot be reintroduced by startup defaults.
    _run_pre_startup_sanitization()
    _install_generation_sync_timing_patch()
    _install_live_execution_authority_blocker_patch()


def _run_canonical_preactivation_handoff() -> None:
    """Keep the canonical writer-first path bounded while installing economic safety."""

    _install_all_in_profitability_authority_v324()
    os.environ["NIJA_MAIN_CANONICAL_PREHANDOFF_BOUNDED"] = "1"
    logger.critical(
        "MAIN_CANONICAL_PREHANDOFF_BOUNDED marker=%s duplicated_compatibility_fanout=false "
        "startup_runtime_safety_deferred=true all_in_profitability_v324=true handoff=bot.bot",
        _CANONICAL_PREHANDOFF_MARKER,
    )


if _canonical_fast_path_enabled():
    _run_canonical_preactivation_handoff()
else:
    _run_legacy_preactivation_fanout()

# Execute the real bot module as if it were run directly.  This preserves the
# normal __main__ startup path while allowing Railway to use ``python main.py``.
try:
    runpy.run_module("bot.bot", run_name="__main__")
except Exception:
    print("🔥 MAIN WRAPPER CAUGHT EXCEPTION", flush=True)
    traceback.print_exc()
    raise