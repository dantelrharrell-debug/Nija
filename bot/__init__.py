# bot/__init__.py
"""
NIJA Bot Package
Core modules for the NIJA autonomous system
"""

import os
import logging
import importlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _redis_configured() -> bool:
    return bool(str(os.environ.get("NIJA_REDIS_URL", "")).strip() or str(os.environ.get("REDIS_URL", "")).strip() or str(os.environ.get("REDIS_PRIVATE_URL", "")).strip())


if _redis_configured():
    _cleared = []
    for _key in ("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", "NIJA_DISABLE_WRITER_LOCK", "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", "NIJA_CONFIRM_BYPASS_RISKS"):
        if _truthy(_key):
            os.environ[_key] = "false"
            _cleared.append(_key)
    os.environ["NIJA_REQUIRE_DISTRIBUTED_LOCK"] = "true"
    os.environ["NIJA_STRICT_REDIS_LEASE"] = "1"
    os.environ["NIJA_AUTHORITY_NORMALIZED_AT_PACKAGE_IMPORT"] = "1"
    if _cleared:
        logger.warning("STRICT_REDIS_AUTHORITY_ENFORCED_AT_PACKAGE_IMPORT cleared=%s", ",".join(_cleared))

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
}.items():
    os.environ.setdefault(_key, _value)

try:
    importlib.import_module("sitecustomize")
except Exception as _startup_patch_exc:
    logger.warning("NIJA startup patch unavailable: %s", _startup_patch_exc)

for _key, _value in (("MIN_TRADE_USD", "10"), ("MIN_NOTIONAL_OVERRIDE", "10"), ("MIN_CASH_TO_BUY", "5"), ("KRAKEN_MIN_NOTIONAL_USD", "10"), ("COINBASE_MIN_ORDER_USD", "1"), ("OKX_MIN_ORDER_USD", "10")):
    try:
        if float(os.environ.get(_key, _value) or _value) > float(_value):
            os.environ[_key] = _value
    except Exception:
        os.environ[_key] = _value

_PATCH_HOOKS = (
    ("min_notional_runtime_patch", "Adaptive min-notional runtime patch"),
    ("kraken_equity_runtime_patch", "Kraken equity hydration patch"),
    ("capital_balance_propagation_patch", "Capital balance propagation patch"),
    ("full_execution_observability_patch", "Full execution observability"),
    ("decision_pipeline_runtime_patch", "Decision pipeline telemetry"),
    ("no_trade_watchdog_runtime_patch", "Runtime scan diagnostics"),
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

__version__ = "7.2.0"
logger.debug(f"NIJA Bot package initialized (v{__version__})")
