"""
Default Trading Configuration

Used for brokers that don't have specific configurations yet.
Conservative settings that work across most exchanges.
"""

from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class DefaultConfig:
    """Default conservative trading configuration"""

    # Broker identification
    broker_name: str = "default"
    broker_display_name: str = "Default Exchange"

    # Conservative fee estimate (use higher end)
    taker_fee: float = 0.005  # 0.5% taker fee
    maker_fee: float = 0.003  # 0.3% maker fee
    spread_cost: float = 0.002  # 0.2% spread
    round_trip_cost: float = 0.012  # 1.2% total

    # Asset types (assume crypto only)
    supports_crypto: bool = True
    supports_stocks: bool = False
    supports_futures: bool = False
    supports_options: bool = False

    # Trading direction (conservative - buy focus)
    buy_preferred: bool = True
    sell_preferred: bool = False
    bidirectional: bool = False

    # Profit targets
    profit_targets: List[Tuple[float, str]] = None

    def __post_init__(self):
        """Initialize profit targets"""
        if self.profit_targets is None:
            self.profit_targets = [
                (0.015, "Profit target +1.5%"),
                (0.012, "Profit target +1.2%"),
                (0.010, "Profit target +1.0%"),
            ]

    # Stop loss
    stop_loss: float = -0.010  # -1.0%
    stop_loss_warning: float = -0.007  # -0.7%

    # Position management
    max_hold_hours: float = 24.0  # Allow full day for position development
    stale_warning_hours: float = 12.0  # Warn at 12 hours

    # RSI thresholds
    rsi_overbought: float = 60.0
    rsi_oversold: float = 40.0

    # Position sizing
    min_position_usd: float = 10.0
    recommended_min_usd: float = 20.0

    # Order preferences
    prefer_limit_orders: bool = True
    limit_order_offset_pct: float = 0.001
    limit_order_timeout: int = 60

    # Risk management
    max_positions: int = 8
    max_exposure_pct: float = 0.40

    # Trade frequency
    min_seconds_between_trades: int = 240
    max_trades_per_day: int = 40

    def get_config_summary(self) -> str:
        """Get configuration summary"""
        return f"""
Default Trading Configuration:
  Broker: {self.broker_display_name}
  Fees: {self.round_trip_cost*100:.1f}% round-trip (estimated)
  Strategy: Conservative buy-focused
  Profit Targets: {', '.join([f'{t[0]*100:.1f}%' for t in self.profit_targets])}
  Stop Loss: {self.stop_loss*100:.1f}%
"""

# Create default instance
DEFAULT_CONFIG = DefaultConfig()
