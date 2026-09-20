"""Canonical market-order submission through ExecutionPipeline/ECEL.

The submitter preserves the exact broker adapter and account identity.  Kraken
entries may be upgraded to qualified margin orders; exits can explicitly declare
``intent_type=exit`` and ``position_effect=close`` so they are never interpreted
as new short entries or sized from platform capital.
"""

from __future__ import annotations

import importlib
import logging
import math
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.pipeline_order_submitter")

try:
    from bot.execution_pipeline import PipelineRequest, get_execution_pipeline
except ImportError:
    try:
        from execution_pipeline import PipelineRequest, get_execution_pipeline
    except ImportError:
        PipelineRequest = None  # type: ignore[assignment]
        get_execution_pipeline = None  # type: ignore[assignment]

try:
    from bot.execution_authority_context import assert_distributed_writer_authority
except ImportError:
    try:
        from execution_authority_context import assert_distributed_writer_authority
    except ImportError:
        def assert_distributed_writer_authority() -> None:
            raise RuntimeError("execution authority module unavailable")


_HEARTBEAT_PROBE_STRATEGIES = {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}
_PIPELINE_DEPENDENCY_LOCK = threading.Lock()


def _resolve_execution_pipeline_dependencies() -> tuple[Any, Any]:
    """Recover dependencies that may be unavailable during circular startup.

    The module-level import remains the fast path.  If package initialization
    imported this submitter while ``bot.execution_pipeline`` was only partially
    initialized, retry after startup instead of permanently treating the
    execution path as unavailable.  Existing injected/mocked dependencies are
    preserved independently.
    """
    global PipelineRequest, get_execution_pipeline

    with _PIPELINE_DEPENDENCY_LOCK:
        if PipelineRequest is not None and get_execution_pipeline is not None:
            return PipelineRequest, get_execution_pipeline

        failures = []
        for module_name in ("bot.execution_pipeline", "execution_pipeline"):
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                failures.append(f"{module_name}:{type(exc).__name__}")
                continue

            candidate_request = (
                PipelineRequest if PipelineRequest is not None else getattr(module, "PipelineRequest", None)
            )
            candidate_getter = (
                get_execution_pipeline
                if get_execution_pipeline is not None
                else getattr(module, "get_execution_pipeline", None)
            )
            if candidate_request is None or candidate_getter is None:
                failures.append(f"{module_name}:partial_module")
                continue

            # Commit the pair atomically. Never cache one symbol from a partially
            # initialized alias because a later import could combine incompatible
            # request and pipeline implementations.
            PipelineRequest = candidate_request
            get_execution_pipeline = candidate_getter
            return PipelineRequest, get_execution_pipeline

    logger.error("EXECUTION_PIPELINE_LAZY_IMPORT_FAILED failures=%s", ",".join(failures))
    return PipelineRequest, get_execution_pipeline


def _truthy(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "enabled", "on", "y"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _balance_from_payload(payload: Any) -> Optional[float]:
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, dict):
        for key in (
            "available_balance", "available_usd", "available", "free", "free_usd",
            "trading_balance", "total_balance", "total_funds", "balance", "equity",
            "usd_balance", "total_usd",
        ):
            if key in payload:
                return _float(payload.get(key))
    return None


def _resolve_preferred_broker(broker: Any) -> str:
    broker_type = getattr(broker, "broker_type", None)
    raw = getattr(broker_type, "value", broker_type)
    text = str(raw or "").strip().lower()
    if text:
        return text
    values = (getattr(broker, "NAME", ""), type(broker).__name__)
    for value in values:
        lowered = str(value or "").lower()
        for candidate in ("kraken", "coinbase", "okx", "binance", "alpaca"):
            if candidate in lowered:
                return candidate
    return "coinbase"


def _resolve_account_id(broker: Any, preferred_broker: str) -> str:
    for attr in ("account_identifier", "account_id", "user_id", "owner_id", "name"):
        value = str(getattr(broker, attr, "") or "").strip().lower()
        if value and value not in {"none", preferred_broker}:
            return value
    return "platform" if preferred_broker == "kraken" else "default"


