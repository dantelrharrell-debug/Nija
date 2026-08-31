"""Heartbeat live-venue selection fallback for startup execution proof (v274/v322).

Production on 2026-08-29 exposed a readiness-source race: the broker-local contract
reported active=coinbase,kraken,okx while the three-venue execution reconciler had
published NIJA_EXECUTION_READY_VENUES as an empty string because canonical capital
was temporarily stale. TradingStrategy._get_heartbeat_broker therefore failed before
an otherwise eligible startup heartbeat could reach the existing writer/nonce/risk/
capital/kill-switch/ECEL/order/fill gates.

v274 repairs selection only. When the canonical execution-ready variable is present
but temporarily empty, and only on the HeartbeatTrade thread, it may resolve a broker
from NIJA_ACTIVE_LIVE_VENUES. That broker receives no readiness, authority, capital,
or execution proof from this patch; the unchanged execution pipeline must still pass
all canonical safety gates. If no matching live broker object exists, selection stays
fail-closed. Ordinary order routing is untouched.

Production generation 5057 exposed a second selection-only mismatch. The generic
entry router can consider Coinbase eligible at its low account floor even when the
startup heartbeat resolves a larger exchange-safe notional (for example $12.50).
The downstream CapitalAuthorization gate correctly rejects that order, but repeatedly
selecting the same underfunded venue prevents a genuinely funded venue from being
tried and can add misleading local rejection noise.

v322 therefore filters only the v274 heartbeat fallback candidates by the actual
broker-specific heartbeat notional returned by TradingStrategy's existing
_resolve_heartbeat_trade_amount_usd() method and a previously hydrated/cache-backed
balance. It performs no broker I/O. Unknown balance/notional is fail-closed. The
normal _select_entry_broker() checks still run after filtering and the execution
pipeline still revalidates real buying power, minimum notional, risk, writer, nonce,
kill-switch, order acknowledgement, and fill status. No balance, readiness, execution
proof, trade, or activation is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_live_venue_selection_v274")
MARKER = "20260829-heartbeat-live-venue-selection-v274"
FUNDED_MARKER = "20260831-heartbeat-funded-venue-selection-v322"
RELEASE_ID = "20260829-runtime-convergence-v274"
FUNDED_RELEASE_ID = "20260831-runtime-convergence-v322"
_READY_FLAG = "NIJA_HEARTBEAT_LIVE_VENUE_SELECTION_V274_READY"
_FUNDED_READY_FLAG = "NIJA_HEARTBEAT_FUNDED_VENUE_SELECTION_V322_READY"
_PATCH_ATTR = "_nija_heartbeat_live_venue_selection_v274"
_LOCK = threading.RLock()


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {
        "1", "true", "yes", "on", "enabled", "y"
    }


def _live_venue_fallback_set() -> tuple[bool, tuple[str, ...], str]:
    """Return a selection-only fallback set; never infer execution readiness."""
    if threading.current_thread().name != "HeartbeatTrade":
        return False, (), "not_heartbeat_thread"
    if "NIJA_EXECUTION_READY_VENUES" not in os.environ:
        return False, (), "canonical_readiness_not_published"
    canonical_raw = str(os.environ.get("NIJA_EXECUTION_READY_VENUES", "") or "").strip()
    if canonical_raw:
        return False, (), "canonical_ready_set_nonempty"
    if not _truthy("NIJA_GLOBAL_TRADING_READY"):
        return False, (), "broker_local_global_ready_false"
    active_raw = str(os.environ.get("NIJA_ACTIVE_LIVE_VENUES", "") or "")
    active = tuple(
        dict.fromkeys(
            part.strip().lower()
            for part in active_raw.split(",")
            if part.strip()
        )
    )
    if not active:
        return False, (), "broker_local_active_set_empty"
    return True, active, "broker_local_selection_only"


def _candidate_brokers(strategy: Any) -> dict[Any, Any]:
    try:
        v273 = importlib.import_module("bot.runtime_heartbeat_position_cap_failover_v273_patch")
        resolver = getattr(v273, "_candidate_brokers", None)
        if callable(resolver):
            return dict(resolver(strategy) or {})
    except Exception:
        pass
    candidates: dict[Any, Any] = {}
    manager = getattr(strategy, "multi_account_manager", None)
    if manager is not None:
        for attr in ("platform_brokers", "_platform_brokers"):
            mapping = getattr(manager, attr, None)
            if isinstance(mapping, dict):
                candidates.update(mapping)
    broker_manager = getattr(strategy, "broker_manager", None)
    if broker_manager is not None:
        mapping = getattr(broker_manager, "brokers", None)
        if isinstance(mapping, dict):
            candidates.update(mapping)
        try:
            primary = broker_manager.get_primary_broker()
        except Exception:
            primary = None
        if primary is not None:
            candidates.setdefault(getattr(primary, "broker_type", "primary"), primary)
    broker = getattr(strategy, "broker", None)
    if broker is not None:
        candidates.setdefault(getattr(broker, "broker_type", "cached"), broker)
    return candidates


def _broker_key(strategy: Any, broker: Any) -> str:
    try:
        v273 = importlib.import_module("bot.runtime_heartbeat_position_cap_failover_v273_patch")
        resolver = getattr(v273, "_broker_key", None)
        if callable(resolver):
            value = str(resolver(strategy, broker) or "").strip().lower()
            if value:
                return value
    except Exception:
        pass
    resolver = getattr(strategy, "_broker_key_from_obj", None)
    if callable(resolver):
        try:
            value = str(resolver(broker) or "").strip().lower()
            if value:
                return value
        except Exception:
            pass
    value = str(getattr(broker, "broker_type", "") or "").strip().lower()
    if value:
        return value
    return type(broker).__name__.replace("Broker", "").strip().lower() or "unknown"


def _cached_entry_balance(strategy: Any, broker: Any, broker_key: str) -> tuple[float | None, str]:
    """Return a previously hydrated balance without starting broker I/O."""
    cached = getattr(broker, "_last_known_balance", None)
    if cached is not None:
        try:
            parser = getattr(strategy, "_balance_from_payload", None)
            value = float(parser(cached) if callable(parser) else cached)
            if value >= 0.0:
                return value, "broker_cache"
        except (TypeError, ValueError):
            pass
        except Exception:
            pass

    try:
        from bot.balance_service import BalanceService
    except ImportError:
        try:
            from balance_service import BalanceService  # type: ignore[import]
        except ImportError:
            BalanceService = None  # type: ignore[assignment]
    if BalanceService is not None:
        try:
            value = float(BalanceService.get(broker_key) or 0.0)
            if value >= 0.0:
                return value, "balance_service"
        except Exception:
            pass
    return None, "unproven"


def _heartbeat_required_notional(strategy: Any, broker: Any) -> float | None:
    resolver = getattr(strategy, "_resolve_heartbeat_trade_amount_usd", None)
    if not callable(resolver):
        return None
    try:
        value = float(resolver(broker) or 0.0)
    except Exception:
        return None
    return value if value > 0.0 else None


def _funded_heartbeat_candidates(
    strategy: Any,
    candidates: dict[Any, Any],
) -> tuple[dict[Any, Any], dict[str, str]]:
    """Filter fallback candidates using proven cached balance and real heartbeat size.

    This helper is intentionally selection-only. It never calls a broker method and
    never grants readiness. Downstream CapitalAuthorization remains authoritative.
    """
    funded: dict[Any, Any] = {}
    diagnostics: dict[str, str] = {}
    for raw_key, broker in candidates.items():
        if broker is None:
            continue
        key = _broker_key(strategy, broker)
        required = _heartbeat_required_notional(strategy, broker)
        balance, source = _cached_entry_balance(strategy, broker, key)
        if required is None:
            diagnostics[key] = "heartbeat_notional_unproven"
            LOGGER.warning(
                "HEARTBEAT_FUNDED_VENUE_V322_DEFERRED marker=%s venue=%s "
                "reason=heartbeat_notional_unproven selection_only=true broker_io=false "
                "capital_ready_not_granted=true execution_proof_fabricated=false "
                "forced_activation=false safety_gates_bypassed=false",
                FUNDED_MARKER,
                key,
            )
            continue
        if balance is None:
            diagnostics[key] = f"cached_balance_unproven:required={required:.2f}"
            LOGGER.warning(
                "HEARTBEAT_FUNDED_VENUE_V322_DEFERRED marker=%s venue=%s required=%.2f "
                "reason=cached_balance_unproven selection_only=true broker_io=false "
                "capital_ready_not_granted=true execution_proof_fabricated=false "
                "forced_activation=false safety_gates_bypassed=false",
                FUNDED_MARKER,
                key,
                required,
            )
            continue
        if balance + 1e-9 < required:
            diagnostics[key] = f"underfunded:balance={balance:.2f}:required={required:.2f}:source={source}"
            LOGGER.warning(
                "HEARTBEAT_FUNDED_VENUE_V322_UNDERFUNDED marker=%s venue=%s balance=%.2f "
                "required=%.2f source=%s selection_only=true broker_io=false "
                "downstream_capital_authorization_required=true minimum_notional_unchanged=true "
                "readiness_granted=false execution_proof_fabricated=false forced_trade=false "
                "forced_activation=false safety_gates_bypassed=false",
                FUNDED_MARKER,
                key,
                balance,
                required,
                source,
            )
            continue
        diagnostics[key] = f"funded:balance={balance:.2f}:required={required:.2f}:source={source}"
        funded[raw_key] = broker

    return funded, diagnostics


def _wrap_selector(current: Callable[..., Any]) -> Callable[..., Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def select_v274(self: Any):
        selected = current(self)
        if selected is not None:
            return selected

        allowed_fallback, live_venues, reason = _live_venue_fallback_set()
        if not allowed_fallback:
            return None

        live_set = set(live_venues)
        candidates = {
            raw_key: broker
            for raw_key, broker in _candidate_brokers(self).items()
            if broker is not None and _broker_key(self, broker) in live_set
        }
        if not candidates:
            LOGGER.warning(
                "HEARTBEAT_LIVE_VENUE_SELECTION_V274_NO_MATCH marker=%s active=%s "
                "selection_only=true trading_fail_closed=true",
                MARKER, ",".join(live_venues),
            )
            return None

        funded_candidates, funding_status = _funded_heartbeat_candidates(self, candidates)
        if not funded_candidates:
            LOGGER.error(
                "HEARTBEAT_FUNDED_VENUE_V322_NONE marker=%s active=%s status=%s "
                "selection_only=true broker_io=false trading_fail_closed=true "
                "capital_ready_not_granted=true execution_proof_fabricated=false "
                "forced_trade=false forced_activation=false safety_gates_bypassed=false",
                FUNDED_MARKER,
                ",".join(live_venues),
                funding_status,
            )
            return None

        selector = getattr(self, "_select_entry_broker", None)
        if not callable(selector):
            LOGGER.error(
                "HEARTBEAT_LIVE_VENUE_SELECTION_V274_SELECTOR_MISSING marker=%s "
                "selection_only=true trading_fail_closed=true",
                MARKER,
            )
            return None
        try:
            fallback, _name, status = selector(funded_candidates)
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_LIVE_VENUE_SELECTION_V274_SELECTOR_ERROR marker=%s error=%s:%s "
                "selection_only=true trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
            return None
        if fallback is None or _broker_key(self, fallback) not in live_set:
            LOGGER.warning(
                "HEARTBEAT_LIVE_VENUE_SELECTION_V274_UNAVAILABLE marker=%s active=%s status=%s "
                "funding_status=%s selection_only=true trading_fail_closed=true",
                MARKER, ",".join(live_venues), status or "no_matching_broker", funding_status,
            )
            return None

        self.broker = fallback
        broker_manager = getattr(self, "broker_manager", None)
        if broker_manager is not None:
            try:
                broker_manager.active_broker = fallback
            except Exception:
                pass
        LOGGER.critical(
            "HEARTBEAT_LIVE_VENUE_SELECTION_V274_FALLBACK marker=%s selected=%s active=%s reason=%s "
            "funding_aware_v322=true funding_status=%s selection_only=true "
            "execution_readiness_not_granted=true capital_ready_not_granted=true "
            "writer_nonce_risk_killswitch_ecel_min_notional_order_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER, _broker_key(self, fallback), ",".join(live_venues), reason, funding_status,
        )
        return fallback

    setattr(select_v274, _PATCH_ATTR, True)
    setattr(select_v274, "__wrapped__", current)
    return select_v274


def _patch_trading_strategy() -> tuple[bool, tuple[str, ...]]:
    try:
        importlib.import_module("bot.trading_strategy")
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_LIVE_VENUE_SELECTION_V274_IMPORT_DEFERRED marker=%s error=%s:%s",
            MARKER, type(exc).__name__, exc,
        )
    patched: list[str] = []
    seen: set[int] = set()
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "TradingStrategy", None)
        if not isinstance(cls, type) or id(cls) in seen:
            continue
        seen.add(id(cls))
        current = getattr(cls, "_get_heartbeat_broker", None)
        if not callable(current):
            continue
        cls._get_heartbeat_broker = _wrap_selector(current)
        if bool(getattr(getattr(cls, "_get_heartbeat_broker", None), _PATCH_ATTR, False)):
            patched.append(str(getattr(module, "__name__", name)))
    return bool(patched), tuple(sorted(set(patched)))


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["heartbeat_live_venue_selection_v274"] = _READY_FLAG
        required["heartbeat_funded_venue_selection_v322"] = _FUNDED_READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        try:
            strategy_ready, strategy_surfaces = _patch_trading_strategy()
            manifest_ready = _register_manifest()
            ready = bool(strategy_ready and manifest_ready)
        except Exception as exc:
            LOGGER.error(
                "HEARTBEAT_LIVE_VENUE_SELECTION_V274_INSTALL_ERROR marker=%s error=%s:%s "
                "trading_fail_closed=true",
                MARKER, type(exc).__name__, exc, exc_info=True,
            )
            ready, strategy_surfaces, manifest_ready = False, (), False
        os.environ[_READY_FLAG] = "1" if ready else "0"
        os.environ[_FUNDED_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "HEARTBEAT_LIVE_VENUE_SELECTION_V274_READY marker=%s ready=true strategy_surfaces=%s "
                "heartbeat_thread_only=true canonical_empty_only=true broker_local_active_set_only=true "
                "selection_only=true funding_aware_v322=true cached_balance_only=true broker_io=false "
                "execution_readiness_not_granted=true capital_ready_not_granted=true "
                "ordinary_orders_unchanged=true writer_nonce_risk_capital_killswitch_ecel_min_notional_order_fill_gates_unchanged=true "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER, ",".join(strategy_surfaces),
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "FUNDED_MARKER", "RELEASE_ID", "FUNDED_RELEASE_ID",
    "install", "install_import_hook", "_live_venue_fallback_set",
    "_candidate_brokers", "_broker_key", "_cached_entry_balance",
    "_heartbeat_required_notional", "_funded_heartbeat_candidates",
    "_wrap_selector", "_patch_trading_strategy",
]
