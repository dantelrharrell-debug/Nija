"""Universal four-way protection scope convergence v376.

Extend NIJA's existing v375 four-way protection policy across every canonical
platform/user broker and every asset class represented by the execution
contract without changing strategy thresholds, sizing, leverage, or broker
routing.

Safety contract
---------------
* Fixed stop-loss, fixed take-profit, trailing stop-loss, and trailing
  take-profit remain mandatory before new exposure can execute.
* Every selected canonical broker must expose the exact interfaces used by the
  universal software exit monitor: position read, market price read, and
  position-closing order submission.
* Every canonical broker object is reconciled into the universal supervisor,
  including brokers added for future users or future broker integrations.
* The rule is asset-class agnostic. Current canonical classes (crypto, equity,
  futures, options) and future metadata values receive the same four-way row
  contract; no market is exempted here.
* Existing exit/reduce requests always remain allowed.
* Account-local isolation is preserved: a broken user broker blocks that user's
  new exposure, not unrelated safe platform/user accounts. Broadcast/all-account
  requests still require every selected connected account to pass.
* v375's legacy trigger ordering is preserved. v376 supplements the missing
  trailing leg only after the pre-existing trigger declines to exit, avoiding
  premature synthesized TP exits and preserving fee-aware downstream floors.
* No position, price, fill, connectivity, account identity, or broker
  capability is fabricated. If a selected broker cannot prove the required
  interfaces, new exposure fails closed.
* v376 remains an independent per-entry scope gate above v265 rather than a
  dependency inside v265's own readiness calculation. This avoids a circular
  recovery lock after a transient broker outage while preserving v265 as the
  baseline protective-exit authority.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_universal_four_way_scope_v376")
MARKER = "20260906-universal-four-way-scope-v376"
_READY_FLAG = "NIJA_RUNTIME_UNIVERSAL_FOUR_WAY_SCOPE_V376_READY"
_TRIGGER_PATCH_ATTR = "_nija_universal_four_way_scope_trigger_v376"
_PIPELINE_PATCH_ATTR = "_nija_universal_four_way_scope_pipeline_v376"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_EPS = 1e-12


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if number == number else default
    except Exception:
        return default


def _norm(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.replace("/", "-").replace("_", "-")


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _broker_label(broker: Any) -> str:
    try:
        auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
        label = getattr(auto_exit, "_broker_label", None)
        if callable(label):
            return _norm(label(broker) or "unknown")
    except Exception:
        pass
    raw = getattr(getattr(broker, "broker_type", None), "value", None)
    raw = raw or getattr(broker, "broker_type", None)
    return _norm(raw or type(broker).__name__)


def _manager() -> Any:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        getter = getattr(v281, "_canonical_manager", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _expected_accounts() -> dict[str, Any]:
    manager = _manager()
    if manager is None:
        return {}
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        getter = getattr(v281, "_expected_accounts", None)
        return dict(getter(manager) or {}) if callable(getter) else {}
    except Exception:
        return {}


def _engine_brokers() -> list[Any]:
    brokers: list[Any] = []
    try:
        auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
        snapshot = getattr(auto_exit, "_engine_snapshot", None)
        engines = snapshot() if callable(snapshot) else []
        for engine in list(engines or []):
            broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)
            if broker is not None:
                brokers.append(broker)
    except Exception:
        pass
    return brokers


def _canonical_brokers() -> list[Any]:
    candidates = [broker for broker in _expected_accounts().values() if broker is not None]
    candidates.extend(_engine_brokers())
    unique: list[Any] = []
    seen: set[int] = set()
    for broker in candidates:
        if broker is None or id(broker) in seen:
            continue
        seen.add(id(broker))
        unique.append(broker)
    return unique


def _position_read_capable(broker: Any) -> bool:
    tracker = getattr(broker, "position_tracker", None)
    if tracker is not None:
        if any(callable(getattr(tracker, name, None)) for name in ("get_open_positions", "list_positions")):
            return True
        if callable(getattr(tracker, "get_all_positions", None)) and callable(getattr(tracker, "get_position", None)):
            return True
        if isinstance(getattr(tracker, "positions", None), Mapping):
            return True
    return any(isinstance(getattr(broker, attr, None), (Mapping, list, tuple, set)) for attr in ("positions", "open_positions", "tracked_positions"))


def _price_read_capable(broker: Any) -> bool:
    return any(
        callable(getattr(broker, name, None))
        for name in ("get_quote", "get_market_data", "get_ticker", "fetch_ticker")
    )


def _close_write_capable(broker: Any) -> bool:
    return any(
        callable(getattr(broker, name, None))
        for name in ("place_market_order", "place_order", "market_order", "execute_order")
    )


def _broker_capability(broker: Any) -> dict[str, Any]:
    return {
        "broker": _broker_label(broker),
        "class": type(broker).__name__,
        "connected": _connected(broker),
        "position_read": _position_read_capable(broker),
        "price_read": _price_read_capable(broker),
        "close_write": _close_write_capable(broker),
    }


def _reconcile_supervisor(brokers: list[Any] | None = None) -> tuple[bool, set[int]]:
    try:
        supervisor = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
    except Exception:
        return False, set()
    register = getattr(supervisor, "_register_broker", None)
    snapshot = getattr(supervisor, "_snapshot", None)
    if not callable(register) or not callable(snapshot):
        return False, set()
    for broker in list(brokers if brokers is not None else _canonical_brokers()):
        try:
            register(broker)
        except Exception as exc:
            LOGGER.warning(
                "UNIVERSAL_FOUR_WAY_SCOPE_REGISTER_FAILED marker=%s broker=%s class=%s error=%s:%s",
                MARKER,
                _broker_label(broker),
                type(broker).__name__,
                type(exc).__name__,
                exc,
            )
    try:
        registered = {id(item) for item in list(snapshot() or []) if item is not None}
    except Exception:
        return False, set()
    return True, registered


def _asset_classes() -> tuple[str, ...]:
    try:
        contract = importlib.import_module("bot.pipeline_request_contract")
        raw = getattr(contract, "_ASSET_CLASSES", ())
        values = tuple(sorted(str(item) for item in raw if str(item)))
        if values:
            return values
    except Exception:
        pass
    return ("crypto", "equity", "futures", "options")


def _asset_scope_self_test() -> tuple[bool, dict[str, bool]]:
    """Prove the v375 row contract does not exempt an asset/market label."""
    try:
        v375 = importlib.import_module("bot.runtime_universal_sl_tp_policy_v375_patch")
        policy = getattr(v375, "_policy_row", None)
        if not callable(policy):
            return False, {"policy_callable": False}
    except Exception:
        return False, {"policy_import": False}

    outcomes: dict[str, bool] = {}
    for asset_class in (*_asset_classes(), "future_market"):
        row = policy(
            {
                "account_id": "scope-self-test",
                "position_id": f"scope-{asset_class}",
                "symbol": "SCOPE-TEST",
                "side": "long",
                "entry_price": 100.0,
                "quantity": 1.0,
                "asset_class": asset_class,
                "trade_type": "scope_self_test",
            }
        )
        outcomes[asset_class] = bool(
            isinstance(row, Mapping)
            and row.get("asset_class") == asset_class
            and row.get("universal_four_way_policy_complete") is True
            and row.get("software_stop_loss_available") is True
            and row.get("software_take_profit_available") is True
            and row.get("software_trailing_stop_available") is True
            and row.get("software_trailing_take_profit_available") is True
        )
    return all(outcomes.values()), outcomes


def _request_is_broadcast(request: Any) -> bool:
    if request is None:
        return False
    account = _norm(getattr(request, "account_id", ""))
    metadata = dict(getattr(request, "metadata", {}) or {})
    return bool(
        account in {"all", "broadcast", "all-accounts"}
        or metadata.get("broadcast_all_accounts") is True
        or metadata.get("all_accounts") is True
        or metadata.get("copy_to_all_accounts") is True
    )


def _select_expected_accounts(request: Any, expected: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Resolve the account-local denominator for one execution request."""
    all_rows = {str(key): broker for key, broker in dict(expected or {}).items()}
    if request is None:
        return all_rows, "background_audit"
    if _request_is_broadcast(request):
        return all_rows, "broadcast"

    account_raw = str(getattr(request, "account_id", "") or "").strip()
    account = _norm(account_raw)
    preferred = _norm(getattr(request, "preferred_broker", ""))

    # The canonical request default is a platform request unless a broadcaster
    # explicitly marks all-account fanout in metadata.
    if account in {"", "default", "platform", "master"}:
        selected = {key: broker for key, broker in all_rows.items() if key.startswith("platform:")}
        mode = "platform_default"
    elif account_raw in all_rows:
        selected = {account_raw: all_rows[account_raw]}
        mode = "exact_account"
    elif account.startswith("platform:"):
        selected = {key: broker for key, broker in all_rows.items() if _norm(key) == account}
        mode = "platform_account"
    elif account.startswith("user:"):
        selected = {key: broker for key, broker in all_rows.items() if _norm(key) == account or _norm(key).startswith(account + ":")}
        mode = "user_account"
    elif f"platform:{account}" in {_norm(key) for key in all_rows}:
        selected = {key: broker for key, broker in all_rows.items() if _norm(key) == f"platform:{account}"}
        mode = "platform_venue_alias"
    else:
        user_prefix = f"user:{account}:"
        selected = {key: broker for key, broker in all_rows.items() if _norm(key).startswith(user_prefix)}
        mode = "user_id_alias"

    if preferred:
        selected = {
            key: broker
            for key, broker in selected.items()
            if _norm(key).endswith(":" + preferred) or _broker_label(broker) == preferred
        }
        mode += "+preferred_broker"
    return selected, mode