def _resolve_balance_keys(broker: Any, preferred_broker: str, account_id: str) -> list[str]:
    keys: list[str] = []
    account = str(account_id or "").strip().lower()
    if account and account not in {"default", "platform", preferred_broker}:
        keys.extend((f"{preferred_broker}:{account}", f"{preferred_broker}:user:{account}"))
    identity = str(getattr(broker, "account_identifier", "") or "").strip().lower()
    if identity and identity not in {"default", "platform", preferred_broker}:
        keys.append(f"{preferred_broker}:{identity}")
    keys.append(preferred_broker)
    return list(dict.fromkeys(key for key in keys if key))


def _resolve_available_balance(
    broker: Any,
    preferred_broker: str,
    account_id: str,
) -> Optional[float]:
    cached = _balance_from_payload(getattr(broker, "_balance_cache", None))
    if cached is None:
        scalar = getattr(broker, "_last_known_balance", None)
        if isinstance(scalar, (int, float)):
            cached = float(scalar)

    # Prefer account-specific authority records.  The plain Kraken key remains a
    # fallback for the platform account only; it must never size a user order.
    try:
        import importlib
        for module_name in ("bot.capital_authority", "capital_authority"):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            get_authority = getattr(module, "get_capital_authority", None)
            if not callable(get_authority):
                break
            authority = get_authority()
            is_registered = getattr(authority, "is_registered", None)
            for key in _resolve_balance_keys(broker, preferred_broker, account_id):
                if account_id not in {"platform", "default"} and key == preferred_broker:
                    continue
                amount = _float(authority.get_per_broker(key))
                if amount > 0 or (callable(is_registered) and is_registered(key)):
                    logger.info(
                        "PIPELINE_ACCOUNT_BALANCE_RESOLVED broker_key=%s account=%s balance=$%.2f",
                        key, account_id, amount,
                    )
                    return amount
            break
    except Exception as exc:
        logger.debug("account authority balance lookup failed: %s", exc)

    if cached is not None:
        return cached
    try:
        getter = getattr(broker, "get_account_balance", None)
        if callable(getter):
            payload = getter()
            parsed = _balance_from_payload(payload)
            return parsed if parsed is not None else _float(payload)
    except Exception:
        pass
    return None


def _risk_bounded_heartbeat_size(
    broker: Any,
    requested_usd: float,
    available_balance_usd: Optional[float],
) -> float:
    """Downsize only the Kraken startup BUY probe without weakening risk gates.

    The downstream GlobalRiskGovernor remains authoritative.  This helper merely
    avoids constructing a heartbeat notional that is known in advance to exceed
    the governor's 25% ceiling.  The probe keeps a buffer below that ceiling and
    never goes below Kraken's already-published minimum trade size.  If both
    constraints cannot be satisfied, the original amount is preserved so the
    unchanged downstream risk/minimum gates fail closed.
    """
    requested = max(0.0, _float(requested_usd))
    balance = max(0.0, _float(available_balance_usd))
    if requested <= 0.0 or balance <= 0.0:
        return requested

    try:
        fraction = float(os.environ.get("NIJA_HEARTBEAT_RISK_FRACTION", "0.23") or 0.23)
    except (TypeError, ValueError):
        fraction = 0.23
    fraction = max(0.01, min(0.24, fraction))
    risk_cap = balance * fraction

    broker_min = max(0.0, _float(getattr(broker, "min_trade_size", 0.0)))
    # Preserve the same $10 absolute heartbeat floor used by TradingStrategy,
    # while adding only a 1% rounding cushion to the actual broker minimum.
    safe_floor = max(10.0, broker_min * 1.01)
    if safe_floor > risk_cap + 1e-9:
        logger.warning(
            "KRAKEN_HEARTBEAT_RISK_SIZE_DEFERRED requested=%.2f balance=%.2f "
            "risk_fraction=%.4f risk_cap=%.2f broker_min=%.2f safe_floor=%.2f "
            "reason=no_notional_satisfies_both_constraints downstream_gates_unchanged=true "
            "trading_fail_closed=true safety_gates_bypassed=false",
            requested, balance, fraction, risk_cap, broker_min, safe_floor,
        )
        return requested

    bounded = max(safe_floor, min(requested, risk_cap))
    if bounded + 1e-9 < requested:
        logger.critical(
            "KRAKEN_HEARTBEAT_RISK_SIZE_BOUNDED requested=%.2f resolved=%.2f balance=%.2f "
            "risk_fraction=%.4f risk_cap=%.2f broker_min=%.2f safe_floor=%.2f "
            "heartbeat_only=true downstream_risk_governor_required=true minimum_notional_required=true "
            "ordinary_orders_unchanged=true execution_proof_fabricated=false forced_activation=false "
            "safety_gates_bypassed=false",
            requested, bounded, balance, fraction, risk_cap, broker_min, safe_floor,
        )
    return bounded


