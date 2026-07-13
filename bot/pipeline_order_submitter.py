"""Canonical market-order submit helper via ExecutionPipeline/ECEL.

Kraken orders are margin-enriched here because this boundary owns the exact live
adapter and account identity.  Automatic margin remains fail-closed: a request is
upgraded only after account permission, TradeBalance health, and pair leverage
checks all pass.  Otherwise the original spot request is preserved.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.pipeline_order_submitter")

try:
    from bot.execution_pipeline import get_execution_pipeline, PipelineRequest
except ImportError:
    try:
        from execution_pipeline import get_execution_pipeline, PipelineRequest
    except ImportError:
        get_execution_pipeline = None  # type: ignore
        PipelineRequest = None  # type: ignore

try:
    from bot.execution_authority_context import assert_distributed_writer_authority
except ImportError:
    try:
        from execution_authority_context import assert_distributed_writer_authority
    except ImportError:
        def assert_distributed_writer_authority() -> None:
            return


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "enabled", "on", "y"}


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
                try:
                    return float(payload.get(key) or 0.0)
                except (TypeError, ValueError, OverflowError):
                    return 0.0
    return None


def _resolve_preferred_broker(broker: Any) -> str:
    preferred_broker = "coinbase"
    try:
        broker_type = getattr(broker, "broker_type", None)
        if broker_type is not None:
            if hasattr(broker_type, "value"):
                return str(broker_type.value).lower()
            if isinstance(broker_type, str) and broker_type.strip():
                return broker_type.strip().lower()
        name = getattr(broker, "NAME", None)
        if isinstance(name, str) and name.strip():
            name = name.strip().lower()
            for candidate in ("kraken", "coinbase", "okx", "binance", "alpaca"):
                if candidate in name:
                    return candidate
    except Exception:
        pass
    return preferred_broker


def _resolve_account_id(broker: Any, preferred_broker: str) -> str:
    for attr in ("account_identifier", "account_id", "user_id", "owner_id", "name"):
        try:
            value = str(getattr(broker, attr, "") or "").strip().lower()
        except Exception:
            value = ""
        if value and value not in {"none", preferred_broker}:
            return value
    return "platform" if preferred_broker == "kraken" else "default"


def _resolve_broker_balance_keys(broker: Any, preferred_broker: str) -> list[str]:
    keys: list[str] = []
    try:
        account_identifier = str(getattr(broker, "account_identifier", "") or "").strip().lower()
        if account_identifier and account_identifier not in {"none", "platform", preferred_broker}:
            keys.append(f"{preferred_broker}:{account_identifier}")
    except Exception:
        pass
    if preferred_broker:
        keys.append(preferred_broker)
    return list(dict.fromkeys(key for key in keys if key))


def _resolve_margin_exit(
    *,
    preferred_broker: str,
    account_id: str,
    symbol: str,
) -> Dict[str, Any]:
    if preferred_broker != "kraken":
        return {}
    try:
        from bot.margin_position_ledger import get_margin_position_ledger
        ledger = get_margin_position_ledger()
        row = ledger.get_record(
            broker="kraken",
            account_id=account_id,
            subaccount_id="",
            symbol=str(symbol or "").strip().upper(),
            asset_class="crypto",
        )
    except Exception as exc:
        logger.debug("KRAKEN_MARGIN_EXIT_LEDGER_LOOKUP_FAILED account=%s symbol=%s error=%s", account_id, symbol, exc)
        return {}
    leverage = int(float(row.get("leverage") or 1)) if row else 1
    lifecycle = str(row.get("lifecycle_status") or "").lower() if row else ""
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


def _plan_kraken_margin_entry(
    *,
    broker: Any,
    account_id: str,
    symbol: str,
    side: str,
    size_usd: float,
    account_equity_usd: float,
) -> Dict[str, Any]:
    if str(side or "").lower() != "buy":
        return {}
    if not _truthy("NIJA_KRAKEN_MARGIN_ENABLED", True):
        return {}
    if not _truthy("NIJA_KRAKEN_AUTO_MARGIN_ENABLED", True):
        return {}
    try:
        from bot.kraken_margin_engine import get_margin_engine
        engine = get_margin_engine(account_id=account_id, adapter=broker)
        plan = engine.plan_auto_margin(
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
            "KRAKEN_MARGIN_AUTO_PLAN account=%s symbol=%s side=%s decision=SPOT reason=%s pair_max=%sx",
            account_id, symbol, side, plan.reason, plan.pair_max_leverage,
        )
        return {}
    logger.critical(
        "KRAKEN_MARGIN_AUTO_PLAN account=%s symbol=%s side=%s decision=MARGIN leverage=%sx "
        "spot_notional=$%.2f leveraged_notional=$%.2f buying_power=$%.2f pair_max=%sx reason=%s",
        account_id,
        symbol,
        side,
        plan.leverage,
        plan.spot_notional_usd,
        plan.leveraged_notional_usd,
        plan.buying_power_usd,
        plan.pair_max_leverage,
        plan.reason,
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
) -> Dict[str, Any]:
    """Submit a market order through ExecutionPipeline."""
    if get_execution_pipeline is None or PipelineRequest is None:
        return {
            "status": "error",
            "error": "ExecutionPipeline unavailable and direct broker bypass blocked",
            "symbol": symbol,
            "side": side,
        }

    force_trade = _truthy("FORCE_TRADE") or _truthy("FORCE_TRADE_MODE")
    if not force_trade:
        try:
            assert_distributed_writer_authority()
        except Exception as exc:
            logger.error(
                "🚫 [PipelineOrderSubmitter] DistributedWriterFence reject — symbol=%s side=%s error=%s",
                symbol, side, exc,
            )
            return {
                "status": "error",
                "error": f"DistributedWriterFence reject: {exc}",
                "symbol": symbol,
                "side": side,
            }
    else:
        logger.info(
            "[FORCE_TRADE] Bypassing assert_distributed_writer_authority in pipeline_order_submitter — symbol=%s side=%s",
            symbol, side,
        )

    side_norm = (side or "buy").strip().lower()
    size_usd = float(max(0.0, quantity))
    price_hint_usd: Optional[float] = None
    if (size_type or "quote").lower() == "base":
        try:
            if hasattr(broker, "get_current_price"):
                px = float(broker.get_current_price(symbol) or 0.0)
                if px > 0:
                    price_hint_usd = px
                    size_usd = float(max(0.0, quantity * px))
        except Exception:
            price_hint_usd = None
        if price_hint_usd is None or size_usd <= 0:
            return {
                "status": "error",
                "error": "Cannot compile base-size order without valid price hint",
                "symbol": symbol,
                "side": side_norm,
            }

    preferred_broker = _resolve_preferred_broker(broker)
    account_id = _resolve_account_id(broker, preferred_broker)
    broker_balance_keys = _resolve_broker_balance_keys(broker, preferred_broker)
    available_balance_usd: Optional[float] = None
    try:
        available_balance_usd = _balance_from_payload(getattr(broker, "_balance_cache", None))
        if available_balance_usd is None:
            scalar = getattr(broker, "_last_known_balance", None)
            if isinstance(scalar, (int, float)):
                available_balance_usd = float(scalar)
    except Exception:
        available_balance_usd = None

    try:
        import importlib
        for module_name in ("bot.capital_authority", "capital_authority"):
            try:
                module = importlib.import_module(module_name)
                get_ca = getattr(module, "get_capital_authority", None)
                if callable(get_ca):
                    authority = get_ca()
                    is_registered = getattr(authority, "is_registered", None)
                    for broker_key in broker_balance_keys:
                        balance = float(authority.get_per_broker(broker_key) or 0.0)
                        if balance > 0.0 or (callable(is_registered) and is_registered(broker_key)):
                            available_balance_usd = balance
                            logger.info(
                                "[PipelineOrderSubmitter] resolved broker balance from CapitalAuthority: broker=%s balance=$%.2f symbol=%s side=%s",
                                broker_key, balance, symbol, side_norm,
                            )
                            break
                break
            except ImportError:
                continue
    except Exception as exc:
        logger.debug("[PipelineOrderSubmitter] capital authority balance lookup failed: %s", exc)

    if not available_balance_usd:
        try:
            if broker is not None and hasattr(broker, "get_account_balance"):
                raw = broker.get_account_balance()
                available_balance_usd = _balance_from_payload(raw)
                if available_balance_usd is None:
                    available_balance_usd = float(raw or 0.0)
        except Exception:
            pass

    margin_fields: Dict[str, Any] = {}
    if preferred_broker == "kraken":
        if side_norm == "buy":
            margin_fields = _plan_kraken_margin_entry(
                broker=broker,
                account_id=account_id,
                symbol=symbol,
                side=side_norm,
                size_usd=size_usd,
                account_equity_usd=float(available_balance_usd or 0.0),
            )
        elif side_norm == "sell":
            margin_fields = _resolve_margin_exit(
                preferred_broker=preferred_broker,
                account_id=account_id,
                symbol=symbol,
            )
            if margin_fields:
                logger.critical(
                    "KRAKEN_MARGIN_EXIT_PLAN account=%s symbol=%s leverage=%sx reduce_only=true reason=%s",
                    account_id, symbol, margin_fields.get("leverage"), margin_fields.get("reason"),
                )

    effective_size_usd = float(margin_fields.get("size_usd") or size_usd)
    leverage = int(margin_fields.get("leverage") or 1)
    margin_mode = margin_fields.get("margin_mode")
    reduce_only = margin_fields.get("reduce_only")
    intent_type = margin_fields.get("intent_type")
    buying_power_usd = margin_fields.get("buying_power_usd")
    metadata = {
        "broker_client": broker,
        "broker_name": preferred_broker,
        "kraken_margin_auto": bool(margin_fields and leverage > 1),
        "kraken_margin_reason": margin_fields.get("reason", "spot"),
        "spot_notional_usd": margin_fields.get("spot_notional_usd", size_usd),
        "pair_max_leverage": margin_fields.get("pair_max_leverage", 1),
        "leverage": leverage,
        "reduce_only": reduce_only,
        "margin_mode": margin_mode,
    }

    request = PipelineRequest(
        strategy=strategy,
        symbol=symbol,
        side=side_norm,
        size_usd=effective_size_usd,
        order_type="MARKET",
        preferred_broker=preferred_broker,
        price_hint_usd=price_hint_usd,
        available_balance_usd=available_balance_usd if available_balance_usd else None,
        buying_power_usd=buying_power_usd,
        account_id=account_id,
        intent_type=intent_type,
        leverage=leverage if leverage > 1 else None,
        margin_mode=margin_mode,
        reduce_only=reduce_only,
        metadata=metadata,
    )

    try:
        if preferred_broker == "kraken":
            from bot.kraken_margin_engine import margin_account_scope
            with margin_account_scope(account_id, adapter=broker):
                res = get_execution_pipeline().execute(request)
        else:
            res = get_execution_pipeline().execute(request)
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "symbol": symbol,
            "side": side_norm,
            "leverage": leverage,
        }

    if not res.success:
        return {
            "status": "error",
            "error": res.error or "ExecutionPipeline rejected order",
            "symbol": symbol,
            "side": side_norm,
            "leverage": leverage,
            "margin": leverage > 1,
        }

    return {
        "status": "filled",
        "order_id": "pipeline",
        "symbol": symbol,
        "side": side_norm,
        "filled_price": res.fill_price,
        "filled_size_usd": res.filled_size_usd,
        "broker": res.broker,
        "leverage": leverage,
        "margin": leverage > 1,
        "reduce_only": bool(reduce_only),
    }
