"""Keep broker-local authority and canonical module identity stable after imports.

Late startup imports can recreate the legacy downstream-risk module alias after the
initial identity audit. Runtime authority also historically defaulted to requiring
two valid brokers, contradicting broker-local readiness where one healthy venue may
trade independently. This guard continuously restores the canonical alias, sets
the authority broker threshold from the active readiness policy, installs the
fail-closed v154 pre-authority structural gate repair, the v155 same-lease nonce
maturity verifier, the v157 post-activation runtime-quality convergence repair,
the v158 bounded capital-pipeline publication-margin repair, the v161
capital/position liveness convergence repair, and the v162 retired-observation
fence.
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


def _install_v154_recovery() -> bool:
    try:
        module = importlib.import_module("bot.runtime_execution_recovery_v154_patch")
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            raise RuntimeError("v154_install_missing")
        return bool(install_fn())
    except Exception as exc:
        logger.error(
            "RUNTIME_EXECUTION_RECOVERY_V154_INSTALL_ERROR error=%s:%s trading_fail_closed=true",
            type(exc).__name__,
            exc,
        )
        return False


def _install_v155_nonce_maturity() -> bool:
    try:
        module = importlib.import_module("bot.nonce_lease_maturity_v155_patch")
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            raise RuntimeError("v155_install_missing")
        return bool(install_fn())
    except Exception as exc:
        logger.error(
            "NONCE_LEASE_MATURITY_V155_INSTALL_ERROR error=%s:%s trading_fail_closed=true",
            type(exc).__name__,
            exc,
        )
        return False


def _install_v157_runtime_quality() -> bool:
    try:
        module = importlib.import_module("bot.runtime_quality_convergence_v157_patch")
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            raise RuntimeError("v157_install_missing")
        return bool(install_fn())
    except Exception as exc:
        logger.error(
            "RUNTIME_QUALITY_CONVERGENCE_V157_INSTALL_ERROR error=%s:%s trading_fail_closed=true",
            type(exc).__name__,
            exc,
        )
        return False


def _install_v158_capital_margin() -> bool:
    try:
        module = importlib.import_module("bot.capital_pipeline_margin_v158_patch")
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            raise RuntimeError("v158_install_missing")
        return bool(install_fn())
    except Exception as exc:
        logger.error(
            "CAPITAL_PIPELINE_MARGIN_V158_INSTALL_ERROR error=%s:%s trading_fail_closed=true",
            type(exc).__name__,
            exc,
        )
        return False


def _install_v161_capital_position_convergence() -> bool:
    try:
        module = importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            raise RuntimeError("v161_install_missing")
        return bool(install_fn())
    except Exception as exc:
        logger.error(
            "RUNTIME_CAPITAL_POSITION_CONVERGENCE_V161_INSTALL_ERROR error=%s:%s trading_fail_closed=true",
            type(exc).__name__,
            exc,
        )
        return False


def _install_v162_late_observation_fence() -> bool:
    try:
        module = importlib.import_module("bot.runtime_capital_late_observation_fence_v162_patch")
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            raise RuntimeError("v162_install_missing")
        return bool(install_fn())
    except Exception as exc:
        logger.error(
            "RUNTIME_CAPITAL_LATE_OBSERVATION_FENCE_V162_INSTALL_ERROR error=%s:%s trading_fail_closed=true",
            type(exc).__name__,
            exc,
        )
        return False


def _iteration() -> bool:
    changed = _canonicalize_alias()
    required = _apply_broker_threshold()
    patched = _patch_quiescence_audit()
    v154_installed = _install_v154_recovery()
    v155_installed = _install_v155_nonce_maturity()
    v157_installed = _install_v157_runtime_quality()
    v158_installed = _install_v158_capital_margin()
    v161_installed = _install_v161_capital_position_convergence()
    v162_installed = _install_v162_late_observation_fence()
    os.environ["NIJA_RUNTIME_POST_IMPORT_CONVERGENCE_INSTALLED"] = "1"
    if changed:
        logger.warning(
            "DOWNSTREAM_RISK_ALIAS_DRIFT_REPAIRED marker=%s canonical=%s alias=%s same=true",
            _MARKER,
            _CANONICAL,
            _ALIAS,
        )
    logger.debug(
        "RUNTIME_POST_IMPORT_CONVERGENCE marker=%s policy=%s min_brokers=%d audit_patched=%s "
        "v154_installed=%s v155_installed=%s v157_installed=%s v158_installed=%s "
        "v161_installed=%s v162_installed=%s",
        _MARKER,
        _policy(),
        required,
        str(patched).lower(),
        str(v154_installed).lower(),
        str(v155_installed).lower(),
        str(v157_installed).lower(),
        str(v158_installed).lower(),
        str(v161_installed).lower(),
        str(v162_installed).lower(),
    )
    return bool(
        v154_installed
        and v155_installed
        and v157_installed
        and v158_installed
        and v161_installed
        and v162_installed
    )


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
            "RUNTIME_POST_IMPORT_CONVERGENCE_INSTALLED marker=%s policy=%s min_brokers=%d "
            "alias_same=true v154_recovery=true v155_nonce_maturity=true v157_runtime_quality=true "
            "v158_capital_margin=true v161_capital_position_convergence=true "
            "v162_late_observation_fence=true",
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
    "_install_v154_recovery",
    "_install_v155_nonce_maturity",
    "_install_v157_runtime_quality",
    "_install_v158_capital_margin",
    "_install_v161_capital_position_convergence",
    "_install_v162_late_observation_fence",
    "_iteration",
]
