"""
Coinbase-Specific Trading Configuration

Coinbase Advanced Trade characteristics:
- Higher fees: ~0.6% taker, ~0.4% maker (1.4% round-trip with spread)
- Crypto only (no stocks, futures, or options)
- Best strategy: BUY-FOCUSED with quick profit-taking
- Market dynamics: Fast-moving crypto markets
- Liquidity: Generally excellent for major pairs

Strategy Focus:
- Buy on strong signals, sell quickly for profit
- Higher profit targets to overcome fees (1.5%+)
- Aggressive stop losses to preserve capital
- Limit position holding time due to high fees
"""

from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class CoinbaseConfig:
    """Coinbase-specific trading configuration"""
    
    # Broker identification
    broker_name: str = "coinbase"
    broker_display_name: str = "Coinbase Advanced Trade"
    
    # Fee structure
    taker_fee: float = 0.006  # 0.6% taker fee
    maker_fee: float = 0.004  # 0.4% maker fee
    spread_cost: float = 0.002  # ~0.2% average spread
    round_trip_cost: float = 0.014  # 1.4% total (taker fees + spread)
    
    # Asset types supported
    supports_crypto: bool = True
    supports_stocks: bool = False
    supports_futures: bool = False
    supports_options: bool = False
    
    # Trading direction profitability
    # On Coinbase, BUYING is more profitable due to fee structure
    buy_preferred: bool = True  # Buy-focused strategy
    sell_preferred: bool = False  # Selling less profitable
    bidirectional: bool = False  # Not equally profitable both ways
    
    # Profit targets (must exceed 1.4% fees)
    # Stepped targets: check highest first, exit at first hit
    profit_targets: List[Tuple[float, str]] = None
    
    def __post_init__(self):
        """Initialize profit targets after dataclass creation"""
        if self.profit_targets is None:
            # NOTE: With 1.4% fees, targets below 1.4% are net-negative
            # These targets are ordered by preference (check highest first)
            # 1.5% target: Net +0.1% after fees (minimal but positive profit)
            # 1.2% target: Net -0.2% (accepts small loss to avoid larger reversal)
            # 1.0% target: Net -0.4% (emergency exit, still better than -1.0% stop loss)
            self.profit_targets = [
                (0.015, "Profit target +1.5% (Net +0.1% after 1.4% fees) - ONLY PROFITABLE TARGET"),
                (0.012, "Profit target +1.2% (Net -0.2% after fees) - DAMAGE CONTROL vs reversal"),
                (0.010, "Profit target +1.0% (Net -0.4% after fees) - EMERGENCY vs -1.0% stop"),
            ]
    
    # Stop loss (aggressive to preserve capital with high fees)
    stop_loss: float = -0.010  # -1.0% stop loss
    stop_loss_warning: float = -0.007  # -0.7% warning
    
    # Position management
    max_hold_hours: float = 24.0  # Maximum 24 hours to allow full daily profit potential
    stale_warning_hours: float = 12.0  # Warn at 12 hours
    
    # RSI thresholds (aggressive for quick entries/exits)
    rsi_overbought: float = 55.0  # Exit when RSI > 55 (quick profit-taking)
    rsi_oversold: float = 45.0  # Exit when RSI < 45 (quick loss-cutting)
    
    # Entry signals (buy-focused)
    buy_rsi_min: float = 30.0  # Buy when RSI bounces from oversold
    buy_rsi_max: float = 50.0  # Buy before overbought
    sell_rsi_min: float = 50.0  # Sell when momentum fades
    sell_rsi_max: float = 70.0  # Sell in overbought
    
    # Position sizing (fee-aware)
    # Minimum $10 to allow trading, recommended $25+ for profitability after 1.4% fees
    min_position_usd: float = 10.0  # $10 minimum (fees are ~$0.14)
    recommended_min_usd: float = 25.0  # $25+ recommended for profitability
    min_balance_to_trade: float = 10.0  # $10 minimum to allow small account trading
    
    # Order type preferences
    prefer_limit_orders: bool = True  # Use limit orders to save fees
    limit_order_offset_pct: float = 0.001  # 0.1% from current price
    limit_order_timeout: int = 60  # Cancel after 60 seconds
    
    # Risk management
    max_positions: int = 8  # Maximum concurrent positions
    max_exposure_pct: float = 0.40  # Maximum 40% of capital deployed
    
    # Trade frequency (limit to reduce fee impact)
    min_seconds_between_trades: int = 300  # 5 minutes between trades
    max_trades_per_day: int = 30  # Limit to 30 trades/day
    
    def get_profit_target_price(self, entry_price: float, target_index: int = 0) -> float:
        """
        Calculate profit target price.
        
        Args:
            entry_price: Entry price
            target_index: Index of profit target (0 = highest/first)
            
        Returns:
            Target price
        """
        if target_index >= len(self.profit_targets):
            target_index = 0
        
        target_pct, _ = self.profit_targets[target_index]
        return entry_price * (1 + target_pct)
    
    def get_stop_loss_price(self, entry_price: float) -> float:
        """Calculate stop loss price"""
        return entry_price * (1 + self.stop_loss)
    
    def should_buy(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if BUY signal is valid for Coinbase.
        
        Coinbase strategy: BUY-FOCUSED
        - Buy on RSI bounce from oversold (30-50)
        - Buy when price above EMA support
        - Quick entries for momentum
        """
        # RSI in buy zone
        rsi_valid = self.buy_rsi_min <= rsi <= self.buy_rsi_max
        
        # Price above EMA9 for momentum
        above_ema9 = price > ema9
        
        # Above EMA21 for trend
        above_ema21 = price > ema21
        
        return rsi_valid and above_ema9 and above_ema21
    
    def should_sell(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if SELL signal is valid for Coinbase.
        
        Coinbase strategy: QUICK PROFIT-TAKING
        - Sell on RSI overbought (> 55)
        - Sell when price drops below EMA support
        - Less emphasis on short selling (not profitable with high fees)
        """
        # RSI overbought (exit long positions)
        rsi_overbought = rsi > self.rsi_overbought
        
        # Price below EMA9 (momentum lost)
        below_ema9 = price < ema9
        
        # Either condition triggers sell
        return rsi_overbought or below_ema9
    
    def calculate_position_size(self, account_balance: float, signal_strength: float = 1.0) -> float:
        """
        Calculate position size for Coinbase.
        
        Args:
            account_balance: Available balance
            signal_strength: Signal quality (0.0 to 1.0)
            
        Returns:
            Position size in USD
        """
        # Base position size (fee-aware)
        if account_balance < 50:
            base_pct = 0.50  # 50% for small accounts
        elif account_balance < 100:
            base_pct = 0.40  # 40% for medium accounts
        else:
            base_pct = 0.20  # 20% for larger accounts
        
        # Adjust by signal strength
        adjusted_pct = base_pct * signal_strength
        
        # Calculate size
        position_size = account_balance * adjusted_pct
        
        # Enforce minimum
        return max(position_size, self.min_position_usd)
    
    def get_config_summary(self) -> str:
        """Get configuration summary for logging"""
        return f"""
Coinbase Trading Configuration:
  Broker: {self.broker_display_name}
  Role: SECONDARY/SELECTIVE (not for small accounts)
  Min Balance: ${self.min_balance_to_trade} (with Coinbase-specific strategy rules)
  Fees: {self.round_trip_cost*100:.1f}% round-trip
  Strategy: BUY-FOCUSED (high fees = quick profits)
  Profit Targets: {', '.join([f'{t[0]*100:.1f}%' for t in self.profit_targets])}
  Stop Loss: {self.stop_loss*100:.1f}%
  Max Hold: {self.max_hold_hours} hours
  Min Position: ${self.min_position_usd}
  Asset Types: Crypto only
"""


# Create default instance
COINBASE_CONFIG = CoinbaseConfig()
