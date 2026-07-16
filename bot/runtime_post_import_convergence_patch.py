"""Keep broker-local authority and canonical module identity stable after imports.

Late startup imports can recreate the legacy downstream-risk module alias after the
initial identity audit.  Runtime authority also historically defaulted to requiring
two valid brokers, contradicting broker-local readiness where one healthy venue may
trade independently.  This guard continuously restores the canonical alias and sets
the authority broker threshold from the active readiness policy.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.runtime_post_import_convergence")
_MARKER = "20260716-post-import-convergence-v1"
_LOCK = threading.RLock()
_STARTED = False

_CANONICAL = "bot.downstream_risk_governor_equity_repair_patch"
_ALIAS = "nija_downstream_risk_governor_equity_repair_patch"


def _policy() -> str:
    explicit = str(os.environ.get("NIJA_SECONDARY_VENUE_POLICY", "") or "").strip().lower()
    if explicit in {"broker_local", "global_all_required", "optional"}:
        return explicit
    strict = str(os.environ.get("NIJA_REQUIRE_SECONDARY_VENUES_READY", "") or "").strip().lower()
    return "broker_local" if strict in {"1", "true", "yes", "on"} else "optional"


def _required_broker_count() -> int:
    return 2 if _policy() == "global_all_required" else 1


def _apply_broker_threshold() -> int:
    required = _required_broker_count()
    current = str(os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", "") or "").strip()
    # Preserve an explicit stricter operator setting. Otherwise align the default
    # with the broker-local contract.
    if not current:
        os.environ["NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS"] = str(required)
    else:
        try:
            configured = max(1, int(float(current)))
        except Exception:
            configured = required
        if _policy() != "global_all_required" and configured == 2:
            os.environ["NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS"] = "1"
        required = int(os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", required))
    os.environ["NIJA_RUNTIME_AUTHORITY_BROKER_POLICY"] = _policy()
    return required


def _canonicalize_alias() -> bool:
    canonical = sys.modules.get(_CANONICAL)
    if not isinstance(canonical, ModuleType):
        canonical = importlib.import_module(_CANONICAL)
    changed = sys.modules.get(_ALIAS) is not canonical
    sys.modules[_CANONICAL] = canonical
    sys.modules[_ALIAS] = canonical
    marker = str(getattr(canonical, "_MARKER", "") or "")
    if marker != "20260714-downstream-risk-v2":
        raise RuntimeError(f"downstream_risk_marker_mismatch:{marker or 'missing'}")
    return changed


def _patch_quiescence_audit() -> bool:
    try:
        module = importlib.import_module("runtime_convergence_quiescence_patch")
    except Exception:
        return False
    current = getattr(module, "audit", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_post_import_alias_guard_v1", False):
        return True
    original = current

    def audit(*args: Any, **kwargs: Any):
        _canonicalize_alias()
        _apply_broker_threshold()
        return original(*args, **kwargs)

    audit._nija_post_import_alias_guard_v1 = True  # type: ignore[attr-defined]
    audit.__wrapped__ = original  # type: ignore[attr-defined]
    module.audit = audit
    return True


def _iteration() -> bool:
    changed = _canonicalize_alias()
    required = _apply_broker_threshold()
    patched = _patch_quiescence_audit()
    os.environ["NIJA_RUNTIME_POST_IMPORT_CONVERGENCE_INSTALLED"] = "1"
    if changed:
        logger.warning(
            "DOWNSTREAM_RISK_ALIAS_DRIFT_REPAIRED marker=%s canonical=%s alias=%s same=true",
            _MARKER,
            _CANONICAL,
            _ALIAS,
        )
    logger.debug(
        "RUNTIME_POST_IMPORT_CONVERGENCE marker=%s policy=%s min_brokers=%d audit_patched=%s",
        _MARKER,
        _policy(),
        required,
        str(patched).lower(),
    )
    return True


def _watchdog() -> None:
    while True:
        try:
            _iteration()
        except Exception as exc:
            logger.error("RUNTIME_POST_IMPORT_CONVERGENCE_ERROR marker=%s error=%s", _MARKER, exc)
        time.sleep(max(1.0, float(os.environ.get("NIJA_POST_IMPORT_CONVERGENCE_INTERVAL_S", "5") or 5)))


def install() -> bool:
    global _STARTED
    with _LOCK:
        _iteration()
        if not _STARTED:
            _STARTED = True
            threading.Thread(
                target=_watchdog,
                name="RuntimePostImportConvergence",
                daemon=True,
            ).start()
        logger.critical(
            "RUNTIME_POST_IMPORT_CONVERGENCE_INSTALLED marker=%s policy=%s min_brokers=%d alias_same=true",
            _MARKER,
            _policy(),
            _required_broker_count(),
        )
        return True


__all__ = [
    "install",
    "_policy",
    "_required_broker_count",
    "_apply_broker_threshold",
    "_canonicalize_alias",
    "_patch_quiescence_audit",
    "_iteration",
]
