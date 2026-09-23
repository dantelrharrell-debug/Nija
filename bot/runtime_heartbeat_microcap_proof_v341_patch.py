"""Heartbeat-only Coinbase micro-cap proof bridge (v341).

The startup execution heartbeat must produce a genuine broker ACK/fill before
execution readiness can become true. Coinbase's canonical minimum-notional gate
already supports micro-cap balances, but heartbeat-adjacent routing retained a
legacy $10/$12 Coinbase floor and the v322 candidate filter inherited the ordinary
active-venue publication. With a hydrated Coinbase quote balance below that legacy
floor, the heartbeat could never reach the unchanged execution pipeline even though
NIJA's canonical Coinbase micro-cap policy explicitly permitted the order size.

v341 is deliberately narrow:
- only the verified startup heartbeat may use the existing Coinbase micro-cap floor;
- ordinary entries retain their existing routing semantics;
- cached/hydrated balance only is used for heartbeat sizing/selection (no broker I/O);
- when v274's startup fallback regime is already active, Coinbase may be considered
  as a heartbeat-only candidate without mutating NIJA_ACTIVE_LIVE_VENUES;
- the canonical MinimumNotionalGate still validates the order;
- spendable cash, ECEL, risk, writer, nonce, kill switch, broker health, order ACK,
  fill verification, position sync, and capital gates remain authoritative.

No readiness, execution proof, fill, trade, or activation is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_microcap_proof_v341")
MARKER = "20260901-heartbeat-microcap-proof-v341"
RELEASE_ID = "20260901-runtime-convergence-v341"
_READY_FLAG = "NIJA_HEARTBEAT_MICROCAP_PROOF_V341_READY"
_PATCH_ATTR = "_nija_heartbeat_microcap_proof_v341"
_SELECTOR_ATTR = "_nija_heartbeat_microcap_selector_v341"
_ALLOWED_REASONS = {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}


def _broker_key(strategy: Any, broker: Any) -> str:
    try:
        v274 = importlib.import_module("bot.runtime_heartbeat_live_venue_selection_v274_patch")
        resolver = getattr(v274, "_broker_key", None)
        if callable(resolver):
            value = str(resolver(strategy, broker) or "").strip().lower()
            if value:
                return value
    except Exception:
        pass
    raw = getattr(broker, "broker_type", None)
    raw = getattr(raw, "value", raw)
    text = str(raw or type(broker).__name__).strip().lower()
    for key in ("coinbase", "kraken", "okx", "alpaca"):
        if key in text:
            return key
    return text


def _cached_balance(strategy: Any, broker: Any, broker_key: str) -> tuple[float | None, str]:
    """Use the same no-I/O cache authority as v322."""
    try:
        v274 = importlib.import_module("bot.runtime_heartbeat_live_venue_selection_v274_patch")
        resolver = getattr(v274, "_cached_entry_balance", None)
        if callable(resolver):
            balance, source = resolver(strategy, broker, broker_key)
            if balance is None:
                return None, str(source or "unproven")
            return max(0.0, float(balance)), str(source or "cached")
    except Exception:
        pass
    return None, "unproven"


def _coinbase_floor(balance: float) -> float:
    """Resolve NIJA's existing Coinbase micro-cap floor; never invent a new floor."""
    try:
        gate_mod = importlib.import_module("bot.minimum_notional_gate")
        getter = getattr(gate_mod, "get_minimum_notional_gate", None)
        gate = getter() if callable(getter) else None
        config = getattr(gate, "config", None)
        resolver = getattr(config, "get_min_notional_for_broker", None)
        if callable(resolver):
            return max(1.0, float(resolver("coinbase", balance=max(0.0, float(balance))) or 0.0))
    except Exception:
        pass
    # Failure is conservative: retain the ordinary Coinbase floor.
    return max(10.0, float(os.environ.get("COINBASE_VENUE_THRESHOLD_USD", "12.0") or 12.0))