def _scope_truth(request: Any = None) -> tuple[bool, dict[str, Any]]:
    expected = _expected_accounts()
    all_brokers = _canonical_brokers()
    supervisor_ready, registered_ids = _reconcile_supervisor(all_brokers)
    asset_ready, asset_details = _asset_scope_self_test()

    try:
        supervisor = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
        state = getattr(supervisor, "_STATE", {})
        supervisor_started = bool(isinstance(state, dict) and state.get("started") is True)
    except Exception:
        supervisor_started = False

    v375_ready = _truthy(os.environ.get("NIJA_RUNTIME_UNIVERSAL_SL_TP_POLICY_V375_READY"))
    selected, selection_mode = _select_expected_accounts(request, expected)

    capability_rows: list[dict[str, Any]] = []
    selected_ready = True
    if request is not None:
        if not selected:
            selected_ready = False
        for account_key, broker in selected.items():
            row = {"account": account_key, **_broker_capability(broker)} if broker is not None else {
                "account": account_key,
                "broker": _norm(account_key.rsplit(":", 1)[-1]),
                "class": "missing",
                "connected": False,
                "position_read": False,
                "price_read": False,
                "close_write": False,
            }
            row["registered"] = bool(broker is not None and id(broker) in registered_ids)
            row_ready = bool(
                broker is not None
                and row["connected"]
                and row["position_read"]
                and row["price_read"]
                and row["close_write"]
                and row["registered"]
            )
            row["four_way_scope_ready"] = row_ready
            capability_rows.append(row)
            selected_ready = bool(selected_ready and row_ready)
    else:
        # Background readiness proves the protection service itself is installed.
        # Individual account capability remains request-scoped so a broken user
        # cannot revoke unrelated safe platform/user execution.
        for account_key, broker in expected.items():
            if broker is None or not _connected(broker):
                continue
            row = {"account": account_key, **_broker_capability(broker)}
            row["registered"] = id(broker) in registered_ids
            row["four_way_scope_ready"] = bool(
                row["position_read"] and row["price_read"] and row["close_write"] and row["registered"]
            )
            capability_rows.append(row)

    service_ready = bool(v375_ready and supervisor_ready and supervisor_started and asset_ready)
    ready = bool(service_ready and (selected_ready if request is not None else True))
    details = {
        "v375_ready": v375_ready,
        "supervisor_ready": supervisor_ready,
        "supervisor_started": supervisor_started,
        "asset_scope_ready": asset_ready,
        "asset_scope": asset_details,
        "selection_mode": selection_mode,
        "selected_accounts": tuple(selected),
        "selected_ready": selected_ready if request is not None else None,
        "capabilities": capability_rows,
        "expected_accounts": len(expected),
        "canonical_broker_objects": len(all_brokers),
        "account_local_isolation": True,
    }
    if request is None:
        os.environ[_READY_FLAG] = "1" if ready else "0"
    return ready, details


