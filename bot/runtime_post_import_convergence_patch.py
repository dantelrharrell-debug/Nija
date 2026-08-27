"""Keep broker-local authority and canonical module identity stable after imports."""
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
_MARKER = "20260826-post-import-convergence-v242"
_LOCK = threading.RLock()
_STARTED = False
_LAST_PREREQUISITES: dict[str, bool] = {}
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
    audit._nija_post_import_alias_guard_v1 = True
    audit.__wrapped__ = original
    module.audit = audit
    return True


def _install_named(module_name: str, missing_reason: str, log_prefix: str) -> bool:
    try:
        module = importlib.import_module(module_name)
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            install_fn = getattr(module, "install_import_hook", None)
        if not callable(install_fn):
            raise RuntimeError(missing_reason)
        return bool(install_fn())
    except Exception as exc:
        logger.error("%s error=%s:%s trading_fail_closed=true", log_prefix, type(exc).__name__, exc)
        return False


def _install_v154_recovery(): return _install_named("bot.runtime_execution_recovery_v154_patch", "v154_install_missing", "RUNTIME_EXECUTION_RECOVERY_V154_INSTALL_ERROR")
def _install_v155_nonce_maturity(): return _install_named("bot.nonce_lease_maturity_v155_patch", "v155_install_missing", "NONCE_LEASE_MATURITY_V155_INSTALL_ERROR")
def _install_v157_runtime_quality(): return _install_named("bot.runtime_quality_convergence_v157_patch", "v157_install_missing", "RUNTIME_QUALITY_CONVERGENCE_V157_INSTALL_ERROR")
def _install_v158_capital_margin(): return _install_named("bot.capital_pipeline_margin_v158_patch", "v158_install_missing", "CAPITAL_PIPELINE_MARGIN_V158_INSTALL_ERROR")
def _install_v161_capital_position_convergence(): return _install_named("bot.runtime_capital_position_convergence_v161_patch", "v161_install_missing", "RUNTIME_CAPITAL_POSITION_CONVERGENCE_V161_INSTALL_ERROR")
def _install_v162_late_observation_fence(): return _install_named("bot.runtime_capital_late_observation_fence_v162_patch", "v162_install_missing", "RUNTIME_CAPITAL_LATE_OBSERVATION_FENCE_V162_INSTALL_ERROR")
def _install_v163_activation_convergence(): return _install_named("bot.runtime_activation_convergence_v163_patch", "v163_install_missing", "RUNTIME_ACTIVATION_CONVERGENCE_V163_INSTALL_ERROR")
def _install_v164_capital_publication_liveness(): return _install_named("bot.runtime_capital_publication_liveness_v164_patch", "v164_install_missing", "RUNTIME_CAPITAL_PUBLICATION_LIVENESS_V164_INSTALL_ERROR")
def _install_v165_capital_publication_scheduling(): return _install_named("bot.runtime_capital_publication_scheduling_v165_patch", "v165_install_missing", "RUNTIME_CAPITAL_PUBLICATION_SCHEDULING_V165_INSTALL_ERROR")
def _install_v167_refresh_demand(): return _install_named("bot.runtime_refresh_demand_v167_patch", "v167_install_missing", "RUNTIME_REFRESH_DEMAND_V167_INSTALL_ERROR")
def _install_v209_zero_balance_completeness(): return _install_named("bot.runtime_zero_balance_completeness_v209_patch", "v209_install_missing", "ZERO_BALANCE_COMPLETENESS_V209_INSTALL_ERROR")
def _install_v224_exchange_reject_provenance(): return _install_named("bot.exchange_reject_provenance_v224_patch", "v224_install_missing", "EXCHANGE_REJECT_PROVENANCE_V224_INSTALL_ERROR")
def _install_v228_exchange_reject_dispatch_provenance(): return _install_named("bot.exchange_reject_dispatch_provenance_v228_patch", "v228_install_missing", "EXCHANGE_REJECT_DISPATCH_PROVENANCE_V228_INSTALL_ERROR")
def _install_v229_capital_provenance_alias(): return _install_named("bot.runtime_capital_provenance_alias_convergence_v229_patch", "v229_install_missing", "RUNTIME_CAPITAL_PROVENANCE_ALIAS_V229_INSTALL_ERROR")
def _install_v232_heartbeat_execution_quality(): return _install_named("bot.runtime_heartbeat_execution_quality_v232_patch", "v232_install_missing", "HEARTBEAT_EXECUTION_QUALITY_V232_INSTALL_ERROR")
def _install_v233_heartbeat_terminal_authority(): return _install_named("bot.runtime_heartbeat_terminal_authority_v233_patch", "v233_install_missing", "HEARTBEAT_TERMINAL_AUTHORITY_V233_INSTALL_ERROR")
def _install_v234_kraken_read_lock_recovery(): return _install_named("bot.runtime_kraken_read_lock_recovery_v234_patch", "v234_install_missing", "KRAKEN_READ_LOCK_RECOVERY_V234_INSTALL_ERROR")
def _install_v236_heartbeat_final_submit(): return _install_named("bot.runtime_heartbeat_final_submit_v236_patch", "v236_install_missing", "HEARTBEAT_FINAL_SUBMIT_V236_INSTALL_ERROR")
def _install_v237_kraken_local_contention_health(): return _install_named("bot.runtime_kraken_local_contention_health_v237_patch", "v237_install_missing", "KRAKEN_LOCAL_CONTENTION_V237_INSTALL_ERROR")
def _install_v238_heartbeat_marker_convergence(): return _install_named("bot.runtime_heartbeat_marker_convergence_v238_patch", "v238_install_missing", "HEARTBEAT_MARKER_CONVERGENCE_V238_INSTALL_ERROR")
def _install_v239_all_account_profit_targets(): return _install_named("bot.runtime_all_account_profit_targets_v239_patch", "v239_install_missing", "ALL_ACCOUNT_PROFIT_TARGETS_V239_INSTALL_ERROR")
def _install_v240_heartbeat_terminal_lifecycle(): return _install_named("bot.runtime_heartbeat_terminal_lifecycle_v240_patch", "v240_install_missing", "HEARTBEAT_TERMINAL_LIFECYCLE_V240_INSTALL_ERROR")
def _install_v241_kraken_local_contention_alias(): return _install_named("bot.runtime_kraken_local_contention_alias_v241_patch", "v241_install_missing", "KRAKEN_LOCAL_CONTENTION_V241_INSTALL_ERROR")
def _install_v242_kraken_local_contention_instance(): return _install_named("bot.runtime_kraken_local_contention_instance_v242_patch", "v242_install_missing", "KRAKEN_LOCAL_CONTENTION_V242_INSTALL_ERROR")


