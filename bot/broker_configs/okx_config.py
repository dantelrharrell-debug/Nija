"""
OKX-Specific Trading Configuration

OKX Exchange characteristics:
- Low fees: ~0.08% taker, ~0.06% maker (0.20% round-trip with spread)
- Crypto + Futures + Perpetuals + Options
- Best strategy: BIDIRECTIONAL (very low fees enable both directions)
- Market dynamics: High-volume international exchange
- Liquidity: Excellent for major pairs, good for derivatives
- Advanced order types and leverage trading

Strategy Focus:
- Bidirectional trading (profit from both directions)
- Very low profit targets possible (0.4%+) due to ultra-low fees
- Can hold positions longer (minimal fee pressure)
- Strong support for futures and perpetuals
- Aggressive trading frequency enabled by low fees
"""

from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class OKXConfig:
    """OKX-specific trading configuration"""
    
    # Broker identification
    broker_name: str = "okx"
    broker_display_name: str = "OKX Exchange"
    
    # Fee structure (LOWEST fees of all major exchanges)
    # Fee calculation: (taker_fee + maker_fee + spread) = (0.08% + 0.06% + 0.06%) = 0.20%
    # Round-trip assumes one taker order (entry/exit) and spread impact on both sides
    taker_fee: float = 0.0008  # 0.08% taker fee (VIP tier, ultra-low)
    maker_fee: float = 0.0006  # 0.06% maker fee (VIP tier, ultra-low)
    spread_cost: float = 0.0006  # ~0.06% average spread (very tight)
    round_trip_cost: float = 0.0020  # 0.20% total (lowest in the market!)
    
    # Asset types supported
    supports_crypto: bool = True
    supports_stocks: bool = False
    supports_futures: bool = True
    supports_options: bool = True
    supports_perpetuals: bool = True  # OKX specializes in perpetuals
    
    # Trading direction profitability
    # On OKX, BOTH directions are highly profitable due to ultra-low fees
    buy_preferred: bool = True
    sell_preferred: bool = True
    bidirectional: bool = True
    
    # Profit targets (very low possible due to 0.20% fees)
    # Can target 0.4%+ and still profit after fees
    profit_targets: List[Tuple[float, str]] = None
    
    def __post_init__(self):
        """Initialize profit targets after dataclass creation"""
        if self.profit_targets is None:
            # NOTE: With 0.20% fees, very tight targets are profitable
            # 0.8% target: Net +0.60% after fees (excellent)
            # 0.6% target: Net +0.40% after fees (very good)
            # 0.4% target: Net +0.20% after fees (good, watch slippage)
            self.profit_targets = [
                (0.008, "Profit target +0.8% (Net +0.60% after 0.20% fees) - EXCELLENT"),
                (0.006, "Profit target +0.6% (Net +0.40% after fees) - VERY GOOD"),
                (0.004, "Profit target +0.4% (Net +0.20% after fees) - GOOD, watch slippage"),
            ]
    
    # Stop loss (can be very tight due to ultra-low fees)
    stop_loss: float = -0.005  # -0.5% stop loss (tightest of all brokers)
    stop_loss_warning: float = -0.003  # -0.3% warning
    
    # Position management (can hold longer with ultra-low fees)
    max_hold_hours: float = 36.0  # Maximum 36 hours (longest hold time)
    stale_warning_hours: float = 18.0  # Warn at 18 hours
    
    # RSI thresholds (moderate - low fees allow patience)
    rsi_overbought: float = 65.0  # Exit when RSI > 65
    rsi_oversold: float = 35.0  # Exit when RSI < 35
    
    # Entry signals (bidirectional - both buy and sell)
    buy_rsi_min: float = 25.0  # Buy in deeper oversold
    buy_rsi_max: float = 55.0  # Buy up to neutral
    sell_rsi_min: float = 45.0  # Sell from neutral
    sell_rsi_max: float = 75.0  # Sell in deep overbought
    
    # Short selling thresholds (highly profitable on OKX!)
    short_rsi_min: float = 60.0  # Short when overbought
    short_rsi_max: float = 80.0  # Short in extreme overbought
    
    # Position sizing (can use very small positions profitably)
    min_position_usd: float = 5.0  # $5 minimum (fees only ~$0.01)
    recommended_min_usd: float = 10.0  # $10+ recommended
    min_balance_to_trade: float = 25.0  # $25 minimum - optimal for scaling with ultra-low fees
    
    # Order type preferences
    prefer_limit_orders: bool = True  # Use limit orders for best fees
    limit_order_offset_pct: float = 0.0005  # 0.05% from current price (tight)
    limit_order_timeout: int = 90  # 90 seconds
    
    # Risk management (can be more aggressive with low fees)
    max_positions: int = 15  # Most positions allowed (lowest fees enable high frequency)
    max_exposure_pct: float = 0.70  # Can deploy 70% of capital (highest allocation)
    
    # Trade frequency (highest frequency due to lowest fees)
    min_seconds_between_trades: int = 90  # 90 seconds (fastest allowed)
    max_trades_per_day: int = 80  # 80 trades/day (highest volume)
    
    # Futures and perpetuals support
    enable_futures: bool = True  # Enable futures trading
    enable_perpetuals: bool = True  # Enable perpetual swaps (OKX specialty)
    enable_options: bool = False  # Disable options for now (complex)
    futures_leverage_max: float = 5.0  # Max 5x leverage for futures
    perpetuals_leverage_max: float = 3.0  # Max 3x leverage for perpetuals
    
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
        Determine if BUY (long) signal is valid for OKX.
        
        OKX strategy: BIDIRECTIONAL with tight entries
        - Buy on RSI oversold bounce (25-55)
        - Buy when price above EMA support
        - Ultra-low fees enable tight entries
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
        Determine if SELL signal is valid for OKX.
        
        OKX strategy: QUICK PROFIT-TAKING
        - Sell on RSI overbought (> 65)
        - Sell when price drops below EMA support
        - Low fees enable frequent exits and re-entries
        """
        # RSI overbought (exit long positions)
        rsi_overbought = rsi > self.rsi_overbought
        
        # Price below EMA9 (momentum lost)
        below_ema9 = price < ema9
        
        return rsi_overbought or below_ema9
    
    def should_short(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if SHORT signal is valid for OKX.
        
        OKX strategy: AGGRESSIVE SHORT SELLING
        - Short on RSI overbought (60-80)
        - Short when price below EMA resistance
        - Ultra-low fees make shorting highly profitable
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
        Calculate position size for OKX.
        
        Args:
            account_balance: Available balance
            signal_strength: Signal quality (0.0 to 1.0)
            
        Returns:
            Position size in USD
        """
        # Base position size (aggressive due to low fees)
        if account_balance < 50:
            base_pct = 0.60  # 60% for small accounts (highest allocation)
        elif account_balance < 100:
            base_pct = 0.50  # 50% for medium accounts
        else:
            base_pct = 0.30  # 30% for larger accounts
        
        # Adjust by signal strength
        adjusted_pct = base_pct * signal_strength
        
        # Calculate size
        position_size = account_balance * adjusted_pct
        
        # Enforce minimum
        return max(position_size, self.min_position_usd)
    
    def get_config_summary(self) -> str:
        """Get configuration summary for logging"""
        return f"""
OKX Trading Configuration:
  Broker: {self.broker_display_name}
  Role: PRIMARY (ultra-low fees for scaling)
  Min Balance: ${self.min_balance_to_trade}
  Fees: {self.round_trip_cost*100:.2f}% round-trip (LOWEST)
  Strategy: BIDIRECTIONAL (ultra-low fees = high frequency)
  Profit Targets: {', '.join([f'{t[0]*100:.1f}%' for t in self.profit_targets])}
  Stop Loss: {self.stop_loss*100:.1f}%
  Max Hold: {self.max_hold_hours} hours
  Min Position: ${self.min_position_usd}
  Asset Types: Crypto, Futures, Perpetuals
  Max Positions: {self.max_positions}
  Max Trades/Day: {self.max_trades_per_day}
"""


# Create default instance
OKX_CONFIG = OKXConfig()