def _find_v375_layer(func: Callable[..., Any], marker_attr: str) -> Callable[..., Any] | None:
    seen: set[int] = set()
    current: Any = func
    for _ in range(32):
        if not callable(current) or id(current) in seen:
            return None
        seen.add(id(current))
        if bool(getattr(current, marker_attr, False)):
            return current
        current = getattr(current, "__wrapped__", None)
    return None


def _patch_trigger_compatibility() -> bool:
    """Preserve legacy trigger order, then supplement missing trailing logic."""
    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    v375 = importlib.import_module("bot.runtime_universal_sl_tp_policy_v375_patch")

    patcher = getattr(v375, "_patch_auto_exit_trigger", None)
    if callable(patcher):
        patcher()
    current = getattr(auto_exit, "_trigger", None)
    marker_attr = str(getattr(v375, "_PATCH_ATTR", "_nija_universal_sl_tp_policy_v375"))
    if not callable(current):
        return False
    layer = _find_v375_layer(current, marker_attr)
    if not callable(layer):
        return False
    base = getattr(layer, "__wrapped__", None)
    if not callable(base):
        return False

    existing = getattr(v375, "_four_way_trigger", None)
    if callable(existing) and bool(getattr(existing, _TRIGGER_PATCH_ATTR, False)):
        return True

    def compatible_trigger(pos: dict[str, Any], price: float) -> tuple[bool, str, float]:
        hit, reason, target = base(pos, price)
        if hit:
            return bool(hit), str(reason or ""), _f(target)

        policy = getattr(v375, "_policy_row", None)
        select = getattr(v375, "_select_trailing_candidate", None)
        if not callable(policy) or not callable(select) or price <= 0.0:
            return False, "", 0.0
        row = policy(pos)
        if not isinstance(row, Mapping):
            return False, "", 0.0
        entry = _f(row.get("entry_price", row.get("avg_entry_price", row.get("average_price"))))
        qty = 0.0
        for key in ("quantity", "qty", "size", "amount", "units", "balance"):
            if row.get(key) is not None:
                qty = abs(_f(row.get(key)))
                break
        if entry <= _EPS or qty <= _EPS:
            return False, "", 0.0

        side_fn = getattr(auto_exit, "_side", None)
        side = str(side_fn(row.get("side"), dict(row)) if callable(side_fn) else row.get("side") or "").lower()
        long_side = side in {"long", "buy"}
        key_fn = getattr(auto_exit, "_position_key", None)
        water = getattr(auto_exit, "_HIGH_WATER", None)
        if not callable(key_fn) or not isinstance(water, dict):
            return False, "", 0.0
        key = str(key_fn(dict(row)))
        existing_extreme = _f(water.get(key), entry)
        extreme = (
            max(existing_extreme, entry, price)
            if long_side
            else min(existing_extreme if existing_extreme > 0 else entry, entry, price)
        )
        water[key] = extreme
        return select(
            row,
            entry=entry,
            price=price,
            long_side=long_side,
            extreme=extreme,
        )

    setattr(compatible_trigger, _TRIGGER_PATCH_ATTR, True)
    setattr(compatible_trigger, "__wrapped__", base)
    v375._four_way_trigger = compatible_trigger
    return True


