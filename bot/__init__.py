# bot/__init__.py
"""NIJA bot package startup hooks."""

from __future__ import annotations

import importlib
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _redis_configured() -> bool:
    return bool(
        str(os.environ.get("NIJA_REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_PRIVATE_URL", "")).strip()
        or str(os.environ.get("REDIS_PUBLIC_URL", "")).strip()
    )


def _env_name(*parts: str) -> str:
    return "_".join(parts)


def _copy_first_present_env(canonical: str, aliases: tuple[str, ...]) -> str:
    """Populate *canonical* from the first non-empty alias without exposing values."""
    if str(os.environ.get(canonical, "")).strip():
        return ""
    for alias in aliases:
        value = str(os.environ.get(alias, "")).strip()
        if value:
            os.environ[canonical] = value
            return alias
    return ""


def _normalize_credential_aliases(label: str) -> None:
    """Accept common Railway/user secret aliases and map them to NIJA canonical names."""
    alias_map: dict[str, tuple[str, ...]] = {
        "KRAKEN_PLATFORM_API_KEY": ("KRAKEN_API_KEY", "KRAKEN_MASTER_API_KEY", "KRAKEN_MASTER_KEY", "KRAKEN_PLATFORM_KEY"),
        "KRAKEN_PLATFORM_API_SECRET": ("KRAKEN_API_SECRET", "KRAKEN_PRIVATE_KEY", "KRAKEN_SECRET_KEY", "KRAKEN_MASTER_API_SECRET", "KRAKEN_MASTER_SECRET", "KRAKEN_PLATFORM_SECRET"),
        "KRAKEN_USER_DAIVON_API_KEY": ("KRAKEN_USER_DAIVON_FRAZIER_API_KEY", "KRAKEN_DAIVON_API_KEY", "DAIVON_KRAKEN_API_KEY", "KRAKEN_USER_1_API_KEY", "KRAKEN_USER1_API_KEY"),
        "KRAKEN_USER_DAIVON_API_SECRET": ("KRAKEN_USER_DAIVON_FRAZIER_API_SECRET", "KRAKEN_DAIVON_API_SECRET", "DAIVON_KRAKEN_API_SECRET", "KRAKEN_USER_1_API_SECRET", "KRAKEN_USER1_API_SECRET", "KRAKEN_DAIVON_SECRET", "DAIVON_KRAKEN_SECRET"),
        "KRAKEN_USER_TANIA_API_KEY": ("KRAKEN_USER_TANIA_GILBERT_API_KEY", "KRAKEN_TANIA_API_KEY", "TANIA_KRAKEN_API_KEY", "KRAKEN_USER_2_API_KEY", "KRAKEN_USER2_API_KEY", "KRAKEN_USER_TANIA_KEY"),
        "KRAKEN_USER_TANIA_API_SECRET": ("KRAKEN_USER_TANIA_GILBERT_API_SECRET", "KRAKEN_TANIA_API_SECRET", "TANIA_KRAKEN_API_SECRET", "KRAKEN_USER_2_API_SECRET", "KRAKEN_USER2_API_SECRET", "KRAKEN_USER_TANIA_SECRET", "KRAKEN_TANIA_SECRET", "TANIA_KRAKEN_SECRET"),
        "OKX_API_KEY": ("OKX_PLATFORM_API_KEY", "OKX_MASTER_API_KEY", "OKX_KEY"),
        "OKX_API_SECRET": ("OKX_SECRET_KEY", "OKX_PLATFORM_API_SECRET", "OKX_MASTER_API_SECRET", "OKX_SECRET"),
        "OKX_PASSPHRASE": ("OKX_API_PASSPHRASE", "OKX_PASS_PHRASE", "OKX_PLATFORM_PASSPHRASE", "OKX_MASTER_PASSPHRASE", "OKX_PASSWORD"),
        "ALPACA_USER_TANIA_API_KEY": ("ALPACA_USER_TANIA_GILBERT_API_KEY", "ALPACA_TANIA_API_KEY", "TANIA_ALPACA_API_KEY", "ALPACA_USER_2_API_KEY", "ALPACA_USER2_API_KEY"),
        "ALPACA_USER_TANIA_API_SECRET": ("ALPACA_USER_TANIA_GILBERT_API_SECRET", "ALPACA_TANIA_API_SECRET", "TANIA_ALPACA_API_SECRET", "ALPACA_USER_2_API_SECRET", "ALPACA_USER2_API_SECRET"),
    }
    used: list[str] = []
    for canonical, aliases in alias_map.items():
        source = _copy_first_present_env(canonical, aliases)
        if source:
            used.append(f"{canonical}<-{source}")
    if used:
        logger.warning("CREDENTIAL_ALIAS_NORMALIZED label=%s mapped=%s", label, ",".join(used))