def _buffer_pct() -> float:
    try:
        return max(0.0, min(float(os.environ.get("NIJA_ENTRY_SPENDABLE_BUFFER_PCT", "0.10") or 0.10), 0.50))
    except Exception:
        return 0.10


def _execution_hardening_floor(broker_key: str, balance: float) -> float | None:
    """Return the canonical execution-layer minimum average for this balance.

    v341 is allowed to downshift only when the resulting heartbeat remains valid
    under the same hardening policy enforced at broker submission.  If that
    policy cannot be resolved, fail closed by returning None so the caller keeps
    the ordinary (larger) heartbeat notional.
    """
    try:
        monitor_mod = importlib.import_module("bot.execution_average_position_monitor")
        monitor_cls = getattr(monitor_mod, "ExecutionAveragePositionMonitor", None)
        if not isinstance(monitor_cls, type):
            return None
        monitor = monitor_cls(broker_type=str(broker_key or "default"))
        threshold = max(0.0, float(getattr(monitor, "min_avg_threshold", 0.0) or 0.0))
        low_cap_threshold = max(0.0, float(getattr(monitor, "LOW_CAPITAL_THRESHOLD", 0.0) or 0.0))
        low_cap_min = max(0.0, float(getattr(monitor, "LOW_CAPITAL_MIN_AVG", 0.0) or 0.0))
        if (
            bool(getattr(monitor, "enforce_low_capital_mode", True))
            and balance > 0.0
            and low_cap_threshold > 0.0
            and balance < low_cap_threshold
        ):
            threshold = max(threshold, low_cap_min)
        return threshold
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_MICROCAP_V341_HARDENING_FLOOR_UNPROVEN marker=%s venue=%s "
            "balance=%.2f error=%s:%s trading_fail_closed=true",
            MARKER, broker_key, balance, type(exc).__name__, exc,
        )
        return None


def _resolve_microcap_heartbeat_notional(
    configured: float,
    micro_floor: float,
    hardening_floor: float,
) -> float:
    """Resolve a heartbeat that satisfies both venue and execution hardening."""
    return max(
        0.01,
        float(configured or 0.0),
        max(0.0, float(micro_floor or 0.0)) * 1.25,
        max(0.0, float(hardening_floor or 0.0)),
    )


def _heartbeat_funding_status(
    strategy: Any,
    broker: Any,
) -> tuple[bool, str, float, float, float, str]:
    """Check cached spendable capital against the actual hardened heartbeat size."""
    key = _broker_key(strategy, broker)
    balance, source = _cached_balance(strategy, broker, key)
    if balance is None or balance <= 0.0:
        return False, key, 0.0, 0.0, 0.0, str(source or "unproven")
    resolver = getattr(strategy, "_resolve_heartbeat_trade_amount_usd", None)
    if not callable(resolver):
        return False, key, balance, 0.0, 0.0, "heartbeat_notional_unproven"
    try:
        required = max(0.0, float(resolver(broker) or 0.0))
    except Exception as exc:
        return False, key, balance, 0.0, 0.0, f"heartbeat_notional_error:{type(exc).__name__}"
    spendable = max(0.0, balance * (1.0 - _buffer_pct()))
    return bool(required > 0.0 and spendable + 1e-9 >= required), key, balance, spendable, required, str(source or "cached")


def _verified_heartbeat_context() -> bool:
    if threading.current_thread().name == "HeartbeatTrade":
        return True
    try:
        v236 = importlib.import_module("bot.runtime_heartbeat_final_submit_v236_patch")
        resolver = getattr(v236, "_verified_reason", None)
        if callable(resolver):
            resolved = resolver()
            value = resolved[0] if isinstance(resolved, tuple) and resolved else resolved
            if str(value or "").strip().upper() in _ALLOWED_REASONS:
                return True
        canonical = getattr(v236, "_canonical_verified_probe", None)
        if callable(canonical):
            return str(canonical() or "").strip().upper() in _ALLOWED_REASONS
    except Exception:
        pass
    return False


