from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.exchange_normalizer")


@dataclass
class ExchangeNormalizationResult:
    accepted: bool
    symbol: str
    side: str
    broker: str
    requested_notional_usd: float
    normalized_notional_usd: float
    native_symbol: str = ""
    native_size: float = 0.0
    native_size_type: str = "quote"
    reason: str = "ok"
    adjustments: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class ExchangeNormalizer:
    """Normalize exchange-facing order requests before ECEL/router dispatch."""

    def __init__(self) -> None:
        self._validator = self._load_validator()
        self._order_normalizer = self._load_order_normalizer()

    def normalize(
        self,
        *,
        symbol: str,
        side: str,
        broker: str,
        size_usd: float,
        price_hint_usd: Optional[float] = None,
    ) -> ExchangeNormalizationResult:
        broker_name = (broker or "coinbase").lower()
        normalized_notional = round(float(size_usd), 2)
        adjustments: List[str] = []

        if abs(normalized_notional - float(size_usd)) > 1e-9:
            adjustments.append("quote_precision")

        if self._validator is not None:
            try:
                outcome = self._validator.validate_and_normalize(
                    symbol=symbol,
                    side=side,
                    quantity=normalized_notional,
                    price=float(price_hint_usd or 0.0),
                    size_type="quote",
                )
                normalized_notional = float(outcome.adjusted_qty)
                adjustments.extend(list(outcome.adjustments or []))
                if not outcome.is_valid:
                    return ExchangeNormalizationResult(
                        accepted=False,
                        symbol=symbol,
                        side=side,
                        broker=broker_name,
                        requested_notional_usd=float(size_usd),
                        normalized_notional_usd=normalized_notional,
                        reason=outcome.reason,
                        adjustments=adjustments,
                    )
            except Exception as exc:
                logger.warning("ExchangeNormalizer: validator failed for %s: %s", symbol, exc)

        native_symbol = symbol
        native_size = normalized_notional
        native_size_type = "quote"
        if self._order_normalizer is not None:
            try:
                native = self._order_normalizer.from_broker_call(
                    broker_name=broker_name,
                    symbol=symbol,
                    side=side,
                    quantity=normalized_notional,
                    size_type="quote",
                    current_price=float(price_hint_usd or 0.0),
                )
                native_symbol = native.symbol
                native_size = float(native.size)
                native_size_type = native.size_type
            except Exception as exc:
                logger.warning("ExchangeNormalizer: order normalization failed for %s: %s", symbol, exc)

        return ExchangeNormalizationResult(
            accepted=True,
            symbol=symbol,
            side=side,
            broker=broker_name,
            requested_notional_usd=float(size_usd),
            normalized_notional_usd=normalized_notional,
            native_symbol=native_symbol,
            native_size=native_size,
            native_size_type=native_size_type,
            adjustments=adjustments,
        )

    @staticmethod
    def _load_validator():
        for mod_name in ("bot.exchange_order_validator", "exchange_order_validator"):
            try:
                mod = __import__(mod_name, fromlist=["get_exchange_order_validator"])
                return mod.get_exchange_order_validator()
            except Exception:
                continue
        return None

    @staticmethod
    def _load_order_normalizer():
        for mod_name in ("bot.order_normalizer", "order_normalizer"):
            try:
                mod = __import__(mod_name, fromlist=["get_order_normalizer"])
                return mod.get_order_normalizer()
            except Exception:
                continue
        return None


_instance: ExchangeNormalizer | None = None
_lock = threading.Lock()


def get_exchange_normalizer() -> ExchangeNormalizer:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ExchangeNormalizer()
    return _instance