def _is_exit_request(request: Any) -> bool:
    intent = str(getattr(request, "intent_type", "") or "").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    metadata = dict(getattr(request, "metadata", {}) or {})
    return (
        intent in {"exit", "reduce"}
        or effect in {"close", "reduce"}
        or metadata.get("closing_position") is True
    )


def _pipeline_denial(module: ModuleType, request: Any, details: Mapping[str, Any]) -> Any:
    result_cls = getattr(module, "PipelineResult", None)
    if not isinstance(result_cls, type):
        raise RuntimeError("UniversalFourWayScope unavailable: new exposure blocked")
    size = getattr(request, "size_usd", None)
    if size is None:
        size = getattr(request, "notional_usd", 0.0)
    LOGGER.critical(
        "UNIVERSAL_FOUR_WAY_SCOPE_ENTRY_BLOCKED marker=%s account=%s broker=%s asset_class=%s "
        "symbol=%s side=%s reason=selected_broker_protection_scope_unproven exits_still_allowed=true details=%s",
        MARKER,
        getattr(request, "account_id", ""),
        getattr(request, "preferred_broker", ""),
        getattr(request, "asset_class", ""),
        getattr(request, "symbol", ""),
        getattr(request, "side", ""),
        dict(details),
    )
    return result_cls(
        success=False,
        symbol=str(getattr(request, "symbol", "") or ""),
        side=str(getattr(request, "side", "") or ""),
        size_usd=float(size or 0.0),
        error="UniversalFourWayScope deny: selected account lacks four-way protective exit coverage",
    )


