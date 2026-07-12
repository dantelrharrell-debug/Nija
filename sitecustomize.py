"""NIJA Python startup normalizer.

This module is imported automatically by Python. Keep it deterministic and
side-effect limited: normalize environment defaults before bot modules read them,
then request runtime patch installation.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

logger = logging.getLogger("nija.startup_patch")
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}


def _clean(value: str | None) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text.strip().strip('"').strip("'").strip()


def _truthy_name(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _float_env(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _redis_configured() -> bool:
    return bool(
        _clean(os.environ.get("NIJA_REDIS_URL"))
        or _clean(os.environ.get("REDIS_URL"))
        or _clean(os.environ.get("REDIS_PRIVATE_URL"))
        or _clean(os.environ.get("REDIS_PUBLIC_URL"))
    )


def _live_mode() -> bool:
    return not _truthy_name("DRY_RUN_MODE") and not _truthy_name("PAPER_MODE")


def _env_name(*parts: str) -> str:
    return "_".join(parts)


def _set_max_floor(name: str, value: float) -> None:
    current = _float_env(name, value)
    if name not in os.environ or current > value:
        os.environ[name] = str(value)


def _set_min_floor(name: str, value: float) -> None:
    current = _float_env(name, value)
    if name not in os.environ or current < value:
        os.environ[name] = str(value)


def _set_max_ceiling(name: str, value: float) -> None:
    current = _float_env(name, value)
    if name not in os.environ or current > value:
        os.environ[name] = str(value)


def _force_strict_redis_authority(label: str = "startup") -> None:
    if not (_live_mode() and _redis_configured()):
        return
    cleared: list[str] = []
    tails = (
        ("UNSAFE", "BYPASS", "DISTRIBUTED", "LOCK"),
        ("DISABLE", "WRITER", "LOCK"),
        ("FORCE", "LOCAL", "WRITER", "LOCK", "FALLBACK"),
        ("ALLOW", "LOCAL", "WRITER", "LOCK", "FALLBACK"),
        ("ALLOW", "DEGRADED", "WRITER", "AUTHORITY"),
        ("ALLOW", "REDIS", "DEGRADED"),
        ("EMERGENCY", "LOCAL", "FALLBACK", "ACTIVE"),
        ("CONFIRM", "BYPASS", "RISKS"),
    )
    for tail in tails:
        key = _env_name("NIJA", *tail)
        if _truthy_name(key):
            os.environ[key] = "false"
            cleared.append(key)
    os.environ[_env_name("NIJA", "REQUIRE", "DISTRIBUTED", "LOCK")] = "true"
    os.environ[_env_name("NIJA", "STRICT", "REDIS", "LEASE")] = "1"
    os.environ[_env_name("NIJA", "STRICT", "WRITER", "LOCK")] = "true"
    os.environ[_env_name("NIJA", "FAIL", "CLOSED", "EXIT", "ON", "UNREACHABLE", "REDIS")] = "true"
    try:
        retries = int(float(os.environ.get(_env_name("NIJA", "FAIL", "CLOSED", "MAX", "RETRY", "ATTEMPTS"), "0") or "0"))
    except Exception:
        retries = 0
    if retries < 36:
        os.environ[_env_name("NIJA", "FAIL", "CLOSED", "MAX", "RETRY", "ATTEMPTS")] = "36"
    if cleared:
        logger.warning(
            "STRICT_REDIS_AUTHORITY_ENFORCED label=%s cleared=%s require_distributed_lock=true strict_redis_lease=1",
            label,
            ",".join(cleared),
        )


def _normalize_okx() -> None:
    base = _clean(os.getenv("OKX_BASE_URL")).rstrip("/")
    if not base or base in {"https://www.okx.com", "https://openapi.okx.com"}:
        os.environ["OKX_BASE_URL"] = "https://us.okx.com"
    os.environ.setdefault("OKX_US_REGION", "true")
    for name in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE", "OKX_PASSPHRASE"):
        if name in os.environ:
            os.environ[name] = _clean(os.environ.get(name))


def _normalize_coinbase_pem() -> None:
    """Convert Coinbase PEM credential from escape-sequence form to true multiline.

    Railway and other platforms encode newlines as the two-character sequence
    ``\\n`` when storing multi-line secrets as env vars.  The Coinbase Advanced
    Trade SDK (and the JWT signing code) require a real PEM with actual newline
    characters.  This normalizes the env vars once at startup so every code
    path that reads them gets a usable key without having to do its own
    ``replace('\\\\n', '\\n')`` everywhere.
    """
    for name in ("COINBASE_API_SECRET", "COINBASE_PEM_CONTENT",
                 "COINBASE_PLATFORM_API_SECRET", "COINBASE_ADVANCED_API_SECRET"):
        raw = os.environ.get(name)
        if not raw:
            continue
        # Convert literal \n (backslash-n, 2 chars) to a real newline.
        normalized = raw.replace("\\n", "\n").strip()
        if normalized != raw:
            os.environ[name] = normalized
            logger.warning(
                "COINBASE_PEM_NORMALIZED name=%s begin=%s end=%s lines=%d",
                name,
                normalized.startswith("-----BEGIN"),
                normalized.strip().endswith("-----"),
                len(normalized.splitlines()),
            )


def _normalize_micro_cap_floors() -> None:
    if not _live_mode():
        return
    _set_max_floor("MIN_TRADE_USD", _float_env("NIJA_MICRO_CAP_MIN_TRADE_USD", 10.0))
    _set_max_floor("MIN_NOTIONAL_OVERRIDE", _float_env("NIJA_MICRO_CAP_MIN_NOTIONAL_USD", 10.0))
    _set_max_floor("MIN_CASH_TO_BUY", _float_env("NIJA_MICRO_CAP_MIN_CASH_TO_BUY_USD", 5.0))
    _set_max_floor("KRAKEN_MIN_NOTIONAL_USD", _float_env("NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD", 10.0))
    _set_max_floor("COINBASE_MIN_ORDER_USD", _float_env("NIJA_COINBASE_MICRO_MIN_ORDER_USD", 1.0))
    _set_max_floor("OKX_MIN_ORDER_USD", _float_env("NIJA_OKX_MICRO_MIN_ORDER_USD", 10.0))
    os.environ.setdefault("NIJA_MIN_NOTIONAL_SPENDABLE_CAP", "true")


def _normalize_writer_lock_timing() -> None:
    if not (_live_mode() and _redis_configured()):
        return
    for name in (
        "NIJA_WRITER_LOCK_ACQUIRE_TIMEOUT_S",
        "NIJA_DISTRIBUTED_LOCK_ACQUIRE_TIMEOUT_S",
        "NIJA_REDIS_LOCK_ACQUIRE_TIMEOUT_S",
        "NIJA_LOCK_ACQUIRE_TIMEOUT_S",
        "NIJA_FAIL_CLOSED_LOCK_ACQUIRE_TIMEOUT_S",
    ):
        _set_min_floor(name, 300.0)
    for name in (
        "NIJA_STALE_LOCK_HEARTBEAT_THRESHOLD_S",
        "NIJA_WRITER_LOCK_STALE_HEARTBEAT_THRESHOLD_S",
        "NIJA_RAILWAY_STALE_LOCK_HEARTBEAT_THRESHOLD_S",
        "STALE_LOCK_HEARTBEAT_THRESHOLD_S",
        "WRITER_LOCK_STALE_HEARTBEAT_THRESHOLD_S",
        "RAILWAY_STALE_LOCK_HEARTBEAT_THRESHOLD_S",
        "NIJA_WRITER_HEARTBEAT_STALE_THRESHOLD_S",
        "NIJA_LOCK_HEARTBEAT_STALE_THRESHOLD_S",
    ):
        _set_max_ceiling(name, 120.0)
    logger.warning(
        "WRITER_LOCK_TIMING_NORMALIZED wait_s=%s stale_threshold_s=%s max_retry_attempts=%s",
        os.environ.get("NIJA_WRITER_LOCK_ACQUIRE_TIMEOUT_S"),
        os.environ.get("NIJA_STALE_LOCK_HEARTBEAT_THRESHOLD_S"),
        os.environ.get("NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"),
    )


def _runtime_defaults() -> None:
    defaults = {
        "NIJA_STARTUP_POSITION_SYNC_ENABLED": "true",
        "NIJA_BROKER_SCOPED_POSITION_CAP": "true",
        "NIJA_PROFITABILITY_GUARD_ENABLED": "true",
        "NIJA_LOG_TRADE_DECISIONS": "true",
        "NIJA_PENDING_ORDER_TIMEOUT_S": "90",
        "NIJA_RECONCILE_BROKER_OPEN_ORDERS": "true",
        "NIJA_COLLAPSE_STARTUP_REGISTRATION_GATE": "true",
        "NIJA_ADAPTIVE_MIN_NOTIONAL_ENABLED": "true",
        "NIJA_POST_LOCK_CAPITAL_REFRESH": "true",
        "NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED": "true",
        "NIJA_COINBASE_EXECUTION_FAILOVER_ENABLED": "true",
        "NIJA_EXECUTION_ENTRY_SAFE_LOGGER_ENABLED": "true",
        "NIJA_RUNTIME_EXECUTION_AUTHORITY": "true",
        "NIJA_RISK_GATE_EXECUTION_BRIDGE_ENABLED": "true",
        "NIJA_TPE_MIN_NOTIONAL_REASON_SANITIZER_ENABLED": "true",
        "NIJA_STALE_EXCHANGE_KILL_SWITCH_RECOVERY_ENABLED": "true",
        "NIJA_EXCHANGE_KILL_SWITCH_IGNORE_INTERNAL_ROUTING_REJECTS": "true",
        "NIJA_KRAKEN_OHLC_THREAD_GUARD_ENABLED": "true",
        "NIJA_KRAKEN_OHLC_MAX_ACTIVE_THREADS": "24",
        "NIJA_KRAKEN_OHLC_SATURATION_COOLDOWN_S": "60",
        "NIJA_FALLBACK_REPAIR_MIN_TP1_PCT": "0.012",
        "NIJA_FALLBACK_REPAIR_MIN_TP2_PCT": "0.018",
        "NIJA_FALLBACK_REPAIR_MIN_TP3_PCT": "0.026",
        "NIJA_WRITER_LOCK_ACQUIRE_TIMEOUT_S": "300",
        "NIJA_DISTRIBUTED_LOCK_ACQUIRE_TIMEOUT_S": "300",
        "NIJA_REDIS_LOCK_ACQUIRE_TIMEOUT_S": "300",
        "NIJA_LOCK_ACQUIRE_TIMEOUT_S": "300",
        "NIJA_FAIL_CLOSED_LOCK_ACQUIRE_TIMEOUT_S": "300",
        "NIJA_STALE_LOCK_HEARTBEAT_THRESHOLD_S": "120",
        "NIJA_WRITER_LOCK_STALE_HEARTBEAT_THRESHOLD_S": "120",
        "NIJA_RAILWAY_STALE_LOCK_HEARTBEAT_THRESHOLD_S": "120",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    _normalize_writer_lock_timing()


def _install_patch_module(*, filename: str, module_name: str, success_log: str, error_prefix: str) -> None:
    try:
        patch_path = Path(__file__).resolve().parent / "bot" / filename
        spec = importlib.util.spec_from_file_location(module_name, patch_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load spec for {patch_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        installer = getattr(module, "install_import_hook", None)
        if callable(installer):
            installer()
            logger.warning(success_log)
    except Exception as exc:
        logger.warning("%s unavailable: %s", error_prefix, exc)


def _install_logging_format_guard() -> None:
    _install_patch_module(filename="logging_format_guard_patch.py", module_name="nija_logging_format_guard_patch", success_log="LOGGING_FORMAT_GUARD_INSTALL_REQUESTED", error_prefix="Logging format guard")


def _install_operator_emergency_stop_clear() -> None:
    _install_patch_module(filename="operator_emergency_stop_clear_patch.py", module_name="nija_operator_emergency_stop_clear_patch", success_log="OPERATOR_EMERGENCY_STOP_CLEAR_INSTALL_REQUESTED", error_prefix="Operator emergency stop clear")


def _install_stale_exchange_kill_switch_recovery() -> None:
    _install_patch_module(filename="stale_exchange_kill_switch_recovery_patch.py", module_name="nija_stale_exchange_kill_switch_recovery_patch", success_log="STALE_EXCHANGE_KILL_SWITCH_RECOVERY_INSTALL_REQUESTED", error_prefix="Stale exchange kill-switch recovery")


def _install_exchange_kill_switch_internal_reject_guard() -> None:
    _install_patch_module(filename="exchange_kill_switch_internal_reject_guard_patch.py", module_name="nija_exchange_kill_switch_internal_reject_guard_patch", success_log="EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_INSTALL_REQUESTED", error_prefix="Exchange kill-switch internal reject guard")


def _install_kraken_ohlc_thread_guard() -> None:
    _install_patch_module(filename="kraken_ohlc_thread_guard_patch.py", module_name="nija_kraken_ohlc_thread_guard_patch", success_log="KRAKEN_OHLC_THREAD_GUARD_INSTALL_REQUESTED", error_prefix="Kraken OHLC thread guard")


def _install_activation_snapshot_bridge() -> None:
    _install_patch_module(filename="activation_snapshot_bridge_patch.py", module_name="nija_activation_snapshot_bridge_patch", success_log="ACTIVATION_SNAPSHOT_BRIDGE_INSTALL_REQUESTED", error_prefix="Activation snapshot bridge")


def _install_live_active_dispatch_bridge() -> None:
    _install_patch_module(filename="live_active_dispatch_bridge_patch.py", module_name="nija_live_active_dispatch_bridge_patch", success_log="LIVE_ACTIVE_DISPATCH_BRIDGE_INSTALL_REQUESTED", error_prefix="Live-active dispatch bridge")


def _install_activation_pending_commit_monitor() -> None:
    _install_patch_module(filename="activation_pending_commit_monitor_patch.py", module_name="nija_activation_pending_commit_monitor_patch", success_log="ACTIVATION_PENDING_COMMIT_MONITOR_INSTALL_REQUESTED", error_prefix="Activation pending commit monitor")


def _install_trading_strategy_apex_wiring() -> None:
    _install_patch_module(filename="trading_strategy_apex_wiring_patch.py", module_name="nija_trading_strategy_apex_wiring_patch", success_log="TRADING_STRATEGY_APEX_WIRING_INSTALL_REQUESTED", error_prefix="TradingStrategy APEX wiring repair")


def _install_phase3_scan_budget() -> None:
    _install_patch_module(filename="phase3_scan_budget_patch.py", module_name="nija_phase3_scan_budget_patch", success_log="PHASE3_SCAN_BUDGET_INSTALL_REQUESTED", error_prefix="Phase3 scan budget patch")


def _install_phase3_overselect_import_repair() -> None:
    _install_patch_module(filename="phase3_overselect_import_repair_patch.py", module_name="nija_phase3_overselect_import_repair_patch", success_log="PHASE3_OVERSELECT_IMPORT_REPAIR_INSTALL_REQUESTED", error_prefix="Phase3 overselect import repair")


def _install_phase3_force_next_preserve_selection() -> None:
    _install_patch_module(filename="phase3_force_next_preserve_selection_patch.py", module_name="nija_phase3_force_next_preserve_selection_patch", success_log="PHASE3_FORCE_NEXT_PRESERVE_SELECTION_INSTALL_REQUESTED", error_prefix="Phase3 force-next preserve selection")


def _install_phase3_selection_width() -> None:
    _install_patch_module(filename="phase3_selection_width_patch.py", module_name="nija_phase3_selection_width_patch", success_log="PHASE3_SELECTION_WIDTH_INSTALL_REQUESTED", error_prefix="Phase3 selection width repair")


def _install_phase3_fallback_hold_skip() -> None:
    _install_patch_module(filename="phase3_fallback_hold_skip_patch.py", module_name="nija_phase3_fallback_hold_skip_patch", success_log="PHASE3_FALLBACK_HOLD_SKIP_INSTALL_REQUESTED", error_prefix="Phase3 fallback hold-skip bridge")


def _install_execution_bootstrap_authority_repair() -> None:
    _install_patch_module(filename="execution_bootstrap_authority_repair_patch.py", module_name="nija_execution_bootstrap_authority_repair_patch", success_log="EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_INSTALL_REQUESTED", error_prefix="Execution bootstrap authority repair")


def _install_execution_bootstrap_monitor_iteration_guard() -> None:
    _install_patch_module(filename="execution_bootstrap_monitor_iteration_guard_patch.py", module_name="nija_execution_bootstrap_monitor_iteration_guard_patch", success_log="EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_INSTALL_REQUESTED", error_prefix="Execution bootstrap monitor iteration guard")


def _install_forced_fallback_payload_repair() -> None:
    _install_patch_module(filename="forced_fallback_payload_repair_patch.py", module_name="nija_forced_fallback_payload_repair_patch", success_log="FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_REQUESTED", error_prefix="Forced fallback payload repair")


def _install_fallback_take_profit_geometry_repair() -> None:
    _install_patch_module(filename="fallback_take_profit_geometry_repair_patch.py", module_name="nija_fallback_take_profit_geometry_patch", success_log="FORCED_FALLBACK_TP_GEOMETRY_REPAIR_INSTALL_REQUESTED", error_prefix="Fallback take-profit geometry repair")


def _install_execution_pipeline_gate_repair() -> None:
    _install_patch_module(filename="execution_pipeline_gate_repair_patch.py", module_name="nija_execution_pipeline_gate_repair_patch", success_log="EXECUTION_PIPELINE_GATE_REPAIR_INSTALL_REQUESTED", error_prefix="Execution pipeline gate repair")


def _install_hard_controls_csm_repair() -> None:
    _install_patch_module(filename="hard_controls_csm_repair_patch.py", module_name="nija_hard_controls_csm_repair_patch", success_log="HARD_CONTROLS_CSM_REPAIR_INSTALL_REQUESTED", error_prefix="Hard controls CSM repair")


def _install_trading_state_dispatch_latch_repair() -> None:
    _install_patch_module(filename="trading_state_dispatch_latch_repair_patch.py", module_name="nija_trading_state_dispatch_latch_repair_patch", success_log="TRADING_STATE_DISPATCH_LATCH_REPAIR_INSTALL_REQUESTED", error_prefix="Trading state dispatch latch repair")


def _install_downstream_risk_governor_equity_repair() -> None:
    _install_patch_module(filename="downstream_risk_governor_equity_repair_patch.py", module_name="nija_downstream_risk_governor_equity_repair_patch", success_log="DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_INSTALL_REQUESTED", error_prefix="Downstream risk governor equity repair")


def _install_usdt_kraken_ecel_routing_repair() -> None:
    logger.warning("USDT_KRAKEN_ECEL_ROUTING_REPAIR_INSTALL_SKIPPED reason=legacy_blind_reroute_disabled source=sitecustomize")


def _install_coinbase_execution_failover() -> None:
    _install_patch_module(filename="coinbase_execution_failover_patch.py", module_name="nija_coinbase_execution_failover_patch", success_log="COINBASE_EXECUTION_FAILOVER_INSTALL_REQUESTED", error_prefix="Coinbase execution failover")


def _install_execution_entry_safe_logger() -> None:
    _install_patch_module(filename="execution_entry_nonblocking_logger_patch.py", module_name="nija_execution_entry_nonblocking_logger_patch", success_log="EXECUTION_ENTRY_SAFE_LOGGER_INSTALL_REQUESTED", error_prefix="Execution entry safe logger")


def _install_risk_gate_execution_bridge() -> None:
    _install_patch_module(filename="risk_gate_execution_bridge_patch.py", module_name="nija_risk_gate_execution_bridge_patch", success_log="RISK_GATE_EXECUTION_BRIDGE_INSTALL_REQUESTED", error_prefix="Risk gate execution bridge")


def _install_tpe_min_notional_reason_sanitizer() -> None:
    _install_patch_module(filename="tpe_min_notional_reason_sanitizer_patch.py", module_name="nija_tpe_min_notional_reason_sanitizer_patch", success_log="TPE_MIN_NOTIONAL_REASON_SANITIZER_INSTALL_REQUESTED", error_prefix="TPE min-notional reason sanitizer")


def _install_direct_broker_metadata_guard() -> None:
    _install_patch_module(filename="direct_broker_metadata_guard_patch.py", module_name="nija_direct_broker_metadata_guard_patch", success_log="DIRECT_BROKER_METADATA_GUARD_INSTALL_REQUESTED", error_prefix="Direct broker metadata guard")


def _install_okx_min_notional_prefilter_repair() -> None:
    _install_patch_module(filename="okx_min_notional_prefilter_repair_patch.py", module_name="nija_okx_min_notional_prefilter_repair_patch", success_log="OKX_MIN_NOTIONAL_PREFILTER_REPAIR_INSTALL_REQUESTED", error_prefix="OKX min-notional prefilter repair")


def _install_okx_final_order_submission_bridge() -> None:
    _install_patch_module(filename="okx_final_order_submission_bridge_patch.py", module_name="nija_okx_final_order_submission_bridge_patch", success_log="OKX_FINAL_ORDER_SUBMISSION_BRIDGE_INSTALL_REQUESTED", error_prefix="OKX final order submission bridge")


def _install_ecel_min_notional_rounding_repair() -> None:
    _install_patch_module(filename="ecel_min_notional_rounding_repair_patch.py", module_name="nija_ecel_min_notional_rounding_repair_patch", success_log="ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_INSTALL_REQUESTED", error_prefix="ECEL min-notional rounding repair")


_install_logging_format_guard()
_install_operator_emergency_stop_clear()
_force_strict_redis_authority("sitecustomize_import")
_normalize_okx()
_normalize_coinbase_pem()
_runtime_defaults()
_install_stale_exchange_kill_switch_recovery()
_install_exchange_kill_switch_internal_reject_guard()
_install_kraken_ohlc_thread_guard()
_install_okx_min_notional_prefilter_repair()
_install_okx_final_order_submission_bridge()
_install_ecel_min_notional_rounding_repair()
_install_tpe_min_notional_reason_sanitizer()
_install_trading_strategy_apex_wiring()
_install_phase3_scan_budget()
_install_phase3_overselect_import_repair()
_install_phase3_force_next_preserve_selection()
_install_phase3_selection_width()
_install_phase3_fallback_hold_skip()
_install_execution_bootstrap_authority_repair()
_install_execution_bootstrap_monitor_iteration_guard()
_install_forced_fallback_payload_repair()
_install_fallback_take_profit_geometry_repair()
_install_execution_pipeline_gate_repair()
_install_hard_controls_csm_repair()
_install_trading_state_dispatch_latch_repair()
_install_downstream_risk_governor_equity_repair()
_install_usdt_kraken_ecel_routing_repair()
_install_coinbase_execution_failover()
_install_direct_broker_metadata_guard()
_install_execution_entry_safe_logger()
_install_risk_gate_execution_bridge()
_install_activation_snapshot_bridge()
_install_activation_pending_commit_monitor()
_install_live_active_dispatch_bridge()
_normalize_micro_cap_floors()
_force_strict_redis_authority("sitecustomize_final")
_normalize_writer_lock_timing()
