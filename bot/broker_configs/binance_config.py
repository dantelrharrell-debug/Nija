"""
Binance-Specific Trading Configuration

Binance Exchange characteristics:
- Low fees: ~0.10% taker, ~0.10% maker (0.28% round-trip with spread)
- Crypto only (spot, futures, margin)
- Best strategy: BIDIRECTIONAL (low fees enable both directions)
- Market dynamics: Highest volume crypto exchange globally
- Liquidity: Excellent for all major pairs, deep order books
- Wide variety of trading pairs (1000+ pairs)

Strategy Focus:
- Bidirectional trading (profit from both directions)
- Low profit targets possible (0.5%+) due to low fees
- High frequency trading enabled by excellent liquidity
- Strong support for futures and margin trading
- Aggressive position sizing due to deep liquidity
"""

from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class BinanceConfig:
    """Binance-specific trading configuration"""
    
    # Broker identification
    broker_name: str = "binance"
    broker_display_name: str = "Binance Exchange"
    
    # Fee structure (LOW fees, BNB discount applied)
    # Note: Base fees are 0.10% taker/maker, reduced to 0.075% with BNB holdings
    # This configuration uses conservative (non-discounted) fees for safety
    # Fee calculation: (taker_fee + maker_fee + spread) = (0.10% + 0.10% + 0.08%) = 0.28%
    # Round-trip assumes taker order on both entry and exit plus spread impact
    # With BNB discount: actual cost could be as low as 0.23% (0.075% + 0.075% + 0.08%)
    taker_fee: float = 0.0010  # 0.10% taker fee (0.075% with BNB)
    maker_fee: float = 0.0010  # 0.10% maker fee (0.075% with BNB)
    spread_cost: float = 0.0008  # ~0.08% average spread (tight due to high volume)
    round_trip_cost: float = 0.0028  # 0.28% total (very competitive)
    
    # Asset types supported
    supports_crypto: bool = True
    supports_stocks: bool = False
    supports_futures: bool = True
    supports_options: bool = True
    supports_margin: bool = True  # Binance supports margin trading
    
    # Trading direction profitability
    # On Binance, BOTH directions are profitable due to low fees and high liquidity
    buy_preferred: bool = True
    sell_preferred: bool = True
    bidirectional: bool = True
    
    # Profit targets (low possible due to 0.28% fees)
    # Can target 0.5%+ and still profit after fees
    profit_targets: List[Tuple[float, str]] = None
    
    def __post_init__(self):
        """Initialize profit targets after dataclass creation"""
        if self.profit_targets is None:
            # NOTE: With 0.28% fees, tight targets are profitable
            # 0.9% target: Net +0.62% after fees (excellent)
            # 0.6% target: Net +0.32% after fees (good)
            # 0.5% target: Net +0.22% after fees (acceptable, watch slippage)
            self.profit_targets = [
                (0.009, "Profit target +0.9% (Net +0.62% after 0.28% fees) - EXCELLENT"),
                (0.006, "Profit target +0.6% (Net +0.32% after fees) - GOOD"),
                (0.005, "Profit target +0.5% (Net +0.22% after fees) - ACCEPTABLE, watch slippage"),
            ]
    
    # Stop loss (can be tight due to low fees)
    stop_loss: float = -0.006  # -0.6% stop loss
    stop_loss_warning: float = -0.004  # -0.4% warning
    
    # Position management (can hold for good setups with low fees)
    max_hold_hours: float = 30.0  # Maximum 30 hours
    stale_warning_hours: float = 15.0  # Warn at 15 hours
    
    # RSI thresholds (moderate - low fees allow waiting for better setups)
    rsi_overbought: float = 65.0  # Exit when RSI > 65
    rsi_oversold: float = 35.0  # Exit when RSI < 35
    
    # Entry signals (bidirectional - both buy and sell)
    buy_rsi_min: float = 25.0  # Buy in deeper oversold
    buy_rsi_max: float = 55.0  # Buy up to neutral
    sell_rsi_min: float = 45.0  # Sell from neutral
    sell_rsi_max: float = 75.0  # Sell in deep overbought
    
    # Short selling thresholds (profitable on Binance!)
    short_rsi_min: float = 60.0  # Short when overbought
    short_rsi_max: float = 80.0  # Short in extreme overbought
    
    # Position sizing (can use small positions profitably)
    min_position_usd: float = 5.0  # $5 minimum (fees only ~$0.014)
    recommended_min_usd: float = 10.0  # $10+ recommended
    min_balance_to_trade: float = 25.0  # $25 minimum - optimal for scaling
    
    # Order type preferences
    prefer_limit_orders: bool = True  # Use limit orders for best fees
    limit_order_offset_pct: float = 0.0005  # 0.05% from current price (tight)
    limit_order_timeout: int = 90  # 90 seconds
    
    # Risk management (aggressive due to high liquidity and low fees)
    max_positions: int = 12  # High number of positions allowed
    max_exposure_pct: float = 0.65  # Can deploy 65% of capital
    
    # Trade frequency (high frequency enabled by low fees and liquidity)
    min_seconds_between_trades: int = 100  # 100 seconds (~1.5 minutes)
    max_trades_per_day: int = 70  # 70 trades/day (high volume)
    
    # Futures and margin support
    enable_futures: bool = True  # Enable futures trading
    enable_margin: bool = False  # Disable margin for now (higher risk)
    enable_options: bool = False  # Disable options (complex)
    futures_leverage_max: float = 5.0  # Max 5x leverage for futures
    margin_leverage_max: float = 3.0  # Max 3x leverage for margin
    
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
        Determine if BUY (long) signal is valid for Binance.
        
        Binance strategy: BIDIRECTIONAL with quality entries
        - Buy on RSI oversold bounce (25-55)
        - Buy when price above EMA support
        - Low fees enable selective entries
        """
        # RSI in buy zone
        rsi_valid = self.buy_rsi_min <= rsi <= self.buy_rsi_max
        
        # Price above EMA9 for momentum
        above_ema9 = price > ema9
        
        # Above EMA21 for trend (can be relaxed)
        above_ema21 = price > ema21
        
        return rsi_valid and (above_ema9 or above_ema21)
    
    def should_sell(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if SELL signal is valid for Binance.
        
        Binance strategy: EFFICIENT PROFIT-TAKING
        - Sell on RSI overbought (> 65)
        - Sell when price drops below EMA support
        - Low fees enable frequent profit-taking
        """
        # RSI overbought (exit long positions)
        rsi_overbought = rsi > self.rsi_overbought
        
        # Price below EMA9 (momentum lost)
        below_ema9 = price < ema9
        
        return rsi_overbought or below_ema9
    
    def should_short(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if SHORT signal is valid for Binance.
        
        Binance strategy: AGGRESSIVE SHORT SELLING
        - Short on RSI overbought (60-80)
        - Short when price below EMA resistance
        - Low fees and high liquidity make shorting profitable
        """
        # RSI in short zone
        rsi_valid = self.short_rsi_min <= rsi <= self.short_rsi_max
        
        # Price below EMA9 for downward momentum
        below_ema9 = price < ema9
        
        # Below EMA21 for downtrend
        below_ema21 = price < ema21
        
        return rsi_valid and (below_ema9 or below_ema21)
    
    def calculate_position_size(self, account_balance: float, signal_strength: float = 1.0) -> float:
        """
        Calculate position size for Binance.
        
        Args:
            account_balance: Available balance
            signal_strength: Signal quality (0.0 to 1.0)
            
        Returns:
            Position size in USD
        """
        # Base position size (aggressive due to low fees and high liquidity)
        if account_balance < 50:
            base_pct = 0.55  # 55% for small accounts
        elif account_balance < 100:
            base_pct = 0.45  # 45% for medium accounts
        else:
            base_pct = 0.25  # 25% for larger accounts
        
        # Adjust by signal strength
        adjusted_pct = base_pct * signal_strength
        
        # Calculate size
        position_size = account_balance * adjusted_pct
        
        # Enforce minimum
        return max(position_size, self.min_position_usd)
    
    def get_config_summary(self) -> str:
        """Get configuration summary for logging"""
        return f"""
Binance Trading Configuration:
  Broker: {self.broker_display_name}
  Role: PRIMARY (low fees, highest liquidity)
  Min Balance: ${self.min_balance_to_trade}
  Fees: {self.round_trip_cost*100:.2f}% round-trip (very low)
  Strategy: BIDIRECTIONAL (low fees = high frequency)
  Profit Targets: {', '.join([f'{t[0]*100:.1f}%' for t in self.profit_targets])}
  Stop Loss: {self.stop_loss*100:.1f}%
  Max Hold: {self.max_hold_hours} hours
  Min Position: ${self.min_position_usd}
  Asset Types: Crypto, Futures
  Max Positions: {self.max_positions}
  Max Trades/Day: {self.max_trades_per_day}
"""


# Create default instance
BINANCE_CONFIG = BinanceConfig()
