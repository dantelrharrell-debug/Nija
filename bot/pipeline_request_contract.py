from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
import uuid


_ASSET_CLASSES = {"crypto", "equity", "futures", "options"}
_SIDES = {"buy", "sell"}
_INTENT_TYPES = {"entry", "exit", "reduce", "rebalance"}
_ORDER_TYPES = {"market", "limit", "twap", "stop", "stop_limit"}
_TIFS = {"day", "gtc", "ioc", "fok"}
_SIZING_MODES = {"notional_usd", "units"}
_UNIT_TYPES = {"shares", "contracts", "base_asset"}
_MARGIN_MODES = {"cross", "isolated"}


def _norm_enum(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().lower()
    return v or None


def _norm_side(side: Optional[str]) -> str:
    raw = _norm_enum(side) or "buy"
    if raw == "long":
        return "buy"
    if raw == "short":
        return "sell"
    return raw


@dataclass(frozen=True)
class PipelineRequest:
    """Canonical immutable execution request contract."""

    # Identity / trace
    request_id: str = ""
    intent_id: Optional[str] = None
    strategy: str = ""
    cycle_id: Optional[str] = None
    account_id: str = "default"
    subaccount_id: Optional[str] = None

    # Instrument / venue
    symbol: str = ""
    asset_class: Optional[str] = None
    preferred_broker: Optional[str] = None
    allowed_brokers: Tuple[str, ...] = field(default_factory=tuple)

    # Execution intent
    side: str = "buy"
    intent_type: Optional[str] = None
    order_type: Optional[str] = "market"
    time_in_force: Optional[str] = None
    reduce_only: Optional[bool] = None

    # Canonical sizing
    sizing_mode: Optional[str] = None
    notional_usd: Optional[float] = None
    units: Optional[float] = None
    unit_type: Optional[str] = None

    # Backward-compatible aliases
    size_usd: Optional[float] = None

    # Pricing / market context
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    price_hint_usd: Optional[float] = None
    bid_price_usd: Optional[float] = None
    ask_price_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    volatility_pct: Optional[float] = None

    # Margin / equities controls
    leverage: Optional[int] = None
    margin_mode: Optional[str] = None
    short_sell: Optional[bool] = None
    extended_hours: Optional[bool] = None
    buying_power_usd: Optional[float] = None
    available_balance_usd: Optional[float] = None

    # Internal pipeline state
    validated: bool = False
    attempt_n: int = 0  # Incremented by the retry layer; ties to AttemptKey.attempt_n
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rid = self.request_id.strip() if isinstance(self.request_id, str) else ""
        if not rid:
            rid = f"req-{uuid.uuid4().hex}"
        object.__setattr__(self, "request_id", rid)
        object.__setattr__(self, "side", _norm_side(self.side))
        object.__setattr__(self, "asset_class", _norm_enum(self.asset_class))
        object.__setattr__(self, "intent_type", _norm_enum(self.intent_type))
        object.__setattr__(self, "order_type", _norm_enum(self.order_type) or "market")
        object.__setattr__(self, "time_in_force", _norm_enum(self.time_in_force))
        object.__setattr__(self, "sizing_mode", _norm_enum(self.sizing_mode))
        object.__setattr__(self, "unit_type", _norm_enum(self.unit_type))
        object.__setattr__(self, "margin_mode", _norm_enum(self.margin_mode))

        notional = self.notional_usd
        if notional is None and self.size_usd is not None:
            notional = float(self.size_usd)
            object.__setattr__(self, "notional_usd", notional)

        sizing_mode = self.sizing_mode
        if sizing_mode is None:
            if self.units is not None:
                sizing_mode = "units"
            elif notional is not None:
                sizing_mode = "notional_usd"
            object.__setattr__(self, "sizing_mode", sizing_mode)

        if self.size_usd is None and notional is not None:
            object.__setattr__(self, "size_usd", float(notional))


def normalize_pipeline_request(value: PipelineRequest | Dict[str, Any]) -> PipelineRequest:
    if isinstance(value, PipelineRequest):
        return value
    if isinstance(value, dict):
        return PipelineRequest(**value)
    raise TypeError("PipelineRequest input must be PipelineRequest or dict")


def validate_pipeline_request(req: PipelineRequest) -> Tuple[bool, str]:
    if not req.strategy:
        return False, "missing_strategy"
    if not req.symbol:
        return False, "missing_symbol"
    if req.side not in _SIDES:
        return False, "invalid_side"
    if req.order_type not in _ORDER_TYPES:
        return False, "invalid_order_type"
    if req.asset_class is not None and req.asset_class not in _ASSET_CLASSES:
        return False, "invalid_asset_class"
    if req.intent_type is not None and req.intent_type not in _INTENT_TYPES:
        return False, "invalid_intent_type"
    if req.time_in_force is not None and req.time_in_force not in _TIFS:
        return False, "invalid_time_in_force"
    if req.margin_mode is not None and req.margin_mode not in _MARGIN_MODES:
        return False, "invalid_margin_mode"
    if req.sizing_mode not in _SIZING_MODES:
        return False, "invalid_sizing_mode"
    if req.sizing_mode == "notional_usd":
        if req.notional_usd is None or float(req.notional_usd) <= 0:
            return False, "missing_notional_usd"
    if req.sizing_mode == "units":
        if req.units is None or float(req.units) <= 0:
            return False, "missing_units"
        if req.unit_type not in _UNIT_TYPES:
            return False, "missing_unit_type"
    if req.intent_type == "entry" and req.leverage and req.leverage > 1:
        if req.margin_mode not in _MARGIN_MODES:
            return False, "margin_mode_required_for_leverage"
        if req.reduce_only is not False:
            return False, "reduce_only_must_be_false_for_margin_entry"
    if req.intent_type in {"reduce", "exit"} and req.leverage and req.leverage > 1:
        if req.reduce_only is not True:
            return False, "reduce_only_required_for_margin_exit_or_reduce"
    if req.asset_class == "equity":
        if req.time_in_force not in _TIFS:
            return False, "time_in_force_required_for_equity"
        if req.sizing_mode == "units" and req.unit_type != "shares":
            return False, "equity_units_require_shares_unit_type"
    return True, "ok"
