"""Canonical market-order submission through ExecutionPipeline/ECEL.

The submitter preserves the exact broker adapter and account identity.  Kraken
entries may be upgraded to qualified margin orders; exits can explicitly declare
``intent_type=exit`` and ``position_effect=close`` so they are never interpreted
as new short entries or sized from platform capital.
"""

from __future__ import annotations

import logging
import os
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
            return None


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
    if get_execution_pipeline is None or PipelineRequest is None:
        return {"status": "error", "error": "ExecutionPipeline unavailable", "symbol": symbol, "side": side}

    if not (_truthy("FORCE_TRADE") or _truthy("FORCE_TRADE_MODE")):
        try:
            assert_distributed_writer_authority()
        except Exception as exc:
            return {
                "status": "error",
                "error": f"DistributedWriterFence reject: {exc}",
                "symbol": symbol,
                "side": side,
            }

    side_norm = str(side or "buy").strip().lower()
    preferred_broker = _resolve_preferred_broker(broker)
    account_id = str(account_id_override or _resolve_account_id(broker, preferred_broker)).strip().lower()
    explicit_intent = str(intent_type or "").strip().lower()
    is_exit = explicit_intent in {"exit", "reduce"} or str(position_effect or "").lower() in {"close", "reduce"}

    size_usd = max(0.0, _float(quantity))
    price_hint_usd: Optional[float] = None
    if str(size_type or "quote").lower() == "base":
        try:
            price_hint_usd = _float(getattr(broker, "get_current_price")(symbol))
        except Exception:
            price_hint_usd = 0.0
        if price_hint_usd <= 0:
            return {
                "status": "error",
                "error": "Cannot compile base-size order without valid price hint",
                "symbol": symbol,
                "side": side_norm,
                "account_id": account_id,
            }
        size_usd = max(0.0, _float(quantity) * price_hint_usd)

    available_balance = _resolve_available_balance(broker, preferred_broker, account_id)
    margin_fields: Dict[str, Any] = {}
    if preferred_broker == "kraken":
        if side_norm == "buy" and not is_exit:
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
    }
    metadata.update(dict(metadata_override or {}))

    request = PipelineRequest(
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
        metadata=metadata,
    )

    logger.critical(
        "PIPELINE_ORDER_CONTEXT account=%s broker=%s symbol=%s side=%s intent=%s "
        "position_effect=%s leverage=%sx reduce_only=%s notional=$%.2f",
        account_id, preferred_broker, symbol, side_norm, resolved_intent,
        request.position_effect, leverage, bool(reduce_only), effective_size,
    )
    try:
        if preferred_broker == "kraken":
            from bot.kraken_margin_engine import margin_account_scope
            with margin_account_scope(account_id, adapter=broker):
                result = get_execution_pipeline().execute(request)
        else:
            result = get_execution_pipeline().execute(request)
    except Exception as exc:
        return {
            "status": "error", "error": str(exc), "symbol": symbol,
            "side": side_norm, "account_id": account_id, "leverage": leverage,
        }

    if not result.success:
        return {
            "status": "error",
            "error": result.error or "ExecutionPipeline rejected order",
            "symbol": symbol,
            "side": side_norm,
            "account_id": account_id,
            "leverage": leverage,
            "margin": leverage > 1,
            "intent_type": resolved_intent,
        }
    return {
        "status": "filled",
        "order_id": "pipeline",
        "symbol": symbol,
        "side": side_norm,
        "account_id": account_id,
        "filled_price": result.fill_price,
        "filled_size_usd": result.filled_size_usd,
        "broker": result.broker,
        "leverage": leverage,
        "margin": leverage > 1,
        "reduce_only": bool(reduce_only),
        "intent_type": resolved_intent,
    }


__all__ = ["submit_market_order_via_pipeline"]