def _resolve_margin_exit(preferred_broker: str, account_id: str, symbol: str) -> Dict[str, Any]:
    if preferred_broker != "kraken":
        return {}
    try:
        from bot.margin_position_ledger import get_margin_position_ledger
        row = get_margin_position_ledger().get_record(
            broker="kraken",
            account_id=account_id,
            subaccount_id="",
            symbol=str(symbol or "").strip().upper(),
            asset_class="crypto",
        )
    except Exception as exc:
        logger.debug(
            "KRAKEN_MARGIN_EXIT_LEDGER_LOOKUP_FAILED account=%s symbol=%s error=%s",
            account_id, symbol, exc,
        )
        return {}
    leverage = int(_float((row or {}).get("leverage"), 1.0))
    lifecycle = str((row or {}).get("lifecycle_status") or "").lower()
    if leverage <= 1 or lifecycle not in {"open", "reducing", "pending_open"}:
        return {}
    return {
        "leverage": min(3, max(2, leverage)),
        "margin_mode": str(row.get("margin_mode") or "cross"),
        "reduce_only": True,
        "intent_type": "exit",
        "buying_power_usd": row.get("buying_power_usd"),
        "reason": f"existing_margin_position:{lifecycle}",
    }


def _plan_margin_entry(
    broker: Any,
    account_id: str,
    symbol: str,
    side: str,
    size_usd: float,
    account_equity_usd: float,
) -> Dict[str, Any]:
    if side != "buy" or not _truthy("NIJA_KRAKEN_MARGIN_ENABLED", True):
        return {}
    if not _truthy("NIJA_KRAKEN_AUTO_MARGIN_ENABLED", True):
        return {}
    try:
        from bot.kraken_margin_engine import get_margin_engine
        plan = get_margin_engine(account_id=account_id, adapter=broker).plan_auto_margin(
            adapter=broker,
            symbol=symbol,
            side=side,
            spot_size_usd=size_usd,
            account_equity_usd=account_equity_usd,
            requested_leverage=None,
            is_reducing=False,
        )
    except Exception as exc:
        logger.warning(
            "KRAKEN_MARGIN_AUTO_PLAN account=%s symbol=%s decision=SPOT reason=engine_error:%s",
            account_id, symbol, exc,
        )
        return {}
    if not plan.allowed:
        logger.info(
            "KRAKEN_MARGIN_AUTO_PLAN account=%s symbol=%s decision=SPOT reason=%s pair_max=%sx",
            account_id, symbol, plan.reason, plan.pair_max_leverage,
        )
        return {}
    logger.critical(
        "KRAKEN_MARGIN_AUTO_PLAN account=%s symbol=%s decision=MARGIN leverage=%sx "
        "spot_notional=$%.2f leveraged_notional=$%.2f buying_power=$%.2f",
        account_id, symbol, plan.leverage, plan.spot_notional_usd,
        plan.leveraged_notional_usd, plan.buying_power_usd,
    )
    return {
        "leverage": plan.leverage,
        "margin_mode": plan.margin_mode,
        "reduce_only": False,
        "intent_type": "entry",
        "size_usd": plan.leveraged_notional_usd,
        "buying_power_usd": plan.buying_power_usd,
        "reason": plan.reason,
        "pair_max_leverage": plan.pair_max_leverage,
        "spot_notional_usd": plan.spot_notional_usd,
    }