def _patch_execution_pipeline() -> bool:
    module = importlib.import_module("bot.execution_pipeline")
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "execute", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PIPELINE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def execute_v376(self: Any, request: Any):
        if _is_exit_request(request):
            return current(self, request)
        ready, details = _scope_truth(request)
        if ready:
            return current(self, request)
        return _pipeline_denial(module, request, details)

    setattr(execute_v376, _PIPELINE_PATCH_ATTR, True)
    setattr(execute_v376, "__wrapped__", current)
    cls.execute = execute_v376
    return True


def _patch_v265_stack_truth() -> bool:
    """Keep v376 independent so transient failures can recover without a cycle."""
    return True


def reassert() -> bool:
    """Reconcile all current brokers and keep account-local entry gating ready."""
    with _LOCK:
        try:
            v375 = importlib.import_module("bot.runtime_universal_sl_tp_policy_v375_patch")
            install_v375 = getattr(v375, "install_import_hook", None)
            if not callable(install_v375):
                install_v375 = getattr(v375, "install", None)
            v375_ready = bool(callable(install_v375) and install_v375())

            trigger_ready = _patch_trigger_compatibility() if v375_ready else False
            pipeline_ready = _patch_execution_pipeline() if v375_ready else False
            independent_scope_ready = _patch_v265_stack_truth() if v375_ready else False
            service_scope_ready, details = _scope_truth(None) if v375_ready else (False, {"v375_ready": False})
            os.environ[_READY_FLAG] = "1" if service_scope_ready else "0"

            authority_ready = _truthy(os.environ.get("NIJA_PROTECTIVE_EXIT_AUTHORITY_V265_READY"))
            ready = bool(
                v375_ready
                and trigger_ready
                and pipeline_ready
                and independent_scope_ready
                and service_scope_ready
                and authority_ready
            )
            os.environ[_READY_FLAG] = "1" if ready else "0"
            log = LOGGER.critical if ready else LOGGER.error
            log(
                "RUNTIME_UNIVERSAL_FOUR_WAY_SCOPE_V376_%s marker=%s ready=%s "
                "scope=platform_and_all_registered_users broker_scope=all_canonical_and_future_registered_brokers "
                "asset_scope=%s future_market_policy_agnostic=true long_short=true spot_margin_futures_options_equity=true "
                "fixed_sl=true fixed_tp=true trailing_sl=true trailing_tp=true broker_capability_fail_closed=true "
                "entry_gate=account_local exits_preserved=true v265_baseline_authority=%s "
                "scope_gate_independent=true thresholds_unchanged=true safety_gates_bypassed=false details=%s",
                "READY" if ready else "NOT_READY",
                MARKER,
                str(ready).lower(),
                ",".join(_asset_classes()),
                str(authority_ready).lower(),
                details,
            )
            return ready
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception(
                "RUNTIME_UNIVERSAL_FOUR_WAY_SCOPE_V376_FAILED marker=%s error=%s:%s "
                "new_entries_fail_closed=true existing_exits_preserved=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False


def _worker() -> None:
    while True:
        time.sleep(max(3.0, _f(os.environ.get("NIJA_UNIVERSAL_FOUR_WAY_SCOPE_REASSERT_SECONDS"), 5.0)))
        reassert()


def install_import_hook() -> bool:
    global _THREAD
    ready = reassert()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="UniversalFourWayScopeV376",
                daemon=True,
            )
            _THREAD.start()
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "reassert",
    "_asset_classes",
    "_asset_scope_self_test",
    "_broker_capability",
    "_select_expected_accounts",
    "_scope_truth",
    "_patch_trigger_compatibility",
    "_patch_execution_pipeline",
]
