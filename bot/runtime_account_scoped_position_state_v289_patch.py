"""Account-scope NIJA position and entry-price persistence (v289).

Production evidence on 2026-08-30 showed the same ORCA quantity in Coinbase and
OKX local trackers while their authoritative broker snapshots contained no ORCA.
The real ORCA position belonged to a Kraken user account. Broker objects were
instantiating independent PositionTracker objects against the same
``data/positions.json`` file and PositionTracker also used one process-wide
EntryPriceStore keyed only by symbol.

v289 prevents future cross-account persistence and repairs already-created
broker trackers without fabricating positions or cost basis:

* broker-created PositionTrackers are redirected to one file per account before
  their legacy shared file is loaded whenever constructor context is available;
* already-created trackers are rebound to an account-scoped file and entry-price
  store without replacing the tracker object referenced by exit supervisors;
* startup reconciliation is forced to use that broker's scoped EntryPriceStore;
* the legacy process-wide EntryPriceStore repair thread is stopped so one
  broker cannot overwrite another account's same-symbol basis;
* stale tracker symbols are removed only when v285 supplies a current successful
  authoritative snapshot for that exact account;
* no shared legacy position file is copied into a new account namespace as
  authoritative truth.

All reconciliation, cost-basis, protective-exit, writer, nonce, capital, risk,
kill-switch, order and fill gates remain unchanged. New entries remain fail
closed until canonical position readiness naturally recovers.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import threading
from functools import wraps
from types import MethodType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_account_scoped_position_state_v289")
MARKER = "20260830-account-scoped-position-state-v289"
RELEASE_ID = "20260830-runtime-convergence-v289"
_READY_FLAG = "NIJA_RUNTIME_ACCOUNT_SCOPED_POSITION_STATE_V289_READY"
_PATCH_ATTR = "_nija_account_scoped_position_state_v289"
_LOCK = threading.RLock()
_THREAD_LOCAL = threading.local()
_SCOPED_STORES: dict[str, Any] = {}
_MONITOR_STOP = threading.Event()
_MONITOR_THREAD: threading.Thread | None = None
_LAST_SIGNATURE = ""


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower())
    return text.strip("._-") or "unknown"


def _scope(account_type: Any, user_id: Any, broker_type: Any) -> str:
    account = _label(account_type) or "platform"
    venue = _label(broker_type) or "unknown"
    if account == "user":
        return f"user__{_slug(user_id)}__{_slug(venue)}"
    return f"platform__{_slug(venue)}"


def _broker_scope(broker: Any) -> str:
    return _scope(
        getattr(broker, "account_type", "platform"),
        getattr(broker, "user_id", None),
        getattr(broker, "broker_type", type(broker).__name__.replace("Broker", "")),
    )


def _position_dir() -> str:
    return os.environ.get("NIJA_ACCOUNT_POSITION_STATE_DIR", os.path.join("data", "positions")) or os.path.join("data", "positions")


def _entry_dir() -> str:
    return os.environ.get("NIJA_ACCOUNT_ENTRY_PRICE_STATE_DIR", os.path.join("data", "entry_prices")) or os.path.join("data", "entry_prices")


def _position_file(scope: str) -> str:
    return os.path.abspath(os.path.join(_position_dir(), f"{_slug(scope)}.json"))


def _entry_file(scope: str) -> str:
    return os.path.abspath(os.path.join(_entry_dir(), f"{_slug(scope)}.json"))


def _scoped_store(scope: str) -> Any:
    with _LOCK:
        store = _SCOPED_STORES.get(scope)
        if store is not None:
            return store
        module = importlib.import_module("bot.entry_price_store")
        cls = getattr(module, "EntryPriceStore")
        store = cls(data_file=_entry_file(scope))
        _SCOPED_STORES[scope] = store
        return store


def _bind_tracker_instance(tracker: Any, scope: str) -> bool:
    if tracker is None:
        return False
    try:
        current_scope = str(getattr(tracker, "_nija_account_scope_v289", "") or "")
        target_file = _position_file(scope)
        store = _scoped_store(scope)
        tracker.storage_file = target_file
        tracker._eps = store
        setattr(tracker, "_nija_account_scope_v289", scope)
        setattr(tracker, "_nija_account_entry_store_v289", store)

        if not bool(getattr(tracker, "_nija_scoped_methods_v289", False)):
            def _persist_entry_price(self: Any, symbol: str, price: float, quantity: float, source: str) -> None:
                try:
                    verifier = getattr(self, "_source_verified", None)
                    if price <= 0 or not callable(verifier) or not verifier(source, price):
                        return
                    scoped = getattr(self, "_nija_account_entry_store_v289", None)
                    if scoped is not None:
                        scoped.save(symbol, price, source=source, quantity=quantity)
                except Exception as exc:
                    LOGGER.debug("V289 scoped entry-price save failed scope=%s symbol=%s error=%s", getattr(self, "_nija_account_scope_v289", "unknown"), symbol, exc)

            def _track_exit(self: Any, symbol: str, exit_quantity: float | None = None) -> bool:
                try:
                    with self.lock:
                        if symbol not in self.positions:
                            LOGGER.warning("V289 attempted exit of untracked position scope=%s symbol=%s", getattr(self, "_nija_account_scope_v289", "unknown"), symbol)
                            return False
                        if exit_quantity is None:
                            del self.positions[symbol]
                            full_exit = True
                        else:
                            position = self.positions[symbol]
                            quantity = self._safe_float(position.get("quantity"))
                            remaining = quantity - self._safe_float(exit_quantity)
                            if remaining <= 0:
                                del self.positions[symbol]
                                full_exit = True
                            else:
                                full_exit = False
                                if quantity > 0:
                                    position["size_usd"] = self._safe_float(position.get("size_usd")) * (remaining / quantity)
                                position["quantity"] = remaining
                        self._save_positions()
                    if full_exit:
                        scoped = getattr(self, "_nija_account_entry_store_v289", None)
                        if scoped is not None:
                            scoped.clear(symbol)
                    return True
                except Exception as exc:
                    LOGGER.error("V289 scoped track_exit failed scope=%s symbol=%s error=%s", getattr(self, "_nija_account_scope_v289", "unknown"), symbol, exc)
                    return False

            tracker._persist_entry_price = MethodType(_persist_entry_price, tracker)
            tracker.track_exit = MethodType(_track_exit, tracker)
            setattr(tracker, "_nija_scoped_methods_v289", True)

        if current_scope != scope:
            LOGGER.warning(
                "ACCOUNT_POSITION_STATE_V289_BOUND marker=%s scope=%s storage=%s legacy_shared_state_not_authoritative=true tracker_object_preserved=true",
                MARKER,
                scope,
                target_file,
            )
        return True
    except Exception as exc:
        LOGGER.error("ACCOUNT_POSITION_STATE_V289_BIND_FAILED marker=%s scope=%s error=%s:%s", MARKER, scope, type(exc).__name__, exc)
        return False


def _constructor_scope(class_name: str, args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> str:
    broker_type = class_name.replace("Broker", "").lower()
    account_type = kwargs.get("account_type", "platform")
    user_id = kwargs.get("user_id")
    if len(args) >= 1 and args[0] is not None:
        account_type = args[0]
    if len(args) >= 2 and args[1] is not None:
        user_id = args[1]
    return _scope(account_type, user_id, broker_type)


def _patch_position_tracker_constructor() -> bool:
    try:
        module = importlib.import_module("bot.position_tracker")
        cls = getattr(module, "PositionTracker", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "__init__", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def init_v289(self: Any, storage_file: str = "positions.json", *args: Any, **kwargs: Any) -> None:
        scope = str(getattr(_THREAD_LOCAL, "scope", "") or "")
        requested = str(storage_file or "positions.json")
        basename = os.path.basename(requested).lower()
        if scope and basename == "positions.json":
            storage_file = _position_file(scope)
        original(self, storage_file=storage_file, *args, **kwargs)
        if scope:
            _bind_tracker_instance(self, scope)

    setattr(init_v289, _PATCH_ATTR, True)
    setattr(init_v289, "__wrapped__", original)
    cls.__init__ = init_v289
    return True


def _patch_broker_constructors() -> bool:
    try:
        module = importlib.import_module("bot.broker_manager")
    except Exception:
        return False
    patched = False
    found = False
    for class_name in ("CoinbaseBroker", "KrakenBroker", "OKXBroker", "AlpacaBroker", "BinanceBroker"):
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type):
            continue
        current = getattr(cls, "__init__", None)
        if not callable(current):
            continue
        found = True
        if bool(getattr(current, _PATCH_ATTR, False)):
            patched = True
            continue
        original = current

        @wraps(original)
        def init_broker_v289(self: Any, *args: Any, __original=original, __class_name=class_name, **kwargs: Any) -> None:
            prior = getattr(_THREAD_LOCAL, "scope", None)
            _THREAD_LOCAL.scope = _constructor_scope(__class_name, args, kwargs)
            try:
                __original(self, *args, **kwargs)
            finally:
                if prior is None:
                    try:
                        delattr(_THREAD_LOCAL, "scope")
                    except Exception:
                        pass
                else:
                    _THREAD_LOCAL.scope = prior
            tracker = getattr(self, "position_tracker", None)
            if tracker is not None:
                _bind_tracker_instance(tracker, _broker_scope(self))

        setattr(init_broker_v289, _PATCH_ATTR, True)
        setattr(init_broker_v289, "__wrapped__", original)
        cls.__init__ = init_broker_v289
        patched = True
    return patched or not found


def _patch_startup_adopter() -> bool:
    try:
        module = importlib.import_module("bot.startup_position_sync")
    except Exception:
        return False
    current = getattr(module, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def adopt_v289(broker: Any, broker_name: str, _legacy_eps: Any) -> int:
        real = getattr(broker, "_broker", broker)
        scope = _broker_scope(real)
        tracker = getattr(real, "position_tracker", None)
        if tracker is not None:
            _bind_tracker_instance(tracker, scope)
        return original(broker, broker_name, _scoped_store(scope))

    setattr(adopt_v289, _PATCH_ATTR, True)
    setattr(adopt_v289, "__wrapped__", original)
    module._adopt_broker_positions = adopt_v289
    return True


def _current_snapshot_rows(broker: Any) -> tuple[bool, tuple[dict[str, Any], ...], str]:
    try:
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        status = getattr(v285, "_snapshot_status", None)
        if not callable(status):
            return False, (), "v285_snapshot_status_unavailable"
        ready, reason, rows, _age, _generation = status(broker)
        return bool(ready), tuple(dict(row) for row in tuple(rows or ())), str(reason or "")
    except Exception as exc:
        return False, (), f"v285_snapshot_status_error:{type(exc).__name__}:{exc}"


def _clean_authoritative_orphans(broker: Any, scope: str) -> tuple[int, str]:
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return 0, "tracker_missing"
    ready, rows, reason = _current_snapshot_rows(broker)
    if not ready:
        return 0, reason
    if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True or getattr(broker, "_startup_position_sync_adopted", None) is not True:
        return 0, "startup_position_proof_unready"
    sync = getattr(tracker, "sync_with_broker", None)
    if not callable(sync):
        return 0, "tracker_sync_with_broker_unavailable"
    removed = int(sync(list(rows)) or 0)
    if removed:
        LOGGER.critical(
            "ACCOUNT_POSITION_STATE_V289_STALE_TRACKER_REMOVED marker=%s scope=%s removed=%d authoritative_snapshot_current=true cross_account_state_not_preserved=true",
            MARKER,
            scope,
            removed,
        )
    return removed, "authoritative_cleanup_complete"


def _stop_legacy_global_repair() -> bool:
    try:
        module = importlib.import_module("bot.entry_price_store")
        getter = getattr(module, "get_entry_price_store", None)
        if not callable(getter):
            return True
        store = getter()
        stop = getattr(store, "stop_sync_repair_job", None)
        if callable(stop):
            stop()
        return True
    except Exception:
        return False


def _expected_accounts() -> dict[str, Any]:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        manager = v281._canonical_manager()
        return dict(v281._expected_accounts(manager)) if manager is not None else {}
    except Exception:
        return {}


def reconcile_once() -> dict[str, Any]:
    _patch_position_tracker_constructor()
    _patch_broker_constructors()
    _patch_startup_adopter()
    _stop_legacy_global_repair()
    accounts = _expected_accounts()
    bound: dict[str, bool] = {}
    cleanup: dict[str, tuple[int, str]] = {}
    tracker_owners: dict[int, list[str]] = {}
    for account, broker in accounts.items():
        if broker is None:
            bound[account] = False
            cleanup[account] = (0, "broker_missing")
            continue
        scope = _broker_scope(broker)
        tracker = getattr(broker, "position_tracker", None)
        if tracker is not None:
            tracker_owners.setdefault(id(tracker), []).append(account)
        bound[account] = bool(tracker is not None and _bind_tracker_instance(tracker, scope))

    shared_ids = {key for key, owners in tracker_owners.items() if len(owners) > 1}
    for account, broker in accounts.items():
        if broker is None:
            continue
        tracker = getattr(broker, "position_tracker", None)
        if tracker is None:
            continue
        if id(tracker) in shared_ids:
            cleanup[account] = (0, "shared_tracker_object_requires_fresh_reconstruction")
            continue
        cleanup[account] = _clean_authoritative_orphans(broker, _broker_scope(broker))

    ready = bool(accounts) and all(bound.values()) and not shared_ids
    signature = repr((tuple(sorted(bound.items())), tuple(sorted((k, v) for k, v in cleanup.items())), tuple(sorted(shared_ids))))
    global _LAST_SIGNATURE
    if signature != _LAST_SIGNATURE:
        _LAST_SIGNATURE = signature
        LOGGER.critical(
            "ACCOUNT_SCOPED_POSITION_STATE_V289_STATE marker=%s ready=%s accounts=%s shared_tracker_objects=%d cleanup=%s legacy_global_entry_repair_stopped=true authoritative_cleanup_only=true synthetic_position=false synthetic_cost_basis=false safety_gates_bypassed=false",
            MARKER,
            str(ready).lower(),
            tuple(accounts),
            len(shared_ids),
            cleanup,
        )
    return {"ready": ready, "accounts": tuple(accounts), "bound": bound, "cleanup": cleanup, "shared_tracker_objects": len(shared_ids)}


def _monitor() -> None:
    while not _MONITOR_STOP.wait(5.0):
        try:
            reconcile_once()
        except BaseException as exc:
            LOGGER.error("ACCOUNT_SCOPED_POSITION_STATE_V289_MONITOR_ERROR marker=%s error=%s:%s fail_closed=true", MARKER, type(exc).__name__, exc)


def _ensure_monitor() -> bool:
    global _MONITOR_THREAD
    with _LOCK:
        if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
            return True
        if _MONITOR_STOP.is_set():
            _MONITOR_STOP.clear()
        _MONITOR_THREAD = threading.Thread(target=_monitor, name="AccountScopedPositionStateV289", daemon=True)
        _MONITOR_THREAD.start()
        return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_account_scoped_position_state_v289"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    constructor = _patch_position_tracker_constructor()
    brokers = _patch_broker_constructors()
    adopter = _patch_startup_adopter()
    legacy_stopped = _stop_legacy_global_repair()
    monitor = _ensure_monitor()
    manifest = _register_manifest()
    reconcile_once()
    ready = bool(constructor and brokers and adopter and legacy_stopped and monitor and manifest)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_ACCOUNT_SCOPED_POSITION_STATE_V289_%s marker=%s ready=%s broker_constructor_scoping=true existing_tracker_rebind=true scoped_entry_price_store=true legacy_shared_repair_stopped=true authoritative_orphan_cleanup=true shared_tracker_mutation_blocked=true position_fabricated=false cost_basis_fabricated=false forced_trade=false forced_activation=false writer_nonce_capital_risk_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


def stop() -> None:
    _MONITOR_STOP.set()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "stop", "reconcile_once",
    "_scope", "_broker_scope", "_position_file", "_entry_file", "_bind_tracker_instance",
    "_patch_position_tracker_constructor", "_patch_broker_constructors", "_patch_startup_adopter",
    "_clean_authoritative_orphans",
]
