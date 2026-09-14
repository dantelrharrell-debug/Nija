"""Broker-cell strategy selector.

Each broker gets its own strategy configuration. Selection state is stored in
ContextVar objects instead of process-wide mutable attributes so concurrent
broker loops cannot overwrite one another's active strategy.
"""
from __future__ import annotations

from contextvars import ContextVar
import logging
from typing import Any, Dict

logger = logging.getLogger("nija.strategy_selector")

try:
    from .coinbase_config import COINBASE_CONFIG
    from .kraken_config import KRAKEN_CONFIG
    from .binance_config import BINANCE_CONFIG
    from .okx_config import OKX_CONFIG
    from .alpaca_config import ALPACA_CONFIG
    from .default_config import DEFAULT_CONFIG
except ImportError:
    COINBASE_CONFIG = KRAKEN_CONFIG = BINANCE_CONFIG = None
    OKX_CONFIG = ALPACA_CONFIG = DEFAULT_CONFIG = None

try:
    from bot.broker_strategy_router import BROKER_PROFILES
except ImportError:
    try:
        from broker_strategy_router import BROKER_PROFILES  # type: ignore[import]
    except ImportError:
        BROKER_PROFILES: Dict[str, Dict[str, Any]] = {}

_CURRENT_BROKER: ContextVar[str | None] = ContextVar("nija_broker_cell_name", default=None)
_CURRENT_CONFIG: ContextVar[Any | None] = ContextVar("nija_broker_cell_strategy", default=None)


class BrokerStrategySelector:
    """Broker router with context-local compatibility state."""

    def __init__(self) -> None:
        self.configs: Dict[str, Any] = {
            "coinbase": COINBASE_CONFIG,
            "kraken": KRAKEN_CONFIG,
            "binance": BINANCE_CONFIG,
            "okx": OKX_CONFIG,
            "alpaca": ALPACA_CONFIG,
            "default": DEFAULT_CONFIG,
        }

    @property
    def current_broker(self) -> str | None:
        return _CURRENT_BROKER.get()

    @property
    def current_config(self) -> Any | None:
        return _CURRENT_CONFIG.get()

    @staticmethod
    def _name(broker_type: str | None) -> str:
        return str(broker_type or "default").strip().lower()

    def _config(self, broker_type: str | None) -> Any:
        return self.configs.get(self._name(broker_type)) or self.configs.get("default")

    def select_strategy(self, broker_type: str):
        """Return the strategy owned by exactly one broker cell."""
        name = self._name(broker_type)
        config = self._config(name)
        _CURRENT_BROKER.set(name)
        _CURRENT_CONFIG.set(config)
        if config is None:
            profile = BROKER_PROFILES.get(name, BROKER_PROFILES.get("default", {}))
            min_move = float(profile.get("min_move", 0.015) or 0.015)
            logger.warning("No concrete strategy config for %s; using isolated fallback", name)
            return {
                "broker_name": name,
                "round_trip_cost": float(profile.get("fee", 0.014) or 0.014),
                "profit_targets": [(min_move * 1.5, "tp1"), (min_move * 2.5, "tp2"), (min_move * 4.0, "tp3")],
                "stop_loss": -(min_move * 0.8),
                "max_hold_hours": 12.0,
                "min_move": min_move,
                "style": profile.get("style", "swing"),
                "speed": profile.get("speed", "slow"),
            }
        logger.info("BROKER_CELL_STRATEGY_SELECTED broker=%s config=%s context_local=true", name, type(config).__name__)
        return config

    def get_current_config(self):
        return _CURRENT_CONFIG.get()

    def get_config(self, broker_type: str):
        return self._config(broker_type)

    def should_enter_long(self, broker_type: str, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        config = self._config(broker_type)
        if config and hasattr(config, "should_buy"):
            return bool(config.should_buy(rsi, price, ema9, ema21))
        return 30 <= rsi <= 50 and price > ema9 and price > ema21

    def should_enter_short(self, broker_type: str, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        config = self._config(broker_type)
        if config and bool(getattr(config, "bidirectional", False)) and hasattr(config, "should_short"):
            return bool(config.should_short(rsi, price, ema9, ema21))
        return False

    def should_exit_position(self, broker_type: str, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        config = self._config(broker_type)
        if config and hasattr(config, "should_sell"):
            return bool(config.should_sell(rsi, price, ema9, ema21))
        return rsi > 60 or price < ema9

    def calculate_position_size(self, broker_type: str, account_balance: float, signal_strength: float = 1.0) -> float:
        config = self._config(broker_type)
        if config and hasattr(config, "calculate_position_size"):
            return float(config.calculate_position_size(account_balance, signal_strength))
        return max(float(account_balance) * 0.20 * float(signal_strength), 10.0)

    def get_profit_targets(self, broker_type: str) -> list:
        config = self._config(broker_type)
        return list(config.profit_targets) if config and hasattr(config, "profit_targets") else [(0.015, "1.5%"), (0.012, "1.2%"), (0.010, "1.0%")]

    def get_stop_loss(self, broker_type: str) -> float:
        config = self._config(broker_type)
        return float(config.stop_loss) if config and hasattr(config, "stop_loss") else -0.010

    def get_max_hold_hours(self, broker_type: str) -> float:
        config = self._config(broker_type)
        return float(config.max_hold_hours) if config and hasattr(config, "max_hold_hours") else 12.0

    def strategy_snapshot(self) -> Dict[str, Dict[str, Any]]:
        snapshot: Dict[str, Dict[str, Any]] = {}
        for name, config in self.configs.items():
            if name == "default" or config is None:
                continue
            snapshot[name] = {
                "config_class": type(config).__name__,
                "bidirectional": bool(getattr(config, "bidirectional", False)),
                "round_trip_cost": float(getattr(config, "round_trip_cost", 0.0) or 0.0),
                "stop_loss": float(getattr(config, "stop_loss", 0.0) or 0.0),
                "max_hold_hours": float(getattr(config, "max_hold_hours", 0.0) or 0.0),
                "max_positions": int(getattr(config, "max_positions", 0) or 0),
                "max_trades_per_day": int(getattr(config, "max_trades_per_day", 0) or 0),
            }
        return snapshot


STRATEGY_SELECTOR = BrokerStrategySelector()


def get_strategy_for_broker(broker_type: str):
    return STRATEGY_SELECTOR.select_strategy(broker_type)
