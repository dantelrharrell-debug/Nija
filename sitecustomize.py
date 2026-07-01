"""NIJA Python startup normalizer.

This module is imported automatically by Python. Keep it deterministic and
side-effect limited: normalize environment defaults before bot modules read them.
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

    # Lock wait must be longer than stale-holder rescue eligibility.  The latest
    # Railway log showed wait=180s but stale threshold=240s, which can restart the
    # new writer before rescue is even legally allowed.  Keep strict Redis safety,
    # but align the clocks so a truly dead holder can be rescued inside the wait.
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


def _install_activation_snapshot_bridge() -> None:
    _install_patch_module(
        filename="activation_snapshot_bridge_patch.py",
        module_name="nija_activation_snapshot_bridge_patch",
        success_log="ACTIVATION_SNAPSHOT_BRIDGE_INSTALL_REQUESTED",
        error_prefix="Activation snapshot bridge",
    )


def _install_live_active_dispatch_bridge() -> None:
    _install_patch_module(
        filename="live_active_dispatch_bridge_patch.py",
        module_name="nija_live_active_dispatch_bridge_patch",
        success_log="LIVE_ACTIVE_DISPATCH_BRIDGE_INSTALL_REQUESTED",
        error_prefix="Live-active dispatch bridge",
    )


def _install_activation_pending_commit_monitor() -> None:
    _install_patch_module(
        filename="activation_pending_commit_monitor_patch.py",
        module_name="nija_activation_pending_commit_monitor_patch",
        success_log="ACTIVATION_PENDING_COMMIT_MONITOR_INSTALL_REQUESTED",
        error_prefix="Activation pending commit monitor",
    )


def _install_trading_strategy_apex_wiring() -> None:
    _install_patch_module(
        filename="trading_strategy_apex_wiring_patch.py",
        module_name="nija_trading_strategy_apex_wiring_patch",
        success_log="TRADING_STRATEGY_APEX_WIRING_INSTALL_REQUESTED",
        error_prefix="TradingStrategy APEX wiring repair",
    )


_force_strict_redis_authority("sitecustomize_import")
_normalize_okx()
_runtime_defaults()
_install_trading_strategy_apex_wiring()
_install_activation_snapshot_bridge()
_install_activation_pending_commit_monitor()
_install_live_active_dispatch_bridge()
_normalize_micro_cap_floors()
_force_strict_redis_authority("sitecustomize_final")
_normalize_writer_lock_timing()