def _patch_trading_strategy() -> bool:
    module = importlib.import_module("bot.trading_strategy")
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False

    current_resolver = getattr(cls, "_resolve_heartbeat_trade_amount_usd", None)
    if callable(current_resolver) and not getattr(current_resolver, _PATCH_ATTR, False):
        @wraps(current_resolver)
        def _resolve_heartbeat_trade_amount_usd(self: Any, broker: Any) -> float:
            ordinary = float(current_resolver(self, broker))
            if _broker_key(self, broker) != "coinbase":
                return ordinary
            balance, source = _cached_balance(self, broker, "coinbase")
            if balance is None or balance <= 0.0:
                return ordinary
            floor = _coinbase_floor(balance)
            # v341 may only downshift when NIJA's existing micro-cap policy has
            # actually produced a sub-normal Coinbase floor.
            if floor >= 10.0:
                return ordinary
            hardening_floor = _execution_hardening_floor("coinbase", balance)
            if hardening_floor is None or hardening_floor <= 0.0:
                return ordinary
            configured = max(
                0.01,
                float(
                    getattr(
                        self,
                        "_HEARTBEAT_TRADE_AMOUNT_USD",
                        getattr(module, "_HEARTBEAT_TRADE_AMOUNT_USD", 5.0),
                    )
                    or 5.0
                ),
            )
            resolved = _resolve_microcap_heartbeat_notional(
                configured,
                floor,
                hardening_floor,
            )
            LOGGER.critical(
                "HEARTBEAT_MICROCAP_V341_NOTIONAL marker=%s venue=coinbase balance=%.2f "
                "micro_floor=%.2f hardening_floor=%.2f configured=%.2f ordinary=%.2f "
                "resolved=%.2f source=%s cached_balance_only=true "
                "execution_hardening_required=true minimum_notional_gate_required=true "
                "execution_proof_fabricated=false forced_trade=false forced_activation=false "
                "safety_gates_bypassed=false",
                MARKER, balance, floor, hardening_floor, configured, ordinary, resolved, source,
            )
            return resolved

        setattr(_resolve_heartbeat_trade_amount_usd, _PATCH_ATTR, True)
        setattr(cls, "_resolve_heartbeat_trade_amount_usd", _resolve_heartbeat_trade_amount_usd)

    current_eligible = getattr(cls, "_is_broker_eligible_for_entry", None)
    if callable(current_eligible) and not getattr(current_eligible, _PATCH_ATTR, False):
        @wraps(current_eligible)
        def _is_broker_eligible_for_entry(self: Any, broker: Any):
            result = current_eligible(self, broker)
            try:
                allowed = bool(result[0]) if isinstance(result, tuple) else bool(result)
            except Exception:
                allowed = False
            if allowed or threading.current_thread().name != "HeartbeatTrade":
                return result
            if broker is None or _broker_key(self, broker) != "coinbase":
                return result
            if not bool(getattr(broker, "connected", False)) or bool(getattr(broker, "exit_only_mode", False)):
                return result
            if hasattr(broker, "position_tracker") and getattr(broker, "position_tracker") is None:
                return result
            balance, source = _cached_balance(self, broker, "coinbase")
            if balance is None or balance <= 0.0:
                return result
            floor = _coinbase_floor(balance)
            if floor >= 10.0:
                return result
            spendable = max(0.0, balance * (1.0 - _buffer_pct()))
            if spendable + 1e-9 < floor:
                return result
            detail = (
                f"coinbase heartbeat micro-cap eligible spendable=${spendable:.2f} "
                f"cached_balance=${balance:.2f} min=${floor:.2f} source={source}"
            )
            LOGGER.critical(
                "HEARTBEAT_MICROCAP_V341_SELECTION marker=%s %s selection_only=true "
                "ordinary_entries_unchanged=true readiness_granted=false "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER, detail,
            )
            return True, detail

        setattr(_is_broker_eligible_for_entry, _PATCH_ATTR, True)
        # Prevent the older spendable patch from re-wrapping this reconciled method.
        setattr(_is_broker_eligible_for_entry, "_nija_spendable_quote_gate", True)
        setattr(cls, "_is_broker_eligible_for_entry", _is_broker_eligible_for_entry)

    # Reconcile the selected startup venue against the actual heartbeat notional
    # after all runtime wrappers (including v341 hardening) have resolved it.
    # A canonical-ready venue that cannot fund that notional is selection-ineligible
    # for the heartbeat only; ordinary venue readiness and order routing are unchanged.
    current_selector = getattr(cls, "_get_heartbeat_broker", None)
    if callable(current_selector) and not getattr(current_selector, _SELECTOR_ATTR, False):
        @wraps(current_selector)
        def _get_heartbeat_broker(self: Any):
            selected = current_selector(self)
            if threading.current_thread().name != "HeartbeatTrade":
                return selected

            if selected is not None:
                funded, selected_key, balance, spendable, required, source = _heartbeat_funding_status(
                    self, selected
                )
                if funded:
                    return selected
                LOGGER.warning(
                    "HEARTBEAT_MICROCAP_V341_SELECTED_DEFERRED marker=%s venue=%s "
                    "balance=%.2f spendable=%.2f required=%.2f source=%s "
                    "reason=selected_venue_cannot_fund_hardened_heartbeat selection_only=true "
                    "ordinary_entries_unchanged=true readiness_granted=false "
                    "execution_proof_fabricated=false trading_fail_closed=true "
                    "safety_gates_bypassed=false",
                    MARKER, selected_key, balance, spendable, required, source,
                )

            try:
                v274 = importlib.import_module("bot.runtime_heartbeat_live_venue_selection_v274_patch")
                fallback_resolver = getattr(v274, "_live_venue_fallback_set", None)
                candidate_resolver = getattr(v274, "_candidate_brokers", None)
                if not callable(candidate_resolver):
                    return None

                canonical_ready = tuple(
                    dict.fromkeys(
                        part.strip().lower()
                        for part in str(os.environ.get("NIJA_EXECUTION_READY_VENUES", "") or "").split(",")
                        if part.strip()
                    )
                )
                if canonical_ready:
                    allowed_venues = canonical_ready
                    fallback_reason = "canonical_ready_funding_reselection"
                else:
                    if not callable(fallback_resolver):
                        return None
                    allowed, allowed_venues, fallback_reason = fallback_resolver()
                    if not allowed:
                        return None
                candidates = dict(candidate_resolver(self) or {})
            except Exception:
                return None

            allowed_set = set(allowed_venues)
            funded_candidates: dict[Any, Any] = {}
            funding_status: dict[str, str] = {}
            eligible_fn = getattr(self, "_is_broker_eligible_for_entry", None)

            for raw_key, broker in candidates.items():
                if broker is None:
                    continue
                key = _broker_key(self, broker)
                if allowed_set and key not in allowed_set:
                    continue
                funded, _key, balance, spendable, required, source = _heartbeat_funding_status(
                    self, broker
                )
                if not funded:
                    funding_status[key] = (
                        f"underfunded:balance={balance:.2f}:spendable={spendable:.2f}:"
                        f"required={required:.2f}:source={source}"
                    )
                    continue
                if not callable(eligible_fn):
                    funding_status[key] = "entry_eligibility_unavailable"
                    continue
                try:
                    eligible, detail = eligible_fn(broker)
                except Exception as exc:
                    funding_status[key] = f"entry_eligibility_error:{type(exc).__name__}"
                    continue
                if not eligible:
                    funding_status[key] = f"entry_ineligible:{detail}"
                    continue
                funding_status[key] = (
                    f"funded:balance={balance:.2f}:spendable={spendable:.2f}:"
                    f"required={required:.2f}:source={source}"
                )
                funded_candidates[raw_key] = broker

            if not funded_candidates:
                LOGGER.error(
                    "HEARTBEAT_MICROCAP_V341_SELECTOR_NONE marker=%s allowed=%s status=%s "
                    "reason=%s selection_only=true broker_io=false trading_fail_closed=true "
                    "readiness_granted=false execution_proof_fabricated=false forced_trade=false "
                    "forced_activation=false safety_gates_bypassed=false",
                    MARKER, ",".join(allowed_venues), funding_status, fallback_reason,
                )
                return None

            selector = getattr(self, "_select_entry_broker", None)
            if not callable(selector):
                return None
            try:
                fallback, name, status = selector(funded_candidates)
            except Exception as exc:
                LOGGER.warning(
                    "HEARTBEAT_MICROCAP_V341_SELECTOR_ERROR marker=%s error=%s:%s "
                    "selection_only=true trading_fail_closed=true",
                    MARKER, type(exc).__name__, exc,
                )
                return None
            if fallback is None:
                LOGGER.warning(
                    "HEARTBEAT_MICROCAP_V341_SELECTOR_UNAVAILABLE marker=%s status=%s "
                    "funding_status=%s selection_only=true trading_fail_closed=true",
                    MARKER, status or "no_funded_candidate", funding_status,
                )
                return None

            self.broker = fallback
            broker_manager = getattr(self, "broker_manager", None)
            if broker_manager is not None:
                try:
                    broker_manager.active_broker = fallback
                except Exception:
                    pass
            funded, key, balance, spendable, required, source = _heartbeat_funding_status(
                self, fallback
            )
            LOGGER.critical(
                "HEARTBEAT_MICROCAP_V341_SELECTOR_BRIDGE marker=%s selected=%s "
                "balance=%.2f spendable=%.2f required=%.2f source=%s allowed=%s "
                "reason=%s eligibility=%s selection_only=true "
                "ordinary_active_venue_publication_unchanged=true "
                "global_venue_readiness_not_mutated=true downstream_capital_authorization_required=true "
                "ecel_risk_writer_nonce_killswitch_min_notional_order_ack_fill_gates_unchanged=true "
                "readiness_granted=false execution_proof_fabricated=false forced_trade=false "
                "forced_activation=false safety_gates_bypassed=false",
                MARKER, key or name, balance, spendable, required, source,
                ",".join(allowed_venues), fallback_reason, funding_status.get(key, "funded"),
            )
            return fallback

        setattr(_get_heartbeat_broker, _SELECTOR_ATTR, True)
        setattr(_get_heartbeat_broker, _PATCH_ATTR, True)
        # Preserve v274 idempotence on repeated install passes. v341 wraps the
        # already-installed v274 selector and must remain the terminal selector.
        setattr(_get_heartbeat_broker, "_nija_heartbeat_live_venue_selection_v274", True)
        setattr(cls, "_get_heartbeat_broker", _get_heartbeat_broker)

    resolver_ready = bool(getattr(getattr(cls, "_resolve_heartbeat_trade_amount_usd", None), _PATCH_ATTR, False))
    eligible_ready = bool(getattr(getattr(cls, "_is_broker_eligible_for_entry", None), _PATCH_ATTR, False))
    selector_ready = bool(getattr(getattr(cls, "_get_heartbeat_broker", None), _SELECTOR_ATTR, False))
    return bool(resolver_ready and eligible_ready and selector_ready)