def _classify_failed_submission(result: Any) -> str:
    """Classify a failed execution result without permitting blind resubmission."""
    broker_order_id = str(getattr(result, "order_id", "") or "").strip()
    if broker_order_id:
        return "pending"
    error_text = str(getattr(result, "error", "") or "").lower()
    if any(token in error_text for token in (
        "timeout", "timed out", "ack", "unknown", "reconcile", "dispatch",
    )):
        return "state_unknown"
    return "error"


def _v2_duplicate_metadata_state(metadata: Dict[str, Any]) -> str:
    """Return absent/complete/partial for V2 duplicate handoff metadata."""
    data = metadata or {}
    present = {
        "duplicate_key": bool(str(data.get("duplicate_key") or "").strip()),
        "duplicate_token": bool(str(data.get("duplicate_token") or "").strip()),
    }
    shared_present = "duplicate_shared_required" in data
    if not present["duplicate_key"] and not present["duplicate_token"] and not shared_present:
        return "absent"
    if present["duplicate_key"] and present["duplicate_token"]:
        return "complete"
    return "partial"


def _finalize_v2_duplicate(metadata: Dict[str, Any], state: str) -> bool:

    """Finalize a held V2 reservation from authoritative submission outcome."""
    metadata_state = _v2_duplicate_metadata_state(metadata)
    if metadata_state == "absent":
        return True
    if metadata_state == "partial":
        logger.critical("V2_DUPLICATE_METADATA_INCOMPLETE stage=finalize fail_closed=true")
        return False
    try:
        from bot.control.decision_context import (
            IdempotencyReservationHandle,
            get_user_scoped_idempotency_registry,
        )
        handle = IdempotencyReservationHandle.from_metadata(metadata or {})
        if not handle:
            return False
        registry = get_user_scoped_idempotency_registry()
        if state == "released":
            return bool(registry.release(handle))
        return bool(registry.mark_state(handle, state))
    except Exception as exc:
        # Fail closed: inability to finalize must not trigger a blind resubmit.
        duplicate_key = str((metadata or {}).get("duplicate_key") or "").strip()
        logger.error("V2_DUPLICATE_FINALIZE_FAILED key=%s state=%s error=%s", duplicate_key, state, exc)
        return False



def _finalize_pre_submit_v2_duplicate(metadata: Dict[str, Any]) -> bool:
    """Retain for broadcaster-managed retries; otherwise release proven pre-submit attempts."""
    if _v2_duplicate_metadata_state(metadata) == "absent":
        return True
    retry_managed = bool((metadata or {}).get("duplicate_retry_managed", False))
    return _finalize_v2_duplicate(metadata, "submitted" if retry_managed else "released")


def _prepare_v2_duplicate_handoff(metadata: Dict[str, Any]) -> bool:
    """Durably extend a V2 reservation before any broker-dispatch-capable call."""
    metadata_state = _v2_duplicate_metadata_state(metadata)
    if metadata_state == "absent":
        return True
    if metadata_state == "partial":
        logger.critical("V2_DUPLICATE_METADATA_INCOMPLETE stage=handoff fail_closed=true")
        return False
    try:
        from bot.control.decision_context import (
            IdempotencyReservationHandle,
            get_user_scoped_idempotency_registry,
        )
        handle = IdempotencyReservationHandle.from_metadata(metadata or {})
        if not handle:
            return False
        registry = get_user_scoped_idempotency_registry()
        ok = registry.mark_state(handle, "submitted_pending")
        if not ok:
            logger.critical(
                "V2_DUPLICATE_HANDOFF_UNCONFIRMED key=%s fail_closed=true",
                handle.key,
            )
        return bool(ok)
    except Exception as exc:
        logger.error("V2_DUPLICATE_HANDOFF_FAILED error=%s", exc)
        return False


