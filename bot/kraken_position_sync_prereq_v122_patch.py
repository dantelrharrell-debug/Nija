"""Require the bounded Kraken read layer before platform position sync can start.

Production release v121 proved a startup ordering race: v98 installed v108
(platform position-sync dispatch) before v121 (bounded Kraken REST reads). v108
can patch capital refresh and launch a Kraken reconciliation worker immediately.
If that first worker enters Kraken's shared private-API lock before v121 wraps the
concrete API object, the already-running HTTP request remains unbounded and later
bounded generations can queue behind the same lock indefinitely.

v122 closes that race without changing readiness semantics:

* v121 itself and its complete v311 early v286/v292/v293/v297/v299 convergence
  subset must be ready before v108 is allowed to dispatch Kraken work;
* v312's authenticated same-credential Balance epoch handoff must also be
  installed after that v311 stack and before v108 can launch the first PLATFORM
  Kraken reconciliation worker;
* v108 discovery is patched before its installer can expose dispatch;
* as defense in depth, Kraken discovery is suppressed whenever any prerequisite
  flag is absent, while non-Kraken brokers keep their normal path;
* no synthetic positions, readiness, writer authority, nonce authority, capital,
  risk, execution authority, heartbeat proof, or LIVE_ACTIVE state is fabricated;
* no new import hook is added.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.kraken_position_sync_prereq_v122")
MARKER = "20260816-kraken-position-sync-prereq-v122"
EARLY_HANDOFF_MARKER = "20260831-kraken-position-sync-v312-prereq"
RELEASE_ID = "20260816-runtime-convergence-v122"
_PATCH_ATTR = "_nija_kraken_position_sync_prereq_v122"
_LOCK = threading.RLock()
_INSTALLED = False


def _v121_ready() -> bool:
    return os.environ.get("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", "").strip() == "1"


def _v311_ready() -> bool:
    return os.environ.get("NIJA_KRAKEN_EARLY_READ_CONVERGENCE_V311_READY", "").strip() == "1"


def _v312_ready() -> bool:
    return os.environ.get("NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY", "").strip() == "1"


def _ensure_v121() -> bool:
    try:
        from bot import kraken_read_timeout_v121_patch as v121
    except Exception:
        try:
            import kraken_read_timeout_v121_patch as v121  # type: ignore[import]
        except Exception as exc:
            LOGGER.critical(
                "KRAKEN_POSITION_SYNC_V122_V121_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False
    installer = getattr(v121, "install_import_hook", None) or getattr(v121, "install", None)
    if (
        not callable(installer)
        or installer() is False
        or not _v121_ready()
        or not _v311_ready()
    ):
        LOGGER.critical(
            "KRAKEN_POSITION_SYNC_V122_V121_PREREQ_FAILED marker=%s v121_ready=%s v311_ready=%s "
            "kraken_dispatch_blocked=true trading_fail_closed=true",
            MARKER,
            str(_v121_ready()).lower(),
            str(_v311_ready()).lower(),
        )
        return False
    return True


def _ensure_v312() -> bool:
    """Install the real-Balance handoff before the first v108 Kraken dispatch.

    v121's v311 early convergence has installed v286/v292/v293/v297/v299 by the
    time this helper runs, so v312 can safely wrap those live functions. Failure
    leaves Kraken position dispatch closed rather than granting readiness.
    """
    if not _v311_ready():
        return False
    try:
        from bot import runtime_kraken_balance_epoch_handoff_v312_patch as v312
    except Exception as exc:
        LOGGER.critical(
            "KRAKEN_POSITION_SYNC_V312_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            EARLY_HANDOFF_MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    installer = getattr(v312, "install_import_hook", None) or getattr(v312, "install", None)
    if not callable(installer) or installer() is False or not _v312_ready():
        LOGGER.critical(
            "KRAKEN_POSITION_SYNC_V312_PREREQ_FAILED marker=%s "
            "v311_ready=%s kraken_dispatch_blocked=true readiness_granted=false trading_fail_closed=true",
            EARLY_HANDOFF_MARKER,
            str(_v311_ready()).lower(),
        )
        return False
    LOGGER.critical(
        "KRAKEN_POSITION_SYNC_V312_PREREQ_READY marker=%s ready=true v311_ready=true before_v108_dispatch=true "
        "authenticated_balance_only=true same_credential_only=true credential_proof_required=true "
        "position_success_fabricated=false execution_proof_fabricated=false forced_activation=false "
        "safety_gates_bypassed=false",
        EARLY_HANDOFF_MARKER,
    )
    return True


def _load_v108() -> ModuleType | None:
    try:
        from bot import platform_position_sync_v108_patch as v108
        return v108
    except Exception:
        try:
            import platform_position_sync_v108_patch as v108  # type: ignore[import]
            return v108
        except Exception as exc:
            LOGGER.critical(
                "KRAKEN_POSITION_SYNC_V122_V108_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return None


def _patch_v108(v108: ModuleType) -> bool:
    current = getattr(v108, "_connected_unsynced_platform_brokers", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def connected_unsynced_v122(manager: Any):
        brokers = list(current(manager) or [])
        if _v121_ready() and _v311_ready() and _v312_ready():
            return brokers

        allowed = []
        blocked = 0
        for broker_name, broker in brokers:
            if str(broker_name or "").strip().lower() == "kraken":
                blocked += 1
                continue
            allowed.append((broker_name, broker))

        if blocked:
            LOGGER.critical(
                "KRAKEN_POSITION_SYNC_V122_DISPATCH_BLOCKED marker=%s blocked=%d "
                "reason=kraken_read_prereq_not_ready non_kraken_continues=true "
                "v121_ready=%s v311_ready=%s v312_ready=%s synthetic_empty_snapshot=false trading_fail_closed=true",
                MARKER,
                blocked,
                str(_v121_ready()).lower(),
                str(_v311_ready()).lower(),
                str(_v312_ready()).lower(),
            )
        return allowed

    setattr(connected_unsynced_v122, _PATCH_ATTR, True)
    setattr(connected_unsynced_v122, "__wrapped__", current)
    v108._connected_unsynced_platform_brokers = connected_unsynced_v122
    LOGGER.critical(
        "KRAKEN_POSITION_SYNC_V122_V108_PATCHED marker=%s v121_prerequisite=true v311_prerequisite=true "
        "v312_prerequisite=true patch_before_dispatch_install=true non_kraken_dispatch_unchanged=true "
        "import_hook_added=false",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch") or sys.modules.get(
        "runtime_release_manifest_patch"
    )
    if not isinstance(manifest, ModuleType):
        try:
            import bot.runtime_release_manifest_patch as manifest  # type: ignore[no-redef]
        except Exception:
            return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["kraken_position_sync_prereq_v122"] = "NIJA_KRAKEN_POSITION_SYNC_PREREQ_V122_INSTALLED"
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if not _ensure_v121():
            return False
        if not _ensure_v312():
            return False

        v108 = _load_v108()
        if v108 is None:
            return False
        # Patch discovery before v108 can patch refresh_capital_authority and
        # expose its dispatch path to concurrent runtime refreshes.
        if not _patch_v108(v108):
            return False
        installer = getattr(v108, "install_import_hook", None) or getattr(v108, "install", None)
        if not callable(installer) or installer() is False:
            return False

        os.environ["NIJA_KRAKEN_POSITION_SYNC_PREREQ_V122_INSTALLED"] = "1"
        if not _patch_release_manifest():
            os.environ.pop("NIJA_KRAKEN_POSITION_SYNC_PREREQ_V122_INSTALLED", None)
            return False

        _INSTALLED = True
        LOGGER.critical(
            "KRAKEN_POSITION_SYNC_PREREQ_V122_INSTALLED marker=%s v121_ready=true v311_ready=true v312_ready=true "
            "v312_before_first_kraken_dispatch=true v108_after_v121=true discovery_patched_before_dispatch=true "
            "kraken_dispatch_fail_closed=true import_hook_added=false readiness_granted=false "
            "execution_proof_fabricated=false forced_activation=false safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    """Compatibility installer name; v122 deliberately adds no import hook."""
    return install()


__all__ = [
    "MARKER",
    "EARLY_HANDOFF_MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_v121_ready",
    "_v311_ready",
    "_v312_ready",
    "_ensure_v121",
    "_ensure_v312",
    "_patch_v108",
]
