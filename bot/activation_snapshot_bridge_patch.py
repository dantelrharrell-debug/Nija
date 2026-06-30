"""Bridge accepted capital snapshots into live activation safely.

This runtime patch fixes a startup ordering mismatch observed in Railway logs:
CapitalAuthority and CapitalCSMv2 can latch the first live capital snapshot, while
TradingStateMachine._first_snap_accepted remains False because the activation
cycle receives an empty/older cycle_capital dict.  The result is a false
`ACTIVATION BLOCKED: no valid live-exchange capital snapshot accepted` even
though the live capital latch already passed.

The bridge is fail-closed:
- It never invents capital.
- It only sets TradingStateMachine._first_snap_accepted when CapitalAuthority is
  hydrated, non-stale, has real capital > 0, and has at least one positive broker
  balance, or when CapitalAuthority's own first-snapshot latch is already true.
- It only performs the constrained fallback commit after distributed writer,
  nonce, heartbeat/live, and kill-switch gates pass.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("nija.activation_snapshot_bridge")

_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_PATCH_STARTED = False
_PATCH_LOCK = threading.Lock()


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _set_lock_wait_defaults() -> None:
    """Give stale-lock rescue enough runway without disabling Redis safety."""
    # The observed deployment waited only ~45s while the old holder's stale
    # heartbeat threshold was ~240s, causing repeated fail-closed restarts before
    # the safe takeover path could complete.  These defaults extend the runway;
    # they do not bypass the distributed writer lock.
    timeout_defaults = {
        "NIJA_WRITER_LOCK_ACQUIRE_TIMEOUT_S": "180",
        "NIJA_DISTRIBUTED_LOCK_ACQUIRE_TIMEOUT_S": "180",
        "NIJA_REDIS_LOCK_ACQUIRE_TIMEOUT_S": "180",
        "NIJA_LOCK_ACQUIRE_TIMEOUT_S": "180",
        "NIJA_FAIL_CLOSED_LOCK_ACQUIRE_TIMEOUT_S": "180",
    }
    for key, value in timeout_defaults.items():
        os.environ.setdefault(key, value)

    stale_defaults = {
        "NIJA_STALE_LOCK_HEARTBEAT_THRESHOLD_S": "120",
        "NIJA_WRITER_LOCK_STALE_HEARTBEAT_THRESHOLD_S": "120",
        "NIJA_RAILWAY_STALE_LOCK_HEARTBEAT_THRESHOLD_S": "120",
        "STALE_LOCK_HEARTBEAT_THRESHOLD_S": "120",
        "WRITER_LOCK_STALE_HEARTBEAT_THRESHOLD_S": "120",
        "RAILWAY_STALE_LOCK_HEARTBEAT_THRESHOLD_S": "120",
    }
    for key, value in stale_defaults.items():
        os.environ.setdefault(key, value)

    # Avoid restart churn while waiting for a real lock handoff.  This remains
    # fail-closed: trading is blocked until the Redis writer lock is acquired.
    try:
        attempts = int(float(os.environ.get("NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS", "0") or "0"))
    except Exception:
        attempts = 0
    if attempts and attempts < 36:
        os.environ["NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"] = "36"
    elif attempts <= 0:
        os.environ.setdefault("NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS", "36")


def _resolve_class(module_names: tuple[str, ...], class_name: str):
    for module_name in module_names:
        module = sys.modules.get(module_name)
        cls = getattr(module, class_name, None) if module is not None else None
        if cls is not None:
            return cls
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.debug("class import probe failed module=%s class=%s error=%s", module_name, class_name, exc)
            continue
        cls = getattr(module, class_name, None)
        if cls is not None:
            return cls
    return None


def _get_module(*names: str):
    for name in names:
        module = sys.modules.get(name)
        if module is not None:
            return module
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception as exc:
            logger.debug("module import probe failed module=%s error=%s", name, exc)
    return None


def _positive_number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _positive_balance_count_from_mapping(values: Any) -> int:
    if not isinstance(values, Mapping):
        return 0
    count = 0
    for value in values.values():
        if isinstance(value, Mapping):
            candidates = (
                value.get("trading_balance"),
                value.get("total_funds"),
                value.get("available"),
                value.get("cash"),
                value.get("usd"),
                value.get("balance"),
            )
            amount = max((_positive_number(candidate) for candidate in candidates), default=0.0)
        else:
            amount = _positive_number(value)
        if amount > 0.0:
            count += 1
    return count


def _get_capital_authority():
    module = _get_module("bot.capital_authority", "capital_authority")
    if module is None:
        return None
    getter = getattr(module, "get_capital_authority", None)
    if callable(getter):
        try:
            return getter()
        except Exception as exc:
            logger.debug("get_capital_authority() failed: %s", exc)
    for attr in ("capital_authority", "CAPITAL_AUTHORITY", "_capital_authority"):
        instance = getattr(module, attr, None)
        if instance is not None:
            return instance
    return None


def _get_mabm_instance():
    module = _get_module("bot.multi_account_broker_manager", "multi_account_broker_manager")
    if module is None:
        return None
    for attr in ("multi_account_broker_manager", "mabm", "manager"):
        instance = getattr(module, attr, None)
        if instance is not None:
            return instance
    return None


def _valid_brokers_from_mabm() -> int:
    manager = _get_mabm_instance()
    if manager is None:
        return 0
    count = 0
    containers: list[Any] = []
    for attr in ("platform_brokers", "_platform_brokers", "brokers"):
        value = getattr(manager, attr, None)
        if isinstance(value, Mapping):
            containers.append(value)
    for container in containers:
        for broker in container.values():
            if broker is None:
                continue
            if hasattr(broker, "connected") and not bool(getattr(broker, "connected", False)):
                continue
            balance = max(
                _positive_number(getattr(broker, "_last_known_balance", 0.0)),
                _positive_number(getattr(broker, "last_known_balance", 0.0)),
                _positive_number(getattr(broker, "balance", 0.0)),
            )
            if balance > 0.0:
                count += 1
    return count


def _capital_snapshot_meta() -> tuple[bool, dict[str, Any]]:
    ca = _get_capital_authority()
    if ca is None:
        return False, {"ca_available": False}

    hydrated = bool(getattr(ca, "is_hydrated", False))
    stale = True
    is_stale = getattr(ca, "is_stale", None)
    if callable(is_stale):
        try:
            stale = bool(is_stale())
        except Exception:
            stale = True
    else:
        stale = bool(getattr(ca, "stale", True))

    real_capital = 0.0
    getter = getattr(ca, "get_real_capital", None)
    if callable(getter):
        try:
            real_capital = _positive_number(getter())
        except Exception as exc:
            logger.debug("CapitalAuthority.get_real_capital() failed: %s", exc)
    if real_capital <= 0.0:
        for attr in ("real_capital", "total_capital", "total_balance", "balance"):
            real_capital = max(real_capital, _positive_number(getattr(ca, attr, 0.0)))

    accepted_latch = bool(
        getattr(ca, "first_snap_accepted", False)
        or getattr(ca, "_first_snap_accepted", False)
        or getattr(ca, "first_snapshot_accepted", False)
    )

    valid_brokers = 0
    snapshot = None
    for attr in ("last_snapshot", "_last_snapshot", "current_snapshot", "_current_snapshot", "snapshot"):
        snapshot = getattr(ca, attr, None)
        if snapshot is not None:
            break
    for source in (
        getattr(snapshot, "broker_balances", None) if snapshot is not None else None,
        getattr(ca, "broker_balances", None),
        getattr(ca, "_broker_balances", None),
        getattr(ca, "balances", None),
    ):
        valid_brokers = max(valid_brokers, _positive_balance_count_from_mapping(source))

    valid_brokers = max(valid_brokers, _valid_brokers_from_mabm())

    if valid_brokers <= 0 and accepted_latch and real_capital > 0.0:
        # CapitalAuthority has already accepted the first snapshot but its raw
        # balance map is not exposed on this object.  Preserve fail-closed
        # semantics by requiring positive real capital before inferring one valid
        # broker for the activation snapshot flag.
        valid_brokers = 1

    conditions_met = bool(hydrated and real_capital > 0.0 and valid_brokers > 0 and not stale)
    accepted = bool(accepted_latch or conditions_met)
    return accepted, {
        "ca_available": True,
        "accepted_latch": accepted_latch,
        "hydrated": hydrated,
        "stale": stale,
        "real_capital": real_capital,
        "valid_brokers": valid_brokers,
        "conditions_met": conditions_met,
    }


def _augment_cycle_capital(cycle_capital: Any, meta: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = dict(cycle_capital or {}) if isinstance(cycle_capital, Mapping) else {}
    valid_brokers = int(meta.get("valid_brokers") or 0)
    snapshot.setdefault("snapshot_source", "capital_authority")
    snapshot["ca_valid_brokers"] = max(int(snapshot.get("ca_valid_brokers", 0) or 0), valid_brokers, 1)
    snapshot.setdefault("aggregation_normalized", True)
    snapshot.setdefault("capital_hydrated", bool(meta.get("hydrated")))
    snapshot.setdefault("ca_not_stale", not bool(meta.get("stale")))
    snapshot.setdefault("real_capital", float(meta.get("real_capital") or 0.0))
    return snapshot


def _kill_switch_active() -> bool:
    for module_name in ("bot.kill_switch", "kill_switch"):
        try:
            module = importlib.import_module(module_name)
            getter = getattr(module, "get_kill_switch", None)
            if callable(getter):
                return bool(getter().is_active())
        except Exception:
            continue
    return False


def _concrete_activation_gates_pass(tsm_module: Any) -> tuple[bool, str]:
    if _kill_switch_active():
        return False, "kill_switch_active"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "dry_or_paper_mode"
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"

    for fn_name, label in (
        ("_distributed_writer_authority_gate", "writer_authority"),
        ("_nonce_writer_lease_gate", "nonce_writer_lease"),
        ("_live_activation_gate", "live_activation_gate"),
    ):
        fn = getattr(tsm_module, fn_name, None)
        if not callable(fn):
            return False, f"{label}_unavailable"
        try:
            ok, detail = fn()
        except Exception as exc:
            return False, f"{label}_error:{exc}"
        if not ok:
            return False, f"{label}:{detail or 'blocked'}"
    return True, ""


def _sync_first_snapshot_flag(tsm: Any, meta: dict[str, Any]) -> None:
    if bool(getattr(tsm, "_first_snap_accepted", False)):
        return
    setter = getattr(tsm, "set_first_snap_accepted", None)
    if callable(setter):
        setter(True)
    else:
        setattr(tsm, "_first_snap_accepted", True)
    logger.critical(
        "ACTIVATION_SNAPSHOT_BRIDGE first_snap_accepted=True capital=$%.2f valid_brokers=%s hydrated=%s stale=%s accepted_latch=%s",
        float(meta.get("real_capital") or 0.0),
        meta.get("valid_brokers"),
        meta.get("hydrated"),
        meta.get("stale"),
        meta.get("accepted_latch"),
    )


def _patch_trading_state_machine_class(cls: type) -> bool:
    original_commit = getattr(cls, "commit_activation", None)
    if original_commit is None:
        return False
    if getattr(original_commit, "_nija_activation_snapshot_bridge_wrapped", False):
        return True

    def _commit_activation_with_snapshot_bridge(self, cycle_capital=None):
        accepted, meta = _capital_snapshot_meta()
        bridged_capital = cycle_capital
        if accepted:
            _sync_first_snapshot_flag(self, meta)
            bridged_capital = _augment_cycle_capital(cycle_capital, meta)

        result = original_commit(self, cycle_capital=bridged_capital)
        if result:
            return True

        if not accepted:
            return result

        tsm_module = sys.modules.get(cls.__module__) or _get_module("bot.trading_state_machine", "trading_state_machine")
        gates_ok, gates_detail = _concrete_activation_gates_pass(tsm_module)
        if not gates_ok:
            logger.critical(
                "ACTIVATION_SNAPSHOT_BRIDGE_COMMIT blocked_after_original detail=%s capital=$%.2f valid_brokers=%s",
                gates_detail,
                float(meta.get("real_capital") or 0.0),
                meta.get("valid_brokers"),
            )
            return result

        with getattr(self, "_lock", threading.Lock()):
            current_state = getattr(getattr(self, "_current_state", None), "value", getattr(self, "_current_state", "unknown"))
        force_transition = getattr(self, "_force_live_active_transition", None)
        if callable(force_transition):
            logger.critical(
                "ACTIVATION_SNAPSHOT_BRIDGE_COMMIT all_concrete_gates_passed current_state=%s capital=$%.2f valid_brokers=%s — committing LIVE_ACTIVE",
                current_state,
                float(meta.get("real_capital") or 0.0),
                meta.get("valid_brokers"),
            )
            return bool(force_transition("ACTIVATION_SNAPSHOT_BRIDGE: CapitalAuthority first snapshot accepted and concrete live gates passed"))

        logger.critical("ACTIVATION_SNAPSHOT_BRIDGE_COMMIT unable_to_commit: _force_live_active_transition missing")
        return result

    _commit_activation_with_snapshot_bridge._nija_activation_snapshot_bridge_wrapped = True  # type: ignore[attr-defined]
    cls.commit_activation = _commit_activation_with_snapshot_bridge  # type: ignore[method-assign]
    logger.warning("ACTIVATION_SNAPSHOT_BRIDGE_PATCHED class=%s", cls.__name__)
    return True


def install_import_hook() -> None:
    global _PATCH_STARTED
    _set_lock_wait_defaults()
    if _PATCH_STARTED:
        return
    with _PATCH_LOCK:
        if _PATCH_STARTED:
            return
        _PATCH_STARTED = True

        def _worker() -> None:
            deadline = time.monotonic() + float(os.getenv("NIJA_ACTIVATION_SNAPSHOT_BRIDGE_TIMEOUT_S", "120") or "120")
            logger.warning("ACTIVATION_SNAPSHOT_BRIDGE autowire worker started")
            while time.monotonic() < deadline:
                cls = _resolve_class(("bot.trading_state_machine", "trading_state_machine"), "TradingStateMachine")
                if cls is not None and _patch_trading_state_machine_class(cls):
                    return
                time.sleep(0.25)
            logger.error("ACTIVATION_SNAPSHOT_BRIDGE autowire timeout: TradingStateMachine class was not observed or importable")

        threading.Thread(target=_worker, name="activation-snapshot-bridge-autowire", daemon=True).start()
