"""
Immutable trading identity context for Strategy Engine V2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, Mapping, Optional, Tuple
import uuid


_ALLOWED_MODES = {"live", "limited_live", "paper", "shadow", "simulation", "backtest"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class TradingContext:
    user_id: str
    trading_account_id: str
    broker: str
    broker_account_id: str
    strategy_instance_id: str
    portfolio_id: str
    request_id: str
    correlation_id: str
    environment: str
    mode: str
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        required = {
            "user_id": self.user_id,
            "trading_account_id": self.trading_account_id,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "strategy_instance_id": self.strategy_instance_id,
            "portfolio_id": self.portfolio_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "environment": self.environment,
            "mode": self.mode,
        }
        missing = [name for name, value in required.items() if not _clean(value)]
        if missing:
            raise ValueError(f"missing_required_context_fields:{','.join(missing)}")
        mode = _clean(self.mode).lower()
        if mode not in _ALLOWED_MODES:
            raise ValueError(f"invalid_context_mode:{mode}")
        object.__setattr__(self, "user_id", _clean(self.user_id))
        object.__setattr__(self, "trading_account_id", _clean(self.trading_account_id))
        object.__setattr__(self, "broker", _clean(self.broker).lower())
        object.__setattr__(self, "broker_account_id", _clean(self.broker_account_id))
        object.__setattr__(self, "strategy_instance_id", _clean(self.strategy_instance_id))
        object.__setattr__(self, "portfolio_id", _clean(self.portfolio_id))
        object.__setattr__(self, "request_id", _clean(self.request_id))
        object.__setattr__(self, "correlation_id", _clean(self.correlation_id))
        object.__setattr__(self, "environment", _clean(self.environment))
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "decision_id", _clean(self.decision_id) or str(uuid.uuid4()))

    @property
    def owner_key(self) -> Tuple[str, str, str, str]:
        return (
            self.user_id,
            self.trading_account_id,
            self.broker,
            self.broker_account_id,
        )

    @property
    def scope_key(self) -> str:
        """Return a delimiter-safe, opaque key for mutable state isolation."""
        payload = {
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "environment": self.environment,
            "mode": self.mode,
            "portfolio_id": self.portfolio_id,
            "strategy_instance_id": self.strategy_instance_id,
            "trading_account_id": self.trading_account_id,
            "user_id": self.user_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_log_fields(self) -> Dict[str, str]:
        return {
            "user_id": self.user_id,
            "trading_account_id": self.trading_account_id,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "strategy_instance_id": self.strategy_instance_id,
            "portfolio_id": self.portfolio_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "environment": self.environment,
            "mode": self.mode,
            "decision_id": self.decision_id,
        }

    def make_idempotency_key(self, *, symbol: str, side: str, action: str) -> str:
        """Return a collision-resistant idempotency key for one decision."""
        payload = {
            "action": _clean(action).lower(),
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "correlation_id": self.correlation_id,
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "side": _clean(side).lower(),
            "symbol": _clean(symbol).upper(),
            "trading_account_id": self.trading_account_id,
            "user_id": self.user_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"v2:{hashlib.sha256(encoded).hexdigest()}"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TradingContext":
        return cls(
            user_id=data.get("user_id", ""),
            trading_account_id=data.get("trading_account_id", ""),
            broker=data.get("broker", ""),
            broker_account_id=data.get("broker_account_id", ""),
            strategy_instance_id=data.get("strategy_instance_id", ""),
            portfolio_id=data.get("portfolio_id", ""),
            request_id=data.get("request_id", ""),
            correlation_id=data.get("correlation_id", ""),
            environment=data.get("environment", ""),
            mode=data.get("mode", ""),
            decision_id=data.get("decision_id", ""),
        )


def ensure_context(context: Optional[TradingContext], *, fail_code: str = "missing_trading_context") -> TradingContext:
    if context is None:
        raise ValueError(fail_code)
    return context