def _patch_execution_engine() -> bool:
    module = importlib.import_module("bot.execution_engine")
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_apply_minimum_notional_gate", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def _apply_minimum_notional_gate(
        self: Any,
        *,
        symbol: str,
        position_size: float,
        broker_name: str | None,
        balance_usd: float,
        affordable_usd: float | None,
    ):
        broker_key = str(broker_name or "").strip().lower()
        if "coinbase" not in broker_key or not _verified_heartbeat_context():
            return current(
                self,
                symbol=symbol,
                position_size=position_size,
                broker_name=broker_name,
                balance_usd=balance_usd,
                affordable_usd=affordable_usd,
            )

        balance = max(0.0, float(balance_usd or 0.0))
        floor = _coinbase_floor(balance)
        if balance <= 0.0 or floor >= 10.0:
            return current(
                self,
                symbol=symbol,
                position_size=position_size,
                broker_name=broker_name,
                balance_usd=balance_usd,
                affordable_usd=affordable_usd,
            )

        affordable = (
            max(0.0, float(affordable_usd or 0.0))
            if affordable_usd is not None
            else max(0.0, balance * (1.0 - _buffer_pct()))
        )
        if affordable + 1e-9 < floor:
            return None, (
                f"Coinbase micro-cap executable minimum ${floor:.2f} exceeds "
                f"spendable ${affordable:.2f}; heartbeat remains fail-closed"
            )

        gate_mod = importlib.import_module("bot.minimum_notional_gate")
        getter = getattr(gate_mod, "get_minimum_notional_gate", None)
        gate = getter() if callable(getter) else None
        if gate is None:
            return None, "Coinbase micro-cap minimum-notional gate unavailable"

        size = max(0.0, float(position_size or 0.0))
        validator = getattr(gate, "validate_entry_size", None)
        if not callable(validator):
            return None, "Coinbase micro-cap minimum-notional validator unavailable"
        valid, reason = validator(
            symbol=symbol,
            size_usd=size,
            is_stop_loss=False,
            broker_name="coinbase",
            balance=balance,
        )
        if valid:
            LOGGER.critical(
                "HEARTBEAT_MICROCAP_V341_MIN_NOTIONAL_PASS marker=%s symbol=%s size=%.2f "
                "balance=%.2f spendable=%.2f floor=%.2f canonical_gate=true "
                "ecel_risk_writer_nonce_killswitch_order_fill_gates_unchanged=true "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER, symbol, size, balance, affordable, floor,
            )
            return size, None

        adjuster = getattr(gate, "adjust_size_to_minimum", None)
        if callable(adjuster):
            adjusted = float(adjuster(size, broker_name="coinbase", balance=balance) or 0.0)
            if adjusted > size and adjusted <= affordable + 1e-9:
                return adjusted, None
        return None, str(reason or "Coinbase micro-cap minimum-notional rejection")

    setattr(_apply_minimum_notional_gate, _PATCH_ATTR, True)
    # Prevent the older spendable wrapper from being re-applied over v341.
    setattr(_apply_minimum_notional_gate, "_nija_spendable_min_notional_detail", True)
    setattr(cls, "_apply_minimum_notional_gate", _apply_minimum_notional_gate)
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["heartbeat_microcap_proof_v341"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    try:
        strategy_ready = _patch_trading_strategy()
        engine_ready = _patch_execution_engine()
        manifest_ready = _register_manifest()
        ready = bool(strategy_ready and engine_ready and manifest_ready)
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_MICROCAP_V341_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc, exc_info=True,
        )
        ready, strategy_ready, engine_ready, manifest_ready = False, False, False, False
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "HEARTBEAT_MICROCAP_V341_READY marker=%s ready=true "
            "coinbase_microcap_existing_policy_only=true heartbeat_only=true cached_balance_only=true "
            "heartbeat_selector_bridge=true ordinary_active_venue_publication_unchanged=true "
            "ordinary_entries_unchanged=true canonical_min_notional_required=true "
            "ecel_risk_writer_nonce_killswitch_order_ack_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_trade=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_coinbase_floor",
    "_verified_heartbeat_context",
]