def submit_market_order_via_pipeline(
    broker: Any,
    symbol: str,
    side: str,
    quantity: float,
    size_type: str = "quote",
    strategy: str = "PipelineOrderSubmitter",
    *,
    intent_type: Optional[str] = None,
    account_id_override: Optional[str] = None,
    reduce_only_override: Optional[bool] = None,
    position_effect: Optional[str] = None,
    metadata_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Submit a market order while preserving explicit account/exit context."""
    incoming_metadata = dict(metadata_override or {})
    if _v2_duplicate_metadata_state(incoming_metadata) == "partial":
        return {
            "status": "error",
            "error": "v2_duplicate_metadata_incomplete",
            "symbol": symbol,
            "side": side,
            "v2_pre_submit_proven": True,
        }
    strategy_norm = str(strategy or "").strip().upper()
    protection: Dict[str, float] = {}
    for field_name in ("stop_loss_pct", "take_profit_pct"):
        raw_value = incoming_metadata.get(field_name)
        if raw_value is None:
            continue
        parsed = _float(raw_value, float("nan"))
        if not math.isfinite(parsed) or parsed <= 0.0:
            return {
                "status": "error",
                "error": f"invalid_v2_protection:{field_name}",
                "symbol": symbol,
                "side": side,
                "v2_pre_submit_proven": True,
            }
        protection[field_name] = parsed
    if strategy_norm == "BREAK_RETEST" and set(protection) != {"stop_loss_pct", "take_profit_pct"}:
        return {
            "status": "error",
            "error": "break_retest_protection_required",
            "symbol": symbol,
            "side": side,
            "v2_pre_submit_proven": True,
        }
    request_type, pipeline_getter = _resolve_execution_pipeline_dependencies()
    if pipeline_getter is None or request_type is None:
        _finalize_pre_submit_v2_duplicate(incoming_metadata)
        return {"status": "error", "error": "ExecutionPipeline unavailable", "symbol": symbol, "side": side, "v2_pre_submit_proven": True}

    try:
        assert_distributed_writer_authority()
    except Exception as exc:
        _finalize_pre_submit_v2_duplicate(incoming_metadata)
        return {
            "status": "error",
            "error": f"DistributedWriterFence reject: {exc}",
            "symbol": symbol,
            "side": side,
            "v2_pre_submit_proven": True,
        }

    side_norm = str(side or "buy").strip().lower()
    heartbeat_probe = strategy_norm in _HEARTBEAT_PROBE_STRATEGIES
    preferred_broker = _resolve_preferred_broker(broker)
    account_id = str(account_id_override or _resolve_account_id(broker, preferred_broker)).strip().lower()
    explicit_intent = str(intent_type or "").strip().lower()
    is_exit = explicit_intent in {"exit", "reduce"} or str(position_effect or "").lower() in {"close", "reduce"}

    size_usd = max(0.0, _float(quantity))
    price_hint_usd: Optional[float] = None
    base_quantity: Optional[float] = None
    if str(size_type or "quote").lower() == "base":
        base_quantity = max(0.0, _float(quantity))
        try:
            price_hint_usd = _float(getattr(broker, "get_current_price")(symbol))
        except Exception:
            price_hint_usd = 0.0
        if price_hint_usd <= 0:
            _finalize_pre_submit_v2_duplicate(incoming_metadata)
            return {
                "status": "error",
                "error": "Cannot compile base-size order without valid price hint",
                "symbol": symbol,
                "side": side_norm,
                "account_id": account_id,
                "v2_pre_submit_proven": True,
            }
        size_usd = max(0.0, _float(quantity) * price_hint_usd)

    available_balance = _resolve_available_balance(broker, preferred_broker, account_id)
    margin_fields: Dict[str, Any] = {}
    if preferred_broker == "kraken":
        if heartbeat_probe:
            if side_norm == "buy" and not is_exit and str(size_type or "quote").lower() != "base":
                size_usd = _risk_bounded_heartbeat_size(broker, size_usd, available_balance)
            logger.critical(
                "KRAKEN_HEARTBEAT_SPOT_PROBE strategy=%s account=%s symbol=%s "
                "auto_margin_bypassed=true leverage=1x ordinary_kraken_margin_unchanged=true "
                "writer_nonce_risk_capital_killswitch_min_notional_order_fill_gates_unchanged=true "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                strategy_norm, account_id, symbol,
            )
        elif side_norm == "buy" and not is_exit:
            margin_fields = _plan_margin_entry(
                broker, account_id, symbol, side_norm, size_usd, _float(available_balance),
            )
        elif side_norm == "sell":
            margin_fields = _resolve_margin_exit(preferred_broker, account_id, symbol)

    effective_size = _float(margin_fields.get("size_usd"), size_usd)
    leverage = int(_float(margin_fields.get("leverage"), 1.0))
    margin_mode = margin_fields.get("margin_mode")
    resolved_intent = explicit_intent or str(margin_fields.get("intent_type") or "entry")
    reduce_only = margin_fields.get("reduce_only")
    if reduce_only_override is not None:
        reduce_only = bool(reduce_only_override)
    if resolved_intent in {"exit", "reduce"} and leverage > 1:
        reduce_only = True
    if reduce_only is None:
        reduce_only = False

    metadata = {
        "broker_client": broker,
        "broker_name": preferred_broker,
        "account_id": account_id,
        "closing_position": resolved_intent in {"exit", "reduce"},
        "kraken_margin_auto": bool(margin_fields and leverage > 1),
        "kraken_margin_reason": margin_fields.get("reason", "spot"),
        "spot_notional_usd": margin_fields.get("spot_notional_usd", size_usd),
        "pair_max_leverage": margin_fields.get("pair_max_leverage", 1),
        "leverage": leverage,
        "reduce_only": reduce_only,
        "margin_mode": margin_mode,
        # Preserve the explicit base-asset quantity end-to-end so the broker
        # terminal never has to reconstruct base_size from a USD notional.
        "size_type": str(size_type or "quote").lower(),
        "intent_type": resolved_intent,
        "position_effect": position_effect or ("close" if resolved_intent in {"exit", "reduce"} else None),
        "price_hint_usd": price_hint_usd,
    }
    if base_quantity is not None and base_quantity > 0:
        metadata["base_quantity"] = base_quantity
        metadata["owned_base_qty"] = base_quantity
    metadata.update(incoming_metadata)
    metadata.update(protection)
    if protection:
        metadata["protection_required"] = True

    request = request_type(
        strategy=strategy,
        symbol=symbol,
        side=side_norm,
        size_usd=effective_size,
        order_type="market",
        preferred_broker=preferred_broker,
        price_hint_usd=price_hint_usd,
        available_balance_usd=available_balance,
        buying_power_usd=margin_fields.get("buying_power_usd"),
        account_id=account_id,
        intent_type=resolved_intent,
        position_effect=position_effect or ("close" if resolved_intent in {"exit", "reduce"} else None),
        leverage=leverage if leverage > 1 else None,
        margin_mode=margin_mode,
        reduce_only=bool(reduce_only),
        units=base_quantity if (base_quantity or 0) > 0 else None,
        unit_type="base" if (base_quantity or 0) > 0 else None,
        stop_loss_pct=protection.get("stop_loss_pct"),
        take_profit_pct=protection.get("take_profit_pct"),
        metadata=metadata,
    )

    logger.critical(
        "PIPELINE_ORDER_CONTEXT account=%s broker=%s symbol=%s side=%s intent=%s "
        "position_effect=%s leverage=%sx reduce_only=%s notional=$%.2f",
        account_id, preferred_broker, symbol, side_norm, resolved_intent,
        request.position_effect, leverage, bool(reduce_only), effective_size,
    )
    # Before entering the broker-dispatch-capable execution pipeline, extend
    # the exact V2 reservation under its ownership token.  If shared authority
    # cannot durably confirm this handoff, do not dispatch.
    if not _prepare_v2_duplicate_handoff(metadata):
        return {
            "status": "error",
            "error": "v2_duplicate_handoff_unconfirmed",
            "symbol": symbol,
            "side": side_norm,
            "account_id": account_id,
            "intent_type": resolved_intent,
        }
    try:
        if preferred_broker == "kraken":
            from bot.kraken_margin_engine import margin_account_scope
            with margin_account_scope(account_id, adapter=broker):
                result = pipeline_getter().execute(request)
        else:
            result = pipeline_getter().execute(request)
    except Exception as exc:
        _finalize_v2_duplicate(metadata, "state_unknown")
        return {
            "status": "state_unknown", "error": str(exc), "symbol": symbol,
            "side": side_norm, "account_id": account_id, "leverage": leverage,
        }

    broker_order_id = str(getattr(result, "order_id", "") or "").strip()
    if not result.success:
        error_text = str(getattr(result, "error", "") or "").lower()
        known_pre_submit = any(token in error_text for token in (
            "dispatch_disabled", "dispatch.enabled=false", "internal_dispatch_failure",
            "writer", "fence", "validation", "risk reject", "rejected before dispatch",
        ))
        if broker_order_id:
            _finalize_v2_duplicate(metadata, "submitted_pending")
            status = "pending"
        elif known_pre_submit:
            # Release only when the pipeline proves the broker was never
            # contacted. Every other no-order-id failure is submission-uncertain
            # and must remain reserved until reconciliation proves otherwise.
            # Retain the same ownership token through broadcaster retries.
            # Revert to the short pre-dispatch TTL; release only after retries
            # are exhausted or the caller explicitly abandons the attempt.
            _finalize_pre_submit_v2_duplicate(metadata)
            status = "error"
        else:
            _finalize_v2_duplicate(metadata, "state_unknown")
            status = "state_unknown"
        return {
            "status": status,
            "error": result.error or "ExecutionPipeline rejected order",
            "symbol": symbol,
            "side": side_norm,
            "account_id": account_id,
            "order_id": broker_order_id,
            "leverage": leverage,
            "margin": leverage > 1,
            "intent_type": resolved_intent,
            "v2_pre_submit_proven": bool(known_pre_submit and not broker_order_id),
        }
    fill_price = _float(getattr(result, "fill_price", 0.0))
    filled_size_usd = _float(getattr(result, "filled_size_usd", 0.0))

    # A successful submission requires genuine acknowledgment evidence.  Never
    # fabricate an order ID or a fill: without a real fill price the caller must
    # reconcile, not assume the position was closed.
    if fill_price <= 0.0 or filled_size_usd <= 0.0:
        logger.error(
            "PIPELINE_ORDER_UNACKNOWLEDGED account=%s broker=%s symbol=%s side=%s "
            "order_id=%s fill_price=%.10f filled_size_usd=%.8f fill_fabricated=false",
            account_id, preferred_broker, symbol, side_norm,
            broker_order_id or "none", fill_price, filled_size_usd,
        )
        _finalize_v2_duplicate(metadata, "submitted_pending" if broker_order_id else "state_unknown")
        return {
            "status": "pending" if broker_order_id else "state_unknown",
            "error": "unacknowledged_submission: confirmed fill price and quantity required",
            "symbol": symbol,
            "side": side_norm,
            "account_id": account_id,
            "order_id": broker_order_id,
            "intent_type": resolved_intent,
        }

    payload: Dict[str, Any] = {
        "status": "filled",
        "symbol": symbol,
        "side": side_norm,
        "account_id": account_id,
        "filled_price": fill_price,
        "filled_size_usd": filled_size_usd,
        "broker": result.broker,
        "leverage": leverage,
        "margin": leverage > 1,
        "reduce_only": bool(reduce_only),
        "intent_type": resolved_intent,
    }
    if broker_order_id:
        payload["order_id"] = broker_order_id
    _finalize_v2_duplicate(metadata, "reconciled_filled")
    return payload


__all__ = ["submit_market_order_via_pipeline"]
