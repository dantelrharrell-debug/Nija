"""
Alpaca-Specific Trading Configuration

Alpaca Trading characteristics:
- Commission-free stock trading (zero fees)
- Stocks and ETFs (US markets)
- Best strategy: AGGRESSIVE (no fees enable tight profits)
- Market dynamics: US market hours only (9:30 AM - 4:00 PM ET)
- Liquidity: Excellent for major stocks, variable for small caps
- Paper trading available for testing

Strategy Focus:
- Bidirectional trading (no fees = any direction profitable)
- Very tight profit targets possible (0.3%+) due to zero fees
- High frequency trading enabled by zero commissions
- PDT rule awareness (pattern day trader restrictions)
- Market hours constraints (no crypto 24/7 trading)
"""

from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class AlpacaConfig:
    """Alpaca-specific trading configuration"""
    
    # Broker identification
    broker_name: str = "alpaca"
    broker_display_name: str = "Alpaca Trading"
    
    # Fee structure (ZERO commission trading)
    # Only spread costs apply
    taker_fee: float = 0.0  # 0% commission
    maker_fee: float = 0.0  # 0% commission
    spread_cost: float = 0.0010  # ~0.10% average spread (market impact)
    round_trip_cost: float = 0.0020  # 0.20% total (spread only, no commissions!)
    
    # Asset types supported
    supports_crypto: bool = False
    supports_stocks: bool = True
    supports_futures: bool = False
    supports_options: bool = True  # Options trading available (premium tier)
    
    # Trading direction profitability
    # On Alpaca, BOTH directions are highly profitable due to zero commissions
    buy_preferred: bool = True
    sell_preferred: bool = True
    bidirectional: bool = True
    
    # Profit targets (very tight possible due to zero commissions)
    # Can target 0.3%+ and still profit after spread
    profit_targets: List[Tuple[float, str]] = None
    
    def __post_init__(self):
        """Initialize profit targets after dataclass creation"""
        if self.profit_targets is None:
            # NOTE: With 0.20% spread costs, very tight targets are profitable
            # 0.6% target: Net +0.40% after spread (excellent for stocks)
            # 0.4% target: Net +0.20% after spread (good)
            # 0.3% target: Net +0.10% after spread (acceptable, watch slippage)
            self.profit_targets = [
                (0.006, "Profit target +0.6% (Net +0.40% after 0.20% spread) - EXCELLENT"),
                (0.004, "Profit target +0.4% (Net +0.20% after spread) - GOOD"),
                (0.003, "Profit target +0.3% (Net +0.10% after spread) - ACCEPTABLE"),
            ]
    
    # Stop loss (can be tight due to zero commissions)
    stop_loss: float = -0.004  # -0.4% stop loss (tight for stocks)
    stop_loss_warning: float = -0.003  # -0.3% warning
    
    # Position management (stocks trade during market hours only)
    max_hold_hours: float = 6.5  # Maximum one trading day (9:30 AM - 4:00 PM ET)
    stale_warning_hours: float = 3.0  # Warn at 3 hours
    
    # RSI thresholds (moderate - stocks have different dynamics than crypto)
    rsi_overbought: float = 70.0  # Exit when RSI > 70 (traditional stock level)
    rsi_oversold: float = 30.0  # Exit when RSI < 30 (traditional stock level)
    
    # Entry signals (bidirectional - both buy and sell)
    buy_rsi_min: float = 25.0  # Buy in oversold
    buy_rsi_max: float = 60.0  # Buy up to neutral/slightly overbought
    sell_rsi_min: float = 40.0  # Sell from neutral
    sell_rsi_max: float = 75.0  # Sell in overbought
    
    # Short selling thresholds (profitable on Alpaca!)
    short_rsi_min: float = 65.0  # Short when overbought
    short_rsi_max: float = 80.0  # Short in extreme overbought
    
    # Position sizing (stocks typically need larger minimum for liquidity)
    min_position_usd: float = 1.0  # $1 minimum (Alpaca allows fractional shares)
    recommended_min_usd: float = 10.0  # $10+ recommended
    min_balance_to_trade: float = 25.0  # $25 minimum (also accounts for PDT rule threshold)
    
    # Order type preferences
    prefer_limit_orders: bool = True  # Use limit orders for price control
    limit_order_offset_pct: float = 0.0010  # 0.10% from current price
    limit_order_timeout: int = 60  # 60 seconds (faster fill needed in market hours)
    
    # Risk management (conservative for stocks)
    max_positions: int = 10  # Reasonable for stock portfolio
    max_exposure_pct: float = 0.50  # Deploy 50% of capital
    
    # Trade frequency (limited by market hours)
    min_seconds_between_trades: int = 120  # 2 minutes
    max_trades_per_day: int = 50  # 50 trades/day
    
    # PDT (Pattern Day Trader) rule enforcement
    # Accounts under $25k limited to 3 day trades per 5 days
    pdt_threshold: float = 25000.0  # $25,000 minimum to avoid PDT
    pdt_max_day_trades: int = 3  # Maximum 3 day trades in 5 days if under threshold
    enforce_pdt: bool = True  # Enforce PDT rules
    
    # Market hours enforcement
    enforce_market_hours: bool = True  # Only trade during market hours
    extended_hours_enabled: bool = False  # Disable pre-market/after-hours
    
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
        Determine if BUY (long) signal is valid for Alpaca.
        
        Alpaca strategy: AGGRESSIVE due to zero commissions
        - Buy on RSI oversold bounce (25-60)
        - Buy when price above EMA support
        - Zero fees enable aggressive entries
        """
        # RSI in buy zone (wider range for stocks)
        rsi_valid = self.buy_rsi_min <= rsi <= self.buy_rsi_max
        
        # Price above EMA9 for momentum
        above_ema9 = price > ema9
        
        # Above EMA21 for trend (can be relaxed for mean reversion)
        above_ema21 = price > ema21
        
        return rsi_valid and above_ema9  # Only need EMA9 confirmation
    
    def should_sell(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if SELL signal is valid for Alpaca.
        
        Alpaca strategy: QUICK PROFIT-TAKING
        - Sell on RSI overbought (> 70)
        - Sell when price drops below EMA support
        - Zero fees enable frequent exits
        """
        # RSI overbought (exit long positions)
        rsi_overbought = rsi > self.rsi_overbought
        
        # Price below EMA9 (momentum lost)
        below_ema9 = price < ema9
        
        return rsi_overbought or below_ema9
    
    def should_short(self, rsi: float, price: float, ema9: float, ema21: float) -> bool:
        """
        Determine if SHORT signal is valid for Alpaca.
        
        Alpaca strategy: SELECTIVE SHORT SELLING
        - Short on RSI overbought (65-80)
        - Short when price below EMA resistance
        - Zero fees make shorting viable
        """
        # RSI in short zone
        rsi_valid = self.short_rsi_min <= rsi <= self.short_rsi_max
        
        # Price below EMA9 for downward momentum
        below_ema9 = price < ema9
        
        # Below EMA21 for downtrend
        below_ema21 = price < ema21
        
        return rsi_valid and below_ema9  # Need strong downward momentum
    
    def calculate_position_size(self, account_balance: float, signal_strength: float = 1.0, is_pdt_restricted: bool = False) -> float:
        """
        Calculate position size for Alpaca.
        
        Args:
            account_balance: Available balance
            signal_strength: Signal quality (0.0 to 1.0)
            is_pdt_restricted: True if account is under PDT threshold
            
        Returns:
            Position size in USD
        """
        # Base position size (conservative for stocks, more aggressive if not PDT restricted)
        if is_pdt_restricted:
            # PDT restricted: smaller positions to avoid day trading
            base_pct = 0.30  # 30% positions for longer holds
        else:
            # Not PDT restricted: more aggressive
            if account_balance < 100:
                base_pct = 0.50  # 50% for small accounts
            elif account_balance < 500:
                base_pct = 0.40  # 40% for medium accounts
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
Alpaca Trading Configuration:
  Broker: {self.broker_display_name}
  Role: PRIMARY for stocks (zero commissions)
  Min Balance: ${self.min_balance_to_trade}
  Fees: {self.round_trip_cost*100:.2f}% round-trip (ZERO commissions, spread only)
  Strategy: AGGRESSIVE (zero fees = tight profits)
  Profit Targets: {', '.join([f'{t[0]*100:.1f}%' for t in self.profit_targets])}
  Stop Loss: {self.stop_loss*100:.1f}%
  Max Hold: {self.max_hold_hours} hours (market hours only)
  Min Position: ${self.min_position_usd}
  Asset Types: Stocks, ETFs, Options
  Max Positions: {self.max_positions}
  Max Trades/Day: {self.max_trades_per_day}
  PDT Enforcement: {self.enforce_pdt} (threshold: ${self.pdt_threshold:.0f})
"""


# Create default instance
ALPACA_CONFIG = AlpacaConfig()
