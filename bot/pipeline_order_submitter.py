"""Canonical market-order submit helper via ExecutionPipeline/ECEL."""

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


def _balance_from_payload(payload: Any) -> Optional[float]:
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, dict):
        for key in (
            "available_balance",
            "available_usd",
            "available",
            "free",
            "free_usd",
            "trading_balance",
            "total_balance",
            "total_funds",
            "balance",
            "equity",
            "usd_balance",
            "total_usd",
        ):
            if key in payload:
                try:
                    return float(payload.get(key) or 0.0)
                except (TypeError, ValueError):
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
            if "kraken" in name:
                return "kraken"
            if "coinbase" in name:
                return "coinbase"
            if "okx" in name:
                return "okx"
            if "binance" in name:
                return "binance"
            if "alpaca" in name:
                return "alpaca"
    except Exception:
        pass
    return preferred_broker


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
    deduped: list[str] = []
    for key in keys:
        if key and key not in deduped:
            deduped.append(key)
    return deduped


def submit_market_order_via_pipeline(
    broker: Any,
    symbol: str,
    side: str,
    quantity: float,
    size_type: str = "quote",
    strategy: str = "PipelineOrderSubmitter",
) -> Dict[str, Any]:
    """Submit a market order through ExecutionPipeline.

    Args:
        broker: Broker instance (used for broker hint and optional price hint fetch).
        symbol: Trading symbol.
        side: buy/sell.
        quantity: USD size when size_type='quote', base quantity when size_type='base'.
        size_type: 'quote' or 'base'.
        strategy: Strategy tag for pipeline telemetry.
    """
    if get_execution_pipeline is None or PipelineRequest is None:
        return {
            "status": "error",
            "error": "ExecutionPipeline unavailable and direct broker bypass blocked",
            "symbol": symbol,
            "side": side,
        }

    _force_trade = (
        os.environ.get("FORCE_TRADE", "").strip().lower() in {"1", "true", "yes", "enabled", "on"}
        or os.environ.get("FORCE_TRADE_MODE", "").strip().lower() in {"1", "true", "yes", "enabled", "on"}
    )
    if not _force_trade:
        try:
            assert_distributed_writer_authority()
        except Exception as exc:
            logger.error(
                "🚫 [PipelineOrderSubmitter] DistributedWriterFence reject — "
                "symbol=%s side=%s error=%s",
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
            "[FORCE_TRADE] Bypassing assert_distributed_writer_authority in pipeline_order_submitter — "
            "FORCE_TRADE_MODE=true. symbol=%s side=%s",
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
    broker_balance_keys = _resolve_broker_balance_keys(broker, preferred_broker)

    _available_balance_usd: Optional[float] = None
    try:
        cached_detail = getattr(broker, "_balance_cache", None)
        _available_balance_usd = _balance_from_payload(cached_detail)
        if _available_balance_usd is None:
            cached_scalar = getattr(broker, "_last_known_balance", None)
            if isinstance(cached_scalar, (int, float)):
                _available_balance_usd = float(cached_scalar)
    except Exception:
        _available_balance_usd = None
    try:
        for _ca_mod_name in ("bot.capital_authority", "capital_authority"):
            try:
                import importlib as _il
                _ca_mod = _il.import_module(_ca_mod_name)
                _get_ca = getattr(_ca_mod, "get_capital_authority", None)
                if callable(_get_ca):
                    _ca = _get_ca()
                    _is_registered = getattr(_ca, "is_registered", None)
                    for _broker_key in broker_balance_keys:
                        _ca_balance = float(_ca.get_per_broker(_broker_key) or 0.0)
                        if _ca_balance > 0.0 or (callable(_is_registered) and _is_registered(_broker_key)):
                            _available_balance_usd = _ca_balance
                            logger.info(
                                "[PipelineOrderSubmitter] resolved broker balance from "
                                "CapitalAuthority: broker=%s balance=$%.2f symbol=%s side=%s",
                                _broker_key, _ca_balance, symbol, side_norm,
                            )
                            break
                break
            except ImportError:
                continue
    except Exception as _ca_exc:
        logger.debug(
            "[PipelineOrderSubmitter] capital authority balance lookup failed "
            "(non-fatal, risk engine will use fail-open): %s",
            _ca_exc,
        )

    # Fall back to broker's cached balance when CapitalAuthority is unavailable.
    if not _available_balance_usd:
        try:
            if broker is not None and hasattr(broker, "get_account_balance"):
                _raw = broker.get_account_balance()
                _available_balance_usd = _balance_from_payload(_raw)
                if _available_balance_usd is None:
                    _available_balance_usd = float(_raw or 0.0)
        except Exception:
            pass

    res = get_execution_pipeline().execute(
        PipelineRequest(
            strategy=strategy,
            symbol=symbol,
            side=side_norm,
            size_usd=size_usd,
            order_type="MARKET",
            preferred_broker=preferred_broker,
            price_hint_usd=price_hint_usd,
            available_balance_usd=_available_balance_usd if _available_balance_usd else None,
        )
    )

    if not res.success:
        return {
            "status": "error",
            "error": res.error or "ExecutionPipeline rejected order",
            "symbol": symbol,
            "side": side_norm,
        }

    return {
        "status": "filled",
        "order_id": "pipeline",
        "symbol": symbol,
        "side": side_norm,
        "filled_price": res.fill_price,
        "filled_size_usd": res.filled_size_usd,
        "broker": res.broker,
    }
