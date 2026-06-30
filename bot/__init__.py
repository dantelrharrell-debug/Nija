# bot/__init__.py
"""
NIJA Bot Package
Core trading modules for the NIJA autonomous trading system
"""

import os
import logging
import importlib

# This package initializer runs before any bot.* submodule is imported. Use it
# for process-wide safety defaults that must be active before execution authority,
# nonce management, broker_manager, or the execution pipeline are loaded.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _redis_configured() -> bool:
    return bool(
        str(os.environ.get("NIJA_REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_PRIVATE_URL", "")).strip()
    )


# Live production safety: if Redis exists, never let an old Railway emergency
# variable keep NIJA in local-writer bypass mode. This must happen before
# bot.execution_authority_context imports and reads the env.
if _redis_configured():
    _cleared = []
    for _key in (
        "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
        "NIJA_DISABLE_WRITER_LOCK",
        "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
        "NIJA_CONFIRM_BYPASS_RISKS",
    ):
        if _truthy(_key):
            os.environ[_key] = "false"
            _cleared.append(_key)
    os.environ["NIJA_REQUIRE_DISTRIBUTED_LOCK"] = "true"
    os.environ["NIJA_STRICT_REDIS_LEASE"] = "1"
    os.environ["NIJA_AUTHORITY_NORMALIZED_AT_PACKAGE_IMPORT"] = "1"
    if _cleared:
        logger.warning(
            "STRICT_REDIS_AUTHORITY_ENFORCED_AT_PACKAGE_IMPORT cleared=%s",
            ",".join(_cleared),
        )

# Force safe runtime defaults early. These are still tunable upward in Railway.
os.environ.setdefault("NIJA_RECONCILE_BROKER_OPEN_ORDERS", "true")
os.environ.setdefault("NIJA_PENDING_ORDER_TIMEOUT_S", "90")
os.environ.setdefault("NIJA_STARTUP_POSITION_SYNC_ENABLED", "true")
os.environ.setdefault("NIJA_BROKER_SCOPED_POSITION_CAP", "true")
os.environ.setdefault("NIJA_PROFITABILITY_GUARD_ENABLED", "true")
os.environ.setdefault("NIJA_LOG_TRADE_DECISIONS", "true")
os.environ.setdefault("NIJA_NONCE_REBUILD_WAIT_FOR_LINEAGE_S", "15")

try:
    # Import the repo-level startup patch explicitly because some Railway start
    # modes do not auto-import sitecustomize soon enough for authority checks.
    importlib.import_module("sitecustomize")
except Exception as _startup_patch_exc:
    logger.warning("NIJA startup patch unavailable: %s", _startup_patch_exc)

try:
    from .okx_runtime_patch import install_import_hook as _install_okx_runtime_patch
    _install_okx_runtime_patch()
except Exception as _okx_patch_exc:
    logger.warning("OKX runtime patch unavailable: %s", _okx_patch_exc)

try:
    from .execution_pipeline_runtime_patch import install_import_hook as _install_execution_pipeline_patch
    _install_execution_pipeline_patch()
except Exception as _pipeline_patch_exc:
    logger.warning("Execution pipeline runtime patch unavailable: %s", _pipeline_patch_exc)

__version__ = "7.2.0"

logger.debug(f"NIJA Bot package initialized (v{__version__})")
