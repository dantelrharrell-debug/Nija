"""Execution terminal recovery v342.

Repairs two production seams observed on 2026-09-01 without weakening any
execution safety gate.

1. Heartbeat funding selection: the existing v322 funding filter only ran when
   the canonical heartbeat selector returned None. A non-None but underfunded
   Coinbase selection therefore escaped the filter and was later rejected by
   CapitalAuthorization even while Kraken had sufficient spendable capital.
   v342 validates the selected heartbeat venue against the existing cached
   balance plus broker-specific heartbeat notional proof and, when needed,
   selects another already execution-ready funded venue. It performs no broker
   I/O and grants no readiness or execution proof.

2. Protective-exit unit preservation: under wrapper-order churn, a canonical
   v334 sell-to-close could reach Coinbase with quote-sized SELL semantics even
   though the verified exit contract was base-sized. Coinbase Advanced Trade
   requires base_size for market sells. v342 preserves base units only for the
   canonical protective-close metadata contract, using the smaller of the
   verified held quantity and the ECEL notional converted by an already
   verified price hint. ACK/fill truth remains authoritative and no fill is
   fabricated.

Writer, nonce, risk, capital, broker health, kill-switch, circuit, ECEL,
minimum-order, order-acknowledgement, fill, and activation gates are unchanged.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import math
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_execution_terminal_recovery_v342")
MARKER = "20260901-runtime-execution-terminal-recovery-v342"
RELEASE_ID = "20260901-runtime-convergence-v342"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_TERMINAL_RECOVERY_V342_READY"
_HEARTBEAT_PATCH_ATTR = "_nija_funded_heartbeat_selected_venue_v342"
_FACTORY_PATCH_ATTR = "_nija_funded_heartbeat_factory_v342"
_EXIT_PATCH_ATTR = "_nija_protective_exit_base_terminal_v342"
_LOCK = threading.RLock()
_ALLOWED_EXIT_ORIGINS = {"universal_v67", "kraken_account_exit"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if math.isfinite(parsed) else default


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _csv_env(name: str) -> tuple[str, ...]:
    raw = str(os.environ.get(name, "") or "")
    return tuple(dict.fromkeys(part.strip().lower() for part in raw.split(",") if part.strip()))


def _heartbeat_scope() -> bool:
    return threading.current_thread().name == "HeartbeatTrade"


def _funding_proof(v274: ModuleType, strategy: Any, broker: Any) -> tuple[bool, str, float, float, str]:
    key = str(v274._broker_key(strategy, broker) or "unknown").strip().lower()
    try:
        required = _float(v274._heartbeat_required_notional(strategy, broker), 0.0)
    except Exception:
        required = 0.0
    try:
        balance, source = v274._cached_entry_balance(strategy, broker, key)
        balance_f = _float(balance, -1.0) if balance is not None else -1.0
    except Exception:
        balance_f, source = -1.0, "unproven"
    if required <= 0.0:
        return False, key, balance_f, required, "heartbeat_notional_unproven"
    if balance_f < 0.0:
        return False, key, balance_f, required, f"cached_balance_unproven:{source}"
    if balance_f + 1e-9 < required:
        return False, key, balance_f, required, f"underfunded:{source}"
    return True, key, balance_f, required, f"funded:{source}"


def _eligible_heartbeat_candidates(v274: ModuleType, strategy: Any) -> tuple[dict[Any, Any], tuple[str, ...], str]:
    canonical = _csv_env("NIJA_EXECUTION_READY_VENUES")
    if canonical:
        allowed = canonical
        source = "canonical_execution_ready"
    else:
        allowed = _csv_env("NIJA_ACTIVE_LIVE_VENUES")
        source = "active_live_fallback"
    if not allowed:
        return {}, (), source
    allowed_set = set(allowed)
    try:
        raw_candidates = dict(v274._candidate_brokers(strategy) or {})
    except Exception:
        raw_candidates = {}
    candidates = {
        raw_key: broker
        for raw_key, broker in raw_candidates.items()
        if broker is not None and str(v274._broker_key(strategy, broker) or "").strip().lower() in allowed_set
    }
    return candidates, allowed, source


def _select_funded_alternative(v274: ModuleType, strategy: Any) -> Any:
    candidates, allowed, source = _eligible_heartbeat_candidates(v274, strategy)
    if not candidates:
        return None
    funded: dict[Any, Any] = {}
    diagnostics: dict[str, str] = {}
    for raw_key, broker in candidates.items():
        ok, key, balance, required, detail = _funding_proof(v274, strategy, broker)
        diagnostics[key] = f"{detail}:balance={balance:.8f}:required={required:.8f}"
        if ok:
            funded[raw_key] = broker
    if not funded:
        LOGGER.warning(
            "EXECUTION_TERMINAL_V342_HEARTBEAT_NO_FUNDED marker=%s source=%s diagnostics=%s selection_only=true broker_io=false trading_fail_closed=true safety_gates_bypassed=false",
            MARKER, source, diagnostics,
        )
        return None
    selector = getattr(strategy, "_select_entry_broker", None)
    if not callable(selector):
        return None
    try:
        selected, _name, status = selector(funded)
    except Exception as exc:
        LOGGER.warning("EXECUTION_TERMINAL_V342_HEARTBEAT_ALT_SELECTOR_ERROR marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc)
        return None
    if selected is None:
        LOGGER.warning("EXECUTION_TERMINAL_V342_HEARTBEAT_ALT_UNAVAILABLE marker=%s status=%s diagnostics=%s trading_fail_closed=true", MARKER, status or "none", diagnostics)
        return None
    ok, key, balance, required, detail = _funding_proof(v274, strategy, selected)
    if not ok:
        return None
    strategy.broker = selected
    broker_manager = getattr(strategy, "broker_manager", None)
    if broker_manager is not None:
        try:
            broker_manager.active_broker = selected
        except Exception:
            pass
    LOGGER.critical(
        "EXECUTION_TERMINAL_V342_HEARTBEAT_FUNDED_SELECTED marker=%s venue=%s balance=%.8f required=%.8f source=%s selection_only=true broker_io=false writer_nonce_risk_capital_killswitch_ecel_min_notional_order_fill_gates_unchanged=true execution_proof_fabricated=false forced_trade=false forced_activation=false safety_gates_bypassed=false",
        MARKER, key, balance, required, source,
    )
    return selected


def _wrap_heartbeat_selector(current: Any, v274: ModuleType):
    if not callable(current) or bool(getattr(current, _HEARTBEAT_PATCH_ATTR, False)):
        return current
    @wraps(current)
    def funded_selector_v342(self: Any):
        selected = current(self)
        if not _heartbeat_scope():
            return selected
        if selected is not None:
            ok, key, balance, required, detail = _funding_proof(v274, self, selected)
            if ok:
                return selected
            LOGGER.warning(
                "EXECUTION_TERMINAL_V342_HEARTBEAT_SELECTION_REJECTED marker=%s venue=%s balance=%.8f required=%.8f detail=%s selection_only=true broker_io=false capital_authorization_bypass=false trading_fail_closed=true safety_gates_bypassed=false",
                MARKER, key, balance, required, detail,
            )
        return _select_funded_alternative(v274, self)
    setattr(funded_selector_v342, _HEARTBEAT_PATCH_ATTR, True)
    setattr(funded_selector_v342, "__wrapped__", current)
    return funded_selector_v342


def _patch_heartbeat_selection() -> bool:
    v274 = importlib.import_module("bot.runtime_heartbeat_live_venue_selection_v274_patch")
    factory = getattr(v274, "_wrap_selector", None)
    if callable(factory) and not bool(getattr(factory, _FACTORY_PATCH_ATTR, False)):
        @wraps(factory)
        def factory_v342(current: Any):
            return _wrap_heartbeat_selector(factory(current), v274)
        setattr(factory_v342, _FACTORY_PATCH_ATTR, True)
        setattr(factory_v342, "__wrapped__", factory)
        v274._wrap_selector = factory_v342
    importlib.import_module("bot.trading_strategy")
    patched = False
    seen: set[int] = set()
    for module_name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "TradingStrategy", None)
        if not isinstance(cls, type) or id(cls) in seen:
            continue
        seen.add(id(cls))
        current = getattr(cls, "_get_heartbeat_broker", None)
        if not callable(current):
            continue
        cls._get_heartbeat_broker = _wrap_heartbeat_selector(current, v274)
        patched = patched or bool(getattr(getattr(cls, "_get_heartbeat_broker", None), _HEARTBEAT_PATCH_ATTR, False))
    return patched


def _canonical_protective_close(meta: Mapping[str, Any], side: str) -> bool:
    return bool(
        _norm(side) == "sell"
        and meta.get("protective_exit") is True
        and meta.get("closing_position") is True
        and _norm(meta.get("exit_origin")) in _ALLOWED_EXIT_ORIGINS
        and _float(meta.get("verified_position_quantity"), 0.0) > 0.0
    )


def _patch_protective_exit_base_terminal() -> bool:
    v328 = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
    current = getattr(v328, "_submit_direct", None)
    if not callable(current):
        return False
    if bool(getattr(current, _EXIT_PATCH_ATTR, False)):
        return True
    @wraps(current)
    def submit_direct_v342(broker: Any, symbol: str, side: str, size_usd: float, metadata: Mapping[str, Any]):
        meta = dict(metadata or {})
        if not _canonical_protective_close(meta, side):
            return current(broker, symbol, side, size_usd, meta)
        verified_qty = _float(meta.get("verified_position_quantity"), 0.0)
        price = _float(meta.get("price_hint_usd") or meta.get("reference_price_usd") or meta.get("pretrade_price"), 0.0)
        adjusted_notional = _float(size_usd, 0.0)
        if price <= 0.0 or adjusted_notional <= 0.0:
            raise RuntimeError("canonical protective exit base conversion unproven")
        ecel_qty = adjusted_notional / price
        base_qty = min(verified_qty, ecel_qty)
        if base_qty <= 0.0:
            raise RuntimeError("canonical protective exit base quantity invalid")
        submit = getattr(broker, "place_market_order", None) or getattr(broker, "execute_order", None) or getattr(broker, "place_order", None)
        if not callable(submit):
            raise RuntimeError(f"Broker {broker!r} has no market-order submit method")
        submit_kwargs: dict[str, Any] = {"size_type": "base"}
        trace_id = str(meta.get("decision_trace_id") or meta.get("trace_id") or "")
        if trace_id:
            try:
                signature = inspect.signature(submit)
                if "decision_trace_id" in signature.parameters:
                    submit_kwargs["decision_trace_id"] = trace_id
            except (TypeError, ValueError):
                pass
        LOGGER.critical(
            "EXECUTION_TERMINAL_V342_PROTECTIVE_BASE_PRESERVED marker=%s symbol=%s side=sell verified_qty=%.12f ecel_qty=%.12f submitted_qty=%.12f size_type=base adjusted_notional=%.8f price_hint=%.10f quote_sell_forbidden=true ordinary_orders_unchanged=true ack_fill_truth_unchanged=true minimum_order_gate_unchanged=true safety_gates_bypassed=false",
            MARKER, symbol, verified_qty, ecel_qty, base_qty, adjusted_notional, price,
        )
        try:
            return submit(symbol, side, float(base_qty), **submit_kwargs)
        except TypeError:
            try:
                return submit(symbol=symbol, side=side, quantity=float(base_qty), **submit_kwargs)
            except TypeError as exc:
                raise RuntimeError(f"canonical protective exit broker lacks explicit base-size contract: {exc}") from exc
    setattr(submit_direct_v342, _EXIT_PATCH_ATTR, True)
    setattr(submit_direct_v342, "__wrapped__", current)
    v328._submit_direct = submit_direct_v342
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_execution_terminal_recovery_v342"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        heartbeat_ready = exit_ready = manifest_ready = False
        try:
            heartbeat_ready = bool(_patch_heartbeat_selection())
            exit_ready = bool(_patch_protective_exit_base_terminal())
            manifest_ready = bool(_register_manifest())
        except Exception as exc:
            LOGGER.exception("EXECUTION_TERMINAL_V342_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true", MARKER, type(exc).__name__, exc)
        ready = bool(heartbeat_ready and exit_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        LOGGER.critical(
            "EXECUTION_TERMINAL_RECOVERY_V342_READY marker=%s ready=%s heartbeat_funded_selection=%s protective_exit_base_terminal=%s manifest=%s broker_io_added=false writer_nonce_risk_capital_killswitch_circuit_ecel_min_notional_ack_fill_gates_unchanged=true execution_proof_fabricated=false forced_trade=false forced_activation=false safety_gates_bypassed=false",
            MARKER, str(ready).lower(), str(heartbeat_ready).lower(), str(exit_ready).lower(), str(manifest_ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook"]
