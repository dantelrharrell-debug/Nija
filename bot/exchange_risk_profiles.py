"""
NIJA Exchange-Specific Risk Profiles
Different risk parameters for each exchange based on:
- Fee structures
- Liquidity characteristics
- Volatility patterns
- Historical performance
- Regulatory environment

Version: 1.0
Author: NIJA Trading Systems
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("nija.exchange_risk")


class ExchangeType(Enum):
    """Supported exchanges"""
    COINBASE = "coinbase"
    BINANCE = "binance"
    OKX = "okx"
    KRAKEN = "kraken"
    ALPACA = "alpaca"


@dataclass
class ExchangeRiskProfile:
    """Risk parameters for a specific exchange"""
    
    # Exchange identification
    exchange_name: str
    exchange_type: ExchangeType
    
    # Fee structure (as decimals, e.g., 0.006 = 0.6%)
    maker_fee: float  # Limit order fee
    taker_fee: float  # Market order fee
    withdrawal_fee_usd: float  # Typical withdrawal fee
    
    # Position sizing adjustments
    min_position_size_usd: float  # Minimum viable position
    max_position_size_pct: float  # Max % of account per trade
    recommended_position_pct: float  # Recommended position size
    
    # Stop-loss parameters (as decimals)
    min_stop_loss_pct: float  # Minimum stop distance
    max_stop_loss_pct: float  # Maximum stop distance
    recommended_stop_loss_pct: float  # Recommended stop
    
    # Take-profit parameters (as decimals)
    min_take_profit_pct: float  # Minimum TP to cover fees
    tp1_target_pct: float  # First profit target
    tp2_target_pct: float  # Second profit target
    tp3_target_pct: float  # Third profit target
    
    # Risk multipliers (1.0 = neutral)
    volatility_multiplier: float  # Adjust for exchange volatility
    liquidity_multiplier: float  # Adjust for liquidity depth
    risk_score: float  # Overall risk score (0-10, 10 = riskiest)
    
    # Trading constraints
    max_trades_per_day: int
    max_open_positions: int
    max_total_exposure_pct: float  # Max total capital on exchange
    
    # Exchange-specific features
    supports_limit_orders: bool
    supports_stop_loss_orders: bool
    supports_trailing_stops: bool
    has_maker_rebates: bool
    
    # Performance tracking
    historical_win_rate: Optional[float] = None
    avg_trade_duration_hours: Optional[float] = None
    
    def get_break_even_profit_pct(self, use_limit_order: bool = True) -> float:
        """
        Calculate break-even profit percentage including fees
        
        Args:
            use_limit_order: True for maker fees, False for taker
            
        Returns:
            Break-even profit % as decimal
        """
        fee = self.maker_fee if use_limit_order else self.taker_fee
        # Round-trip cost (buy + sell)
        round_trip_cost = fee * 2
        # Add small buffer for slippage and price movement
        break_even = round_trip_cost * 1.2
        return break_even
    
    def get_adjusted_position_size(self, base_size_pct: float, 
                                   account_balance: float) -> float:
        """
        Get exchange-adjusted position size
        
        Args:
            base_size_pct: Base position size as % (e.g., 0.05 = 5%)
            account_balance: Current account balance
            
        Returns:
            Adjusted position size in USD
        """
        # Apply exchange risk multipliers
        adjusted_pct = base_size_pct * self.liquidity_multiplier
        adjusted_pct = min(adjusted_pct, self.max_position_size_pct)
        adjusted_pct = max(adjusted_pct, self.min_position_size_usd / account_balance)
        
        position_usd = account_balance * adjusted_pct
        position_usd = max(position_usd, self.min_position_size_usd)
        
        return position_usd
    
    def get_adjusted_stop_loss(self, base_stop_pct: float) -> float:
        """
        Get exchange-adjusted stop-loss percentage
        
        Args:
            base_stop_pct: Base stop-loss %
            
        Returns:
            Adjusted stop-loss % as decimal
        """
        # Adjust for exchange volatility
        adjusted_stop = base_stop_pct * self.volatility_multiplier
        
        # Ensure within min/max bounds
        adjusted_stop = max(adjusted_stop, self.min_stop_loss_pct)
        adjusted_stop = min(adjusted_stop, self.max_stop_loss_pct)
        
        return adjusted_stop


# ============================================================================
# EXCHANGE RISK PROFILES
# ============================================================================

EXCHANGE_PROFILES = {
    ExchangeType.COINBASE: ExchangeRiskProfile(
        exchange_name="Coinbase Advanced Trade",
        exchange_type=ExchangeType.COINBASE,
        
        # Coinbase fees (Advanced Trade)
        maker_fee=0.004,  # 0.4% maker (limit orders)
        taker_fee=0.006,  # 0.6% taker (market orders)
        withdrawal_fee_usd=0.0,  # Free withdrawals to Coinbase wallet
        
        # Position sizing (conservative due to higher fees)
        min_position_size_usd=10.0,  # $10 minimum
        max_position_size_pct=0.15,  # 15% max per trade
        recommended_position_pct=0.08,  # 8% recommended
        
        # Stop-loss parameters
        min_stop_loss_pct=0.008,  # 0.8% minimum
        max_stop_loss_pct=0.025,  # 2.5% maximum
        recommended_stop_loss_pct=0.015,  # 1.5% recommended
        
        # Take-profit parameters
        min_take_profit_pct=0.015,  # 1.5% minimum (covers fees)
        tp1_target_pct=0.025,  # 2.5%
        tp2_target_pct=0.040,  # 4.0%
        tp3_target_pct=0.060,  # 6.0%
        
        # Risk adjustments
        volatility_multiplier=1.0,  # Average volatility
        liquidity_multiplier=1.0,  # Good liquidity
        risk_score=4.0,  # Medium-low risk
        
        # Trading constraints
        max_trades_per_day=30,
        max_open_positions=8,
        max_total_exposure_pct=0.40,  # 40% max on Coinbase
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=False,  # Not native
        has_maker_rebates=False,
    ),
    
    ExchangeType.BINANCE: ExchangeRiskProfile(
        exchange_name="Binance",
        exchange_type=ExchangeType.BINANCE,
        
        # Binance fees (lowest in industry)
        maker_fee=0.001,  # 0.1% maker
        taker_fee=0.001,  # 0.1% taker
        withdrawal_fee_usd=1.0,  # ~$1 typical
        
        # Position sizing (more aggressive due to low fees)
        min_position_size_usd=5.0,  # $5 minimum
        max_position_size_pct=0.20,  # 20% max per trade
        recommended_position_pct=0.12,  # 12% recommended
        
        # Stop-loss parameters
        min_stop_loss_pct=0.005,  # 0.5% minimum
        max_stop_loss_pct=0.020,  # 2.0% maximum
        recommended_stop_loss_pct=0.010,  # 1.0% recommended
        
        # Take-profit parameters (can be tighter due to low fees)
        min_take_profit_pct=0.008,  # 0.8% minimum
        tp1_target_pct=0.015,  # 1.5%
        tp2_target_pct=0.025,  # 2.5%
        tp3_target_pct=0.040,  # 4.0%
        
        # Risk adjustments
        volatility_multiplier=1.1,  # Slightly higher volatility
        liquidity_multiplier=1.2,  # Excellent liquidity
        risk_score=5.0,  # Medium risk (regulatory uncertainty)
        
        # Trading constraints
        max_trades_per_day=50,  # More trades allowed (lower fees)
        max_open_positions=12,
        max_total_exposure_pct=0.35,  # 35% max on Binance
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=True,
        has_maker_rebates=True,  # VIP tiers
    ),
    
    ExchangeType.OKX: ExchangeRiskProfile(
        exchange_name="OKX",
        exchange_type=ExchangeType.OKX,
        
        # OKX fees
        maker_fee=0.0008,  # 0.08% maker
        taker_fee=0.0010,  # 0.10% taker
        withdrawal_fee_usd=1.5,  # ~$1.50 typical
        
        # Position sizing
        min_position_size_usd=5.0,  # $5 minimum
        max_position_size_pct=0.18,  # 18% max per trade
        recommended_position_pct=0.10,  # 10% recommended
        
        # Stop-loss parameters
        min_stop_loss_pct=0.006,  # 0.6% minimum
        max_stop_loss_pct=0.020,  # 2.0% maximum
        recommended_stop_loss_pct=0.012,  # 1.2% recommended
        
        # Take-profit parameters
        min_take_profit_pct=0.010,  # 1.0% minimum
        tp1_target_pct=0.018,  # 1.8%
        tp2_target_pct=0.030,  # 3.0%
        tp3_target_pct=0.045,  # 4.5%
        
        # Risk adjustments
        volatility_multiplier=1.05,  # Slightly elevated
        liquidity_multiplier=1.15,  # Very good liquidity
        risk_score=4.5,  # Medium risk
        
        # Trading constraints
        max_trades_per_day=40,
        max_open_positions=10,
        max_total_exposure_pct=0.30,  # 30% max on OKX
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=True,
        has_maker_rebates=True,
    ),
    
    ExchangeType.KRAKEN: ExchangeRiskProfile(
        exchange_name="Kraken Pro",
        exchange_type=ExchangeType.KRAKEN,
        
        # Kraken fees
        maker_fee=0.0016,  # 0.16% maker
        taker_fee=0.0026,  # 0.26% taker
        withdrawal_fee_usd=0.5,  # ~$0.50 typical
        
        # Position sizing
        min_position_size_usd=10.0,  # $10 minimum
        max_position_size_pct=0.15,  # 15% max per trade
        recommended_position_pct=0.09,  # 9% recommended
        
        # Stop-loss parameters
        min_stop_loss_pct=0.008,  # 0.8% minimum
        max_stop_loss_pct=0.022,  # 2.2% maximum
        recommended_stop_loss_pct=0.014,  # 1.4% recommended
        
        # Take-profit parameters
        min_take_profit_pct=0.012,  # 1.2% minimum
        tp1_target_pct=0.020,  # 2.0%
        tp2_target_pct=0.035,  # 3.5%
        tp3_target_pct=0.050,  # 5.0%
        
        # Risk adjustments
        volatility_multiplier=0.95,  # Lower volatility
        liquidity_multiplier=1.0,  # Good liquidity
        risk_score=3.0,  # Low risk (regulated, established)
        
        # Trading constraints
        max_trades_per_day=35,
        max_open_positions=8,
        max_total_exposure_pct=0.25,  # 25% max on Kraken
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=False,
        has_maker_rebates=True,
    ),
    
    ExchangeType.ALPACA: ExchangeRiskProfile(
        exchange_name="Alpaca Markets",
        exchange_type=ExchangeType.ALPACA,
        
        # Alpaca fees (stock trading)
        maker_fee=0.0,  # Commission-free
        taker_fee=0.0,  # Commission-free
        withdrawal_fee_usd=0.0,  # Free
        
        # Position sizing (stocks have different dynamics)
        min_position_size_usd=25.0,  # $25 minimum (stocks)
        max_position_size_pct=0.10,  # 10% max per trade
        recommended_position_pct=0.05,  # 5% recommended
        
        # Stop-loss parameters (tighter for stocks)
        min_stop_loss_pct=0.005,  # 0.5% minimum
        max_stop_loss_pct=0.015,  # 1.5% maximum
        recommended_stop_loss_pct=0.008,  # 0.8% recommended
        
        # Take-profit parameters
        min_take_profit_pct=0.008,  # 0.8% minimum
        tp1_target_pct=0.012,  # 1.2%
        tp2_target_pct=0.020,  # 2.0%
        tp3_target_pct=0.030,  # 3.0%
        
        # Risk adjustments
        volatility_multiplier=0.8,  # Lower than crypto
        liquidity_multiplier=1.1,  # Good stock liquidity
        risk_score=2.5,  # Low risk (regulated, established)
        
        # Trading constraints
        max_trades_per_day=25,  # PDT rules may apply
        max_open_positions=6,
        max_total_exposure_pct=0.30,  # 30% max
        
        # Features
        supports_limit_orders=True,
        supports_stop_loss_orders=True,
        supports_trailing_stops=True,
        has_maker_rebates=False,
    ),
}


class ExchangeRiskManager:
    """Manages risk across multiple exchanges"""
    
    def __init__(self):
        """Initialize exchange risk manager"""
        self.profiles = EXCHANGE_PROFILES
        logger.info("🛡️ Exchange Risk Manager initialized")
        logger.info(f"   Loaded profiles for {len(self.profiles)} exchanges")
    
    def get_profile(self, exchange: ExchangeType) -> ExchangeRiskProfile:
        """
        Get risk profile for an exchange
        
        Args:
            exchange: Exchange type
            
        Returns:
            Exchange risk profile
        """
        return self.profiles[exchange]
    
    def get_optimal_position_size(self, exchange: ExchangeType, 
                                  base_position_pct: float,
                                  account_balance: float) -> float:
        """
        Calculate optimal position size for exchange
        
        Args:
            exchange: Exchange type
            base_position_pct: Base position size
            account_balance: Account balance on exchange
            
        Returns:
            Position size in USD
        """
        profile = self.get_profile(exchange)
        return profile.get_adjusted_position_size(base_position_pct, account_balance)
    
    def get_optimal_stop_loss(self, exchange: ExchangeType,
                             base_stop_pct: float) -> float:
        """
        Get exchange-specific stop-loss percentage
        
        Args:
            exchange: Exchange type
            base_stop_pct: Base stop-loss %
            
        Returns:
            Adjusted stop-loss % as decimal
        """
        profile = self.get_profile(exchange)
        return profile.get_adjusted_stop_loss(base_stop_pct)
    
    def compare_exchanges(self) -> str:
        """
        Generate comparison report of all exchanges
        
        Returns:
            Formatted comparison string
        """
        report = [
            "\n" + "=" * 90,
            "EXCHANGE RISK PROFILE COMPARISON",
            "=" * 90,
            ""
        ]
        
        for exchange_type, profile in self.profiles.items():
            report.extend([
                f"\n{profile.exchange_name} ({exchange_type.value.upper()})",
                "-" * 90,
                f"  Fees: Maker {profile.maker_fee*100:.2f}% | Taker {profile.taker_fee*100:.2f}%",
                f"  Break-Even: {profile.get_break_even_profit_pct(True)*100:.2f}% (limit) | "
                f"{profile.get_break_even_profit_pct(False)*100:.2f}% (market)",
                f"  Position Size: {profile.min_position_size_usd:.0f}-{profile.recommended_position_pct*100:.0f}% "
                f"(max {profile.max_position_size_pct*100:.0f}%)",
                f"  Stop-Loss: {profile.min_stop_loss_pct*100:.2f}%-{profile.max_stop_loss_pct*100:.2f}% "
                f"(recommended {profile.recommended_stop_loss_pct*100:.2f}%)",
                f"  Take-Profit Targets: {profile.tp1_target_pct*100:.1f}% | "
                f"{profile.tp2_target_pct*100:.1f}% | {profile.tp3_target_pct*100:.1f}%",
                f"  Risk Score: {profile.risk_score}/10",
                f"  Max Trades/Day: {profile.max_trades_per_day}",
                f"  Max Exposure: {profile.max_total_exposure_pct*100:.0f}%",
                f"  Features: {'Limit' if profile.supports_limit_orders else ''} "
                f"{'| Stop-Loss' if profile.supports_stop_loss_orders else ''} "
                f"{'| Trailing' if profile.supports_trailing_stops else ''} "
                f"{'| Rebates' if profile.has_maker_rebates else ''}",
            ])
        
        report.extend(["", "=" * 90, ""])
        return "\n".join(report)


# Singleton instance
_risk_manager_instance: Optional[ExchangeRiskManager] = None

def get_exchange_risk_manager() -> ExchangeRiskManager:
    """Get singleton instance of ExchangeRiskManager"""
    global _risk_manager_instance
    if _risk_manager_instance is None:
        _risk_manager_instance = ExchangeRiskManager()
    return _risk_manager_instance


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    manager = ExchangeRiskManager()
    print(manager.compare_exchanges())
    
    # Example calculations
    print("\nExample Position Size Calculations ($1000 account, 5% base):")
    print("-" * 60)
    for exchange in ExchangeType:
        pos_size = manager.get_optimal_position_size(exchange, 0.05, 1000.0)
        print(f"{exchange.value:12s}: ${pos_size:.2f}")
