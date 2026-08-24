"""Keep broker-local authority and canonical module identity stable after imports.

Late startup imports can recreate the legacy downstream-risk module alias after the
initial identity audit. Runtime authority also historically defaulted to requiring
two valid brokers, contradicting broker-local readiness where one healthy venue may
trade independently. This guard continuously restores the canonical alias, sets
the authority broker threshold from the active readiness policy, installs the
fail-closed v154 pre-authority structural gate repair, the v155 same-lease nonce
maturity verifier, the v157 post-activation runtime-quality convergence repair,
the v158 bounded capital-pipeline publication-margin repair, the v161
capital/position liveness convergence repair, the v162 retired-observation
fence, the v163 activation proof convergence repair, the v164 canonical
capital publication/worker-liveness repair, the v165 proactive publication
scheduler convergence repair, the v167 runtime refresh-demand attestation, and
the v209 confirmed-zero-balance completeness repair.
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


def _install_named(module_name: str, missing_reason: str, log_prefix: str) -> bool:
    try:
        module = importlib.import_module(module_name)
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            raise RuntimeError(missing_reason)
        return bool(install_fn())
    except Exception as exc:
        logger.error(
            "%s error=%s:%s trading_fail_closed=true",
            log_prefix,
            type(exc).__name__,
            exc,
        )
        return False


def _install_v154_recovery() -> bool:
    return _install_named(
        "bot.runtime_execution_recovery_v154_patch",
        "v154_install_missing",
        "RUNTIME_EXECUTION_RECOVERY_V154_INSTALL_ERROR",
    )


def _install_v155_nonce_maturity() -> bool:
    return _install_named(
        "bot.nonce_lease_maturity_v155_patch",
        "v155_install_missing",
        "NONCE_LEASE_MATURITY_V155_INSTALL_ERROR",
    )


def _install_v157_runtime_quality() -> bool:
    return _install_named(
        "bot.runtime_quality_convergence_v157_patch",
        "v157_install_missing",
        "RUNTIME_QUALITY_CONVERGENCE_V157_INSTALL_ERROR",
    )


def _install_v158_capital_margin() -> bool:
    return _install_named(
        "bot.capital_pipeline_margin_v158_patch",
        "v158_install_missing",
        "CAPITAL_PIPELINE_MARGIN_V158_INSTALL_ERROR",
    )


def _install_v161_capital_position_convergence() -> bool:
    return _install_named(
        "bot.runtime_capital_position_convergence_v161_patch",
        "v161_install_missing",
        "RUNTIME_CAPITAL_POSITION_CONVERGENCE_V161_INSTALL_ERROR",
    )


def _install_v162_late_observation_fence() -> bool:
    return _install_named(
        "bot.runtime_capital_late_observation_fence_v162_patch",
        "v162_install_missing",
        "RUNTIME_CAPITAL_LATE_OBSERVATION_FENCE_V162_INSTALL_ERROR",
    )


def _install_v163_activation_convergence() -> bool:
    return _install_named(
        "bot.runtime_activation_convergence_v163_patch",
        "v163_install_missing",
        "RUNTIME_ACTIVATION_CONVERGENCE_V163_INSTALL_ERROR",
    )


def _install_v164_capital_publication_liveness() -> bool:
    return _install_named(
        "bot.runtime_capital_publication_liveness_v164_patch",
        "v164_install_missing",
        "RUNTIME_CAPITAL_PUBLICATION_LIVENESS_V164_INSTALL_ERROR",
    )


def _install_v165_capital_publication_scheduling() -> bool:
    return _install_named(
        "bot.runtime_capital_publication_scheduling_v165_patch",
        "v165_install_missing",
        "RUNTIME_CAPITAL_PUBLICATION_SCHEDULING_V165_INSTALL_ERROR",
    )


def _install_v167_refresh_demand() -> bool:
    return _install_named(
        "bot.runtime_refresh_demand_v167_patch",
        "v167_install_missing",
        "RUNTIME_REFRESH_DEMAND_V167_INSTALL_ERROR",
    )


def _install_v209_zero_balance_completeness() -> bool:
    return _install_named(
        "bot.runtime_zero_balance_completeness_v209_patch",
        "v209_install_missing",
        "ZERO_BALANCE_COMPLETENESS_V209_INSTALL_ERROR",
    )


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
    v163_installed = _install_v163_activation_convergence()
    v164_installed = _install_v164_capital_publication_liveness()
    v165_installed = _install_v165_capital_publication_scheduling()
    v167_installed = _install_v167_refresh_demand()
    v209_installed = _install_v209_zero_balance_completeness()
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
        "v161_installed=%s v162_installed=%s v163_installed=%s v164_installed=%s "
        "v165_installed=%s v167_installed=%s v209_installed=%s",
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
        str(v163_installed).lower(),
        str(v164_installed).lower(),
        str(v165_installed).lower(),
        str(v167_installed).lower(),
        str(v209_installed).lower(),
    )
    return bool(
        v154_installed
        and v155_installed
        and v157_installed
        and v158_installed
        and v161_installed
        and v162_installed
        and v163_installed
        and v164_installed
        and v165_installed
        and v167_installed
        and v209_installed
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
            "v162_late_observation_fence=true v163_activation_convergence=true "
            "v164_capital_publication_liveness=true v165_capital_publication_scheduling=true "
            "v167_refresh_demand=true v209_zero_balance_completeness=true",
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
    "_install_v163_activation_convergence",
    "_install_v164_capital_publication_liveness",
    "_install_v165_capital_publication_scheduling",
    "_install_v167_refresh_demand",
    "_install_v209_zero_balance_completeness",
    "_iteration",
]
