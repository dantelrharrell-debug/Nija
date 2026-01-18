"""
Kraken-Specific Trading Configuration

Kraken Pro characteristics:
- Lower fees: ~0.16% taker, ~0.10% maker (0.36% round-trip with spread)
- Crypto + Futures + Options + Stocks (Kraken Pro)
- Best strategy: BIDIRECTIONAL (can profit both buying AND selling)
- Market dynamics: Professional-grade trading platform
- Liquidity: Excellent for major pairs, good for derivatives

Strategy Focus:
- Bidirectional trading (profit from both directions)
- Lower profit targets possible (0.5%+) due to low fees
- Can hold positions longer (lower fee pressure)
- Support for futures and options strategies
- More aggressive short selling (profitable with low fees)
"""

from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class KrakenConfig:
    """Kraken-specific trading configuration"""
    
    # Broker identification
    broker_name: str = "kraken"
    broker_display_name: str = "Kraken Pro"
    
    # Fee structure (MUCH LOWER than Coinbase)
    taker_fee: float = 0.0016  # 0.16% taker fee (vs 0.6% Coinbase)
    maker_fee: float = 0.0010  # 0.10% maker fee (vs 0.4% Coinbase)
    spread_cost: float = 0.001  # ~0.1% average spread (tighter than Coinbase)
    round_trip_cost: float = 0.0036  # 0.36% total (vs 1.4% Coinbase - 4x cheaper!)
    
    # Asset types supported
    supports_crypto: bool = True
    supports_stocks: bool = True  # Kraken Stocks (coming/available in some regions)
    supports_futures: bool = True  # Kraken Futures
    supports_options: bool = True  # Kraken Options
    
    # Trading direction profitability
    # On Kraken, BOTH directions are profitable due to low fees
    buy_preferred: bool = True  # Buying is profitable
    sell_preferred: bool = True  # Selling/shorting is ALSO profitable
    bidirectional: bool = True  # Equally profitable both ways
    
    # Profit targets (much lower possible due to 0.36% fees vs 1.4%)
    # Can target 0.5%+ and still profit after fees
    profit_targets: List[Tuple[float, str]] = None
    
    def __post_init__(self):
        """Initialize profit targets after dataclass creation"""
        if self.profit_targets is None:
            # NOTE: With 0.36% fees, all targets are net-positive
            # Recommended to add ~0.1-0.2% buffer for slippage/market impact
            # 1.0% target: Net +0.64% after fees (excellent for crypto)
            # 0.7% target: Net +0.34% after fees (good, accounts for some slippage)
            # 0.5% target: Net +0.14% after fees (minimal profit, tight margin)
            self.profit_targets = [
                (0.010, "Profit target +1.0% (Net +0.64% after 0.36% fees) - EXCELLENT"),
                (0.007, "Profit target +0.7% (Net +0.34% after fees) - GOOD"),
                (0.005, "Profit target +0.5% (Net +0.14% after fees) - MINIMAL, watch slippage"),
            ]
    
    # Stop loss (can be tighter due to lower fees)
    stop_loss: float = -0.007  # -0.7% stop loss (tighter than Coinbase's -1.0%)
    stop_loss_warning: float = -0.005  # -0.5% warning
    
    # Position management (can hold longer with low fees)
    max_hold_hours: float = 24.0  # Maximum 24 hours (3x longer than Coinbase)
    stale_warning_hours: float = 12.0  # Warn at 12 hours
    
    # RSI thresholds (less aggressive, can wait for better setups)
    rsi_overbought: float = 65.0  # Exit when RSI > 65 (less aggressive)
    rsi_oversold: float = 35.0  # Exit when RSI < 35 (less aggressive)
    
    # Entry signals (bidirectional - both buy and sell)
    buy_rsi_min: float = 25.0  # Buy in deeper oversold
    buy_rsi_max: float = 55.0  # Buy up to neutral
    sell_rsi_min: float = 45.0  # Sell from neutral
    sell_rsi_max: float = 75.0  # Sell in deep overbought
    
    # Short selling thresholds (profitable on Kraken!)
    short_rsi_min: float = 60.0  # Short when overbought
    short_rsi_max: float = 80.0  # Short in extreme overbought
    
    # Position sizing (can use smaller positions profitably)
    min_position_usd: float = 5.0  # $5 minimum (fees only ~$0.02)
    recommended_min_usd: float = 10.0  # $10+ recommended
    
    # Order type preferences
    prefer_limit_orders: bool = True  # Use limit orders for best fees
    limit_order_offset_pct: float = 0.0005  # 0.05% from current price (tighter)
    limit_order_timeout: int = 90  # 90 seconds (longer fill time acceptable)
    
    # Risk management
    max_positions: int = 12  # More positions allowed (lower fees)
    max_exposure_pct: float = 0.60  # Can deploy more capital (60% vs Coinbase's 40%)
    
    # Trade frequency (can trade more due to lower fees)
    min_seconds_between_trades: int = 120  # 2 minutes (vs 5 min Coinbase)
    max_trades_per_day: int = 60  # 60 trades/day (vs 30 Coinbase)
    
    # Futures and options support
    # ENABLED (Jan 2026): Multi-asset trading for stocks, options, and futures
    # - Stocks: Available via Alpaca integration (AlpacaBroker handles US equities)
    # - Futures: Enabled via Kraken Futures API
    # - Options: Planned for future (Kraken developing options support)
    enable_futures: bool = True  # ENABLED for all accounts
    enable_options: bool = False  # Disabled (in development by Kraken)
    futures_leverage_max: float = 3.0  # Max 3x leverage for futures
    
    def get_profit_target_price(self, entry_price: float, target_index: int = 0, side: str = 'buy') -> float:
        """
        Calculate profit target price for either direction.
        
        Args:
            entry_price: Entry price
            target_index: Index of profit target (0 = highest/first)
            side: 'buy' (long) or 'sell' (short)
            
        Returns:
            Target price
        """
        if target_index >= len(self.profit_targets):
            target_index = 0
        
        target_pct, _ = self.profit_targets[target_index]
        
        if side == 'buy':
            # Long position: target above entry
            return entry_price * (1 + target_pct)
        else:
            # Short position: target below entry
            return entry_price * (1 - target_pct)
    
    def get_stop_loss_price(self, entry_price: float, side: str = 'buy') -> float:
        """
        Calculate stop loss price for either direction.
        
        Args:
            entry_price: Entry price
            side: 'buy' (long) or 'sell' (short)
            
        Returns:
            Stop loss price
        """
        if side == 'buy':
            # Long position: stop below entry
            return entry_price * (1 + self.stop_loss)
        else:
            # Short position: stop above entry
            return entry_price * (1 - self.stop_loss)
    
    def should_buy(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if BUY (long) signal is valid for Kraken.
        
        Kraken strategy: BIDIRECTIONAL
        - Buy on RSI oversold bounce (25-55)
        - Buy when price above EMA support
        - Can wait for better setups (lower fees)
        """
        # RSI in buy zone (wider range than Coinbase)
        rsi_valid = self.buy_rsi_min <= rsi <= self.buy_rsi_max
        
        # Price above EMA9 for momentum
        above_ema9 = price > ema9
        
        # Above EMA21 for trend (can be relaxed)
        above_ema21 = price > ema21
        
        return rsi_valid and (above_ema9 or above_ema21)  # OR instead of AND
    
    def should_sell(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if SELL signal is valid for Kraken.
        
        Kraken strategy: PROFIT-TAKING + EXIT
        - Sell on RSI overbought (> 65)
        - Sell when price drops below EMA support
        - Can hold longer for bigger gains (low fees)
        """
        # RSI overbought (exit long positions)
        rsi_overbought = rsi > self.rsi_overbought
        
        # Price below EMA9 (momentum lost)
        below_ema9 = price < ema9
        
        # Both conditions should be true for stronger signal
        return rsi_overbought and below_ema9
    
    def should_short(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if SHORT signal is valid for Kraken.
        
        Kraken-specific: SHORT SELLING PROFITABLE
        - Short on RSI overbought (60-80)
        - Short when price below EMA resistance
        - Profitable due to low fees (0.36% vs Coinbase 1.4%)
        """
        # RSI in short zone
        rsi_valid = self.short_rsi_min <= rsi <= self.short_rsi_max
        
        # Price below EMA9 (downward momentum)
        below_ema9 = price < ema9
        
        # Below EMA21 (downtrend)
        below_ema21 = price < ema21
        
        return rsi_valid and below_ema9 and below_ema21
    
    def calculate_position_size(self, account_balance: float, signal_strength: float = 1.0) -> float:
        """
        Calculate position size for Kraken.
        
        Args:
            account_balance: Available balance
            signal_strength: Signal quality (0.0 to 1.0)
            
        Returns:
            Position size in USD
        """
        # Base position size (can be larger due to low fees)
        if account_balance < 50:
            base_pct = 0.60  # 60% for small accounts (vs 50% Coinbase)
        elif account_balance < 100:
            base_pct = 0.50  # 50% for medium accounts (vs 40% Coinbase)
        else:
            base_pct = 0.25  # 25% for larger accounts (vs 20% Coinbase)
        
        # Adjust by signal strength
        adjusted_pct = base_pct * signal_strength
        
        # Calculate size
        position_size = account_balance * adjusted_pct
        
        # Enforce minimum (lower than Coinbase)
        return max(position_size, self.min_position_usd)
    
    def get_config_summary(self) -> str:
        """Get configuration summary for logging"""
        futures_status = "✅ ENABLED" if self.enable_futures else "Disabled"
        options_status = "✅ ENABLED" if self.enable_options else "Disabled (in development)"
        fee_advantage = 1.4 / 0.36  # Calculate dynamically: Coinbase 1.4% / Kraken 0.36%
        
        return f"""
Kraken Trading Configuration:
  Broker: {self.broker_display_name}
  Fees: {self.round_trip_cost*100:.2f}% round-trip ({fee_advantage:.1f}x cheaper than Coinbase)
  Strategy: BIDIRECTIONAL (profit both ways)
  Profit Targets: {', '.join([f'{t[0]*100:.1f}%' for t in self.profit_targets])}
  Stop Loss: {self.stop_loss*100:.1f}%
  Max Hold: {self.max_hold_hours} hours (3x longer than Coinbase)
  Min Position: ${self.min_position_usd} (2x smaller than Coinbase)
  Asset Types:
    - Crypto Spot: ✅ ENABLED (primary market)
    - Futures: {futures_status}
    - Stocks: ✅ Available via AlpacaBroker integration
    - Options: {options_status}
  Short Selling: PROFITABLE (vs unprofitable on Coinbase)
  Multi-Asset: ENABLED for master and all users
"""


# Create default instance
KRAKEN_CONFIG = KrakenConfig()