def _strict_live_cleanup(label: str) -> None:
    if not _redis_configured():
        return
    tails = [
        ("UNSAFE", "BYPASS", "DISTRIBUTED", "LOCK"),
        ("DISABLE", "WRITER", "LOCK"),
        ("FORCE", "LOCAL", "WRITER", "LOCK", "FALLBACK"),
        ("ALLOW", "LOCAL", "WRITER", "LOCK", "FALLBACK"),
        ("ALLOW", "DEGRADED", "WRITER", "AUTHORITY"),
        ("ALLOW", "REDIS", "DEGRADED"),
        ("EMERGENCY", "LOCAL", "FALLBACK", "ACTIVE"),
        ("CONFIRM", "BYPASS", "RISKS"),
    ]
    cleared: list[str] = []
    for tail in tails:
        key = _env_name("NIJA", *tail)
        if _truthy(key):
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
    if retries <= 0:
        os.environ[_env_name("NIJA", "FAIL", "CLOSED", "MAX", "RETRY", "ATTEMPTS")] = "12"
    if cleared:
        logger.warning("STRICT_LIVE_STARTUP_CLEANUP label=%s cleared=%s", label, ",".join(cleared))


def _set_float_floor(key: str, value: str) -> None:
    try:
        if float(os.environ.get(key, value) or value) < float(value):
            os.environ[key] = value
    except Exception:
        os.environ[key] = value


_normalize_credential_aliases("bot_init_first")
try:
    _strict_sanitizer = importlib.import_module(".strict_live_startup_sanitizer", __name__)
    _strict_sanitizer.sanitize("bot_init_first")
except Exception as _exc:
    logger.warning("Strict live startup sanitizer unavailable: %s", _exc)
_strict_live_cleanup("bot_init_pre_defaults")

for _key, _value in {
    "NIJA_RECONCILE_BROKER_OPEN_ORDERS": "true",
    "NIJA_PENDING_ORDER_TIMEOUT_S": "90",
    "NIJA_STARTUP_POSITION_SYNC_ENABLED": "true",
    "NIJA_BROKER_SCOPED_POSITION_CAP": "true",
    "NIJA_PROFITABILITY_GUARD_ENABLED": "true",
    "NIJA_LOG_TRADE_DECISIONS": "true",
    "NIJA_NONCE_REBUILD_WAIT_FOR_LINEAGE_S": "15",
    "NIJA_ADAPTIVE_MIN_NOTIONAL_ENABLED": "true",
    "NIJA_NO_TRADE_WATCHDOG_ENABLED": "true",
    "NIJA_NO_TRADE_WATCHDOG_INTERVAL": "10",
    "NIJA_DECISION_PIPELINE_TRACE": "true",
    "NIJA_FULL_EXECUTION_OBSERVABILITY": "true",
    "NIJA_KRAKEN_EQUITY_HYDRATION": "true",
    "NIJA_CAPITAL_BALANCE_PROPAGATION": "true",
    "NIJA_LIVE_ENTRY_RUNTIME_FIXES": "true",
    "NIJA_EXECUTABLE_TRADE_RUNTIME_PATCH": "true",
    "NIJA_GENERATION_MISMATCH_RECOVERY_COOLDOWN_S": "0",
    "NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD": "23.00",
    "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD": "23.00",
    "NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT": "0.10",
    "KRAKEN_MIN_QUOTE_BUFFER_PCT": "0.10",
    "KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT": "0.05",
    "NIJA_KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT": "0.05",
    "NIJA_APPLY_GLOBAL_EXECUTABLE_MIN_TRADE": "true",
    "HF_TAKE_PROFIT_PCT": "1.0",
    "NIJA_MICROCAP_TP1_PERCENT": "1.0",
    "NIJA_MICROCAP_STOP_LOSS_PERCENT": "0.30",
    "MIN_EXPECTANCY_THRESHOLD_PCT": "0.00",
    "MIN_TP_PCT": "0.010",
    "MAX_SL_PCT": "0.003",
    "NIJA_WRITER_LOCK_STALE_HEARTBEAT_THRESHOLD_S": "90",
    "NIJA_STALE_LOCK_HEARTBEAT_THRESHOLD_S": "90",
    "NIJA_RAILWAY_STALE_LOCK_HEARTBEAT_THRESHOLD_S": "90",
    "NIJA_STALE_LOCK_RESCUE_PTTL_MS": "10000",
    "NIJA_WRITER_LOCK_NEAR_EXPIRY_RESCUE_MS": "10000",
}.items():
    os.environ.setdefault(_key, _value)

