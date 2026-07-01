from __future__ import annotations

import inspect
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
        asset_class: Optional[str] = None,
        quantity_mode: str = "usd",
        quantity: Optional[float] = None,
        account_type: Optional[str] = None,
        leverage: Optional[float] = None,
        reduce_only: bool = False,
        position_effect: Optional[str] = None,
        borrow_intent: Optional[str] = None,
        margin_mode: Optional[str] = None,
        time_in_force: Optional[str] = None,
        extended_hours: Optional[bool] = None,
    ) -> ExchangeNormalizationResult:
        broker_name = (broker or "coinbase").lower()
        normalized_notional = round(float(size_usd), 2)
        adjustments: List[str] = []

        if abs(normalized_notional - float(size_usd)) > 1e-9:
            adjustments.append("quote_precision")

        if self._validator is not None:
            try:
                validator_fn = self._validator.validate_and_normalize
                validator_kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "quantity": float(quantity if quantity is not None else normalized_notional),
                    "price": float(price_hint_usd or 0.0),
                    "size_type": "base" if quantity_mode in {"shares", "contracts", "base"} else "quote",
                    "quantity_mode": quantity_mode,
                    "time_in_force": time_in_force,
                    "extended_hours": extended_hours,
                }
                try:
                    accepted_params = set(inspect.signature(validator_fn).parameters.keys())
                    if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in inspect.signature(validator_fn).parameters.values()):
                        validator_kwargs = {
                            key: value
                            for key, value in validator_kwargs.items()
                            if key in accepted_params
                        }
                    elif "asset_class" not in validator_kwargs:
                        # Kept for clarity; VAR_KEYWORD accepts all optional keys.
                        pass
                    if "asset_class" in accepted_params or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in inspect.signature(validator_fn).parameters.values()
                    ):
                        validator_kwargs["asset_class"] = asset_class
                except (TypeError, ValueError):
                    # Some callables do not expose a signature; keep the legacy shape
                    # but retry without optional keys if it raises below.
                    validator_kwargs["asset_class"] = asset_class

                try:
                    outcome = validator_fn(**validator_kwargs)
                except TypeError as exc:
                    # Backward-compatible retry for older validators that do not accept
                    # asset_class / quantity_mode / session-specific kwargs.
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    fallback_kwargs = {
                        key: value
                        for key, value in validator_kwargs.items()
                        if key not in {"asset_class", "quantity_mode", "time_in_force", "extended_hours"}
                    }
                    logger.info(
                        "ExchangeNormalizer: retrying validator for %s without optional kwargs after compatibility error: %s",
                        symbol,
                        exc,
                    )
                    outcome = validator_fn(**fallback_kwargs)
                if quantity_mode in {"shares", "contracts", "base"}:
                    normalized_notional = round(float(outcome.adjusted_qty) * float(price_hint_usd or 0.0), 2)
                else:
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
                    quantity=float(quantity if quantity is not None else normalized_notional),
                    size_type="base" if quantity_mode in {"shares", "contracts", "base"} else "quote",
                    current_price=float(price_hint_usd or 0.0),
                    asset_class=asset_class,
                    quantity_mode=quantity_mode,
                    account_type=account_type,
                    leverage=leverage,
                    reduce_only=reduce_only,
                    position_effect=position_effect,
                    borrow_intent=borrow_intent,
                    margin_mode=margin_mode,
                    time_in_force=time_in_force,
                    extended_hours=extended_hours,
                )
                native_symbol = native.symbol
                native_size = float(native.size)
                native_size_type = native.size_type
                if native.raw.extra:
                    adjustments.extend([f"native:{k}" for k in sorted(native.raw.extra.keys())])
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
            details={
                "asset_class": asset_class or "",
                "quantity_mode": quantity_mode,
                "account_type": account_type or "",
                "leverage": leverage,
                "reduce_only": bool(reduce_only),
                "position_effect": position_effect or "",
                "borrow_intent": borrow_intent or "",
                "margin_mode": margin_mode or "",
                "time_in_force": time_in_force or "",
                "extended_hours": bool(extended_hours) if extended_hours is not None else None,
            },
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