def _iteration() -> bool:
    changed = _canonicalize_alias()
    required = _apply_broker_threshold()
    patched = _patch_quiescence_audit()
    v224 = _install_v224_exchange_reject_provenance()
    v228 = _install_v228_exchange_reject_dispatch_provenance()
    v232 = _install_v232_heartbeat_execution_quality()
    v233 = _install_v233_heartbeat_terminal_authority()
    v234 = _install_v234_kraken_read_lock_recovery()
    v236 = _install_v236_heartbeat_final_submit()
    v237 = _install_v237_kraken_local_contention_health()
    v238 = _install_v238_heartbeat_marker_convergence()
    v239 = _install_v239_all_account_profit_targets()
    v240 = _install_v240_heartbeat_terminal_lifecycle()
    v241 = _install_v241_kraken_local_contention_alias()
    v242 = _install_v242_kraken_local_contention_instance()
    prerequisites = {
        "audit_patched": patched,
        "v154_execution_recovery": _install_v154_recovery(),
        "v155_nonce_maturity": _install_v155_nonce_maturity(),
        "v157_runtime_quality": _install_v157_runtime_quality(),
        "v158_capital_margin": _install_v158_capital_margin(),
        "v161_capital_position": _install_v161_capital_position_convergence(),
        "v162_late_observation_fence": _install_v162_late_observation_fence(),
        "v163_activation_convergence": _install_v163_activation_convergence(),
        "v164_capital_publication_liveness": _install_v164_capital_publication_liveness(),
        "v165_capital_publication_scheduling": _install_v165_capital_publication_scheduling(),
        "v167_refresh_demand": _install_v167_refresh_demand(),
        "v209_zero_balance_completeness": _install_v209_zero_balance_completeness(),
        "v224_exchange_reject_provenance": v224,
        "v228_exchange_reject_dispatch_provenance": v228,
        "v229_capital_provenance_alias": _install_v229_capital_provenance_alias(),
        "v232_heartbeat_execution_quality": v232,
        "v233_heartbeat_terminal_authority": v233,
        "v234_kraken_read_lock_recovery": v234,
        "v236_heartbeat_final_submit": v236,
        "v237_kraken_contention_health": v237,
        "v238_heartbeat_marker_convergence": v238,
        "v239_all_account_profit_targets": v239,
        "v240_heartbeat_terminal_lifecycle": v240,
        "v241_kraken_contention_alias": v241,
        "v242_kraken_contention_instance": v242,
    }
    global _LAST_PREREQUISITES
    _LAST_PREREQUISITES = dict(prerequisites)
    failed = tuple(name for name, value in prerequisites.items() if not value)
    os.environ["NIJA_RUNTIME_POST_IMPORT_CONVERGENCE_INSTALLED"] = "1"
    if changed:
        logger.warning("DOWNSTREAM_RISK_ALIAS_DRIFT_REPAIRED marker=%s canonical=%s alias=%s same=true", _MARKER, _CANONICAL, _ALIAS)
    logger.warning(
        "RUNTIME_POST_IMPORT_CONVERGENCE marker=%s policy=%s min_brokers=%d ready=%s "
        "failed_prerequisites=%s prerequisites=%s",
        _MARKER, _policy(), required, str(not failed).lower(),
        ",".join(failed) or "none",
        ",".join(f"{name}={str(value).lower()}" for name, value in prerequisites.items()),
    )
    return not failed


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
        ready = _iteration()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="RuntimePostImportConvergence", daemon=True).start()
        failed = tuple(name for name, value in _LAST_PREREQUISITES.items() if not value)
        logger.critical(
            "RUNTIME_POST_IMPORT_CONVERGENCE_INSTALLED marker=%s policy=%s min_brokers=%d "
            "alias_same=true ready=%s failed_prerequisites=%s",
            _MARKER, _policy(), _required_broker_count(), str(ready).lower(),
            ",".join(failed) or "none",
        )
        return ready


__all__ = ["install", "_policy", "_required_broker_count", "_apply_broker_threshold", "_canonicalize_alias", "_patch_quiescence_audit", "_install_v233_heartbeat_terminal_authority", "_install_v234_kraken_read_lock_recovery", "_install_v236_heartbeat_final_submit", "_install_v237_kraken_local_contention_health", "_install_v238_heartbeat_marker_convergence", "_install_v239_all_account_profit_targets", "_install_v240_heartbeat_terminal_lifecycle", "_install_v241_kraken_local_contention_alias", "_install_v242_kraken_local_contention_instance", "_iteration", "_LAST_PREREQUISITES"]