try:
    importlib.import_module("sitecustomize")
except Exception as _exc:
    logger.warning("NIJA startup patch unavailable: %s", _exc)
_normalize_credential_aliases("bot_init_after_sitecustomize")
_strict_live_cleanup("bot_init_after_sitecustomize")

for _key, _value in (
    ("MIN_TRADE_USD", "23.00"),
    ("MIN_POSITION_USD", "23.00"),
    ("MIN_NOTIONAL_OVERRIDE", "23.00"),
    ("MIN_CASH_TO_BUY", "5"),
    ("KRAKEN_MIN_NOTIONAL_USD", "23.00"),
    ("NIJA_KRAKEN_MIN_NOTIONAL_USD", "23.00"),
    ("NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD", "23.00"),
    ("NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD", "23.00"),
    ("NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD", "23.00"),
    ("KRAKEN_MIN_QUOTE_BUFFER_PCT", "0.10"),
    ("NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT", "0.10"),
    ("KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT", "0.05"),
    ("NIJA_KRAKEN_EFFECTIVE_NOTIONAL_EXTRA_BUFFER_PCT", "0.05"),
    ("COINBASE_MIN_ORDER_USD", "1"),
    ("OKX_MIN_ORDER_USD", "2"),
):
    _set_float_floor(_key, _value)

_PATCH_HOOKS = (
    ("strict_live_startup_sanitizer", "Strict live startup sanitizer"),
    ("live_redis_execution_bypass_guard", "Live Redis execution bypass guard"),
    ("writer_lock_release_guard", "Writer lock release guard"),
    ("min_notional_runtime_patch", "Adaptive min-notional runtime patch"),
    ("kraken_equity_runtime_patch", "Kraken equity hydration patch"),
    ("capital_balance_propagation_patch", "Capital balance propagation patch"),
    ("post_lock_capital_refresh_patch", "Post-lock capital refresh patch"),
    ("full_execution_observability_patch", "Full execution observability"),
    ("decision_pipeline_runtime_patch", "Decision pipeline telemetry"),
    ("generation_sync_timing_patch", "Generation sync timing patch"),
    ("execution_entry_tp_geometry_patch", "Execution entry TP geometry patch"),
    ("live_execution_authority_blocker_patch", "Live execution authority blocker patch"),
    ("no_trade_watchdog_runtime_patch", "Runtime scan diagnostics"),
    ("live_entry_runtime_fixes", "Live entry runtime fixes"),
    ("executable_trade_runtime_patch", "Executable trade runtime repair"),
    ("kraken_live_order_size_repair_patch", "Kraken live order-size repair"),
    ("kraken_execution_floor_guard_patch", "Kraken final execution-floor guard"),
    ("execution_route_integrity_patch", "Execution route integrity guard"),
    ("okx_runtime_patch", "OKX runtime patch"),
    ("execution_pipeline_runtime_patch", "Execution pipeline runtime patch"),
    ("coinbase_position_runtime_patch", "Coinbase position runtime patch"),
)

for _module_name, _label in _PATCH_HOOKS:
    try:
        _mod = importlib.import_module(f".{_module_name}", __name__)
        _mod.install_import_hook()
    except Exception as _exc:
        logger.warning("%s unavailable: %s", _label, _exc)

__version__ = "7.2.3"
logger.debug("NIJA Bot package initialized (v%s)", __version__)
