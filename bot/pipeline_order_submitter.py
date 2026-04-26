"""Canonical market-order submit helper via ExecutionPipeline/ECEL."""

from __future__ import annotations

import logging
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

    try:
        assert_distributed_writer_authority()
    except Exception as exc:
        return {
            "status": "error",
            "error": f"DistributedWriterFence reject: {exc}",
            "symbol": symbol,
            "side": side,
        }

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

    res = get_execution_pipeline().execute(
        PipelineRequest(
            strategy=strategy,
            symbol=symbol,
            side=side_norm,
            size_usd=size_usd,
            order_type="MARKET",
            preferred_broker=preferred_broker,
            price_hint_usd=price_hint_usd,
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
