"""
NIJA Asset Class Engines

This module implements specialized trading engines for each asset class:
1. CryptoEngine - Cryptocurrency trading (BTC, ETH, altcoins)
2. EquityEngine - Stock and ETF trading
3. DerivativesEngine - Futures and options (Phase 2)

Each engine implements asset-class-specific strategies while sharing
common interfaces for execution and risk management.

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("nija.asset_engines")


class StrategyType(Enum):
    """Available strategy types per asset class."""
    # Crypto strategies
    CRYPTO_MOMENTUM_SCALPING = "crypto_momentum_scalping"
    CRYPTO_TREND_RIDING = "crypto_trend_riding"
    CRYPTO_MARKET_MAKING = "crypto_market_making"
    CRYPTO_ARBITRAGE = "crypto_arbitrage"
    CRYPTO_VOLATILITY_CAPTURE = "crypto_volatility_capture"

    # Equity strategies
    EQUITY_AI_MOMENTUM_SWING = "equity_ai_momentum_swing"
    EQUITY_EARNINGS_VOLATILITY = "equity_earnings_volatility"
    EQUITY_MEAN_REVERSION = "equity_mean_reversion"
    EQUITY_ETF_ROTATION = "equity_etf_rotation"

    # Derivatives strategies (Phase 2)
    DERIVATIVES_MACRO_TREND = "derivatives_macro_trend"
    DERIVATIVES_INDEX_SCALPING = "derivatives_index_scalping"
    DERIVATIVES_VOLATILITY_BREAKOUT = "derivatives_volatility_breakout"


@dataclass
class StrategyConfig:
    """Configuration for a trading strategy."""
    name: str
    enabled: bool = True
    max_positions: int = 3
    risk_per_trade_pct: float = 2.0
    min_trade_size: float = 10.0
    max_trade_size: float = 1000.0


class BaseAssetEngine(ABC):
    """
    Base class for all asset engines.

    Each asset engine must implement:
    - Strategy selection based on market conditions
    - Asset-specific execution logic
    - Risk management for that asset class
    """

    def __init__(self, capital: float, user_tier: str):
        """
        Initialize asset engine.

        Args:
            capital: Allocated capital for this asset class
            user_tier: User's subscription tier
        """
        self.capital = capital
        self.user_tier = user_tier
        self.active_positions = []

    @abstractmethod
    def select_strategy(self, market_conditions: Dict) -> StrategyType:
        """Select optimal strategy based on market conditions."""
        pass

    @abstractmethod
    def scan_opportunities(self) -> List[Dict]:
        """Scan for trading opportunities in this asset class."""
        pass

    @abstractmethod
    def execute_trade(self, signal: Dict) -> bool:
        """Execute a trade in this asset class."""
        pass

    @abstractmethod
    def get_available_capital(self) -> float:
        """Get available capital for new positions."""
        pass


class CryptoEngine(BaseAssetEngine):
    """
    Cryptocurrency trading engine.

    Strategies:
    - Momentum scalping (primary)
    - Trend riding
    - Market making
    - Arbitrage
    - Volatility capture

    This engine interfaces with existing crypto infrastructure:
    - bot/trading_strategy.py (current APEX strategy)
    - bot/broker_integration.py (Coinbase, Kraken, Binance, OKX)
    """

    def __init__(self, capital: float, user_tier: str):
        super().__init__(capital, user_tier)
        self.strategy_configs = {
            StrategyType.CRYPTO_MOMENTUM_SCALPING: StrategyConfig(
                name="Crypto Momentum Scalping",
                enabled=True,
                max_positions=5,
                risk_per_trade_pct=3.0,
                min_trade_size=10.0
            ),
            StrategyType.CRYPTO_TREND_RIDING: StrategyConfig(
                name="Crypto Trend Riding",
                enabled=True,
                max_positions=3,
                risk_per_trade_pct=2.5,
                min_trade_size=20.0
            ),
            StrategyType.CRYPTO_VOLATILITY_CAPTURE: StrategyConfig(
                name="Crypto Volatility Capture",
                enabled=True,
                max_positions=3,
                risk_per_trade_pct=2.0,
                min_trade_size=15.0
            )
        }
        logger.info(f"CryptoEngine initialized with ${capital:.2f}")

    def select_strategy(self, market_conditions: Dict) -> StrategyType:
        """
        Select crypto strategy based on market conditions.

        Logic:
        - High volatility (>60) → Momentum scalping
        - Strong trend → Trend riding
        - Otherwise → Volatility capture
        """
        volatility = market_conditions.get('crypto_volatility', 50)
        momentum = market_conditions.get('crypto_momentum', 0)

        if volatility > 60:
            return StrategyType.CRYPTO_MOMENTUM_SCALPING
        elif abs(momentum) > 40:
            return StrategyType.CRYPTO_TREND_RIDING
        else:
            return StrategyType.CRYPTO_VOLATILITY_CAPTURE

    def scan_opportunities(self) -> List[Dict]:
        """
        Scan crypto markets for opportunities.

        This delegates to existing bot/trading_strategy.py logic.
        For now, returns empty list (to be integrated).
        """
        # TODO: Integrate with bot/trading_strategy.py
        logger.info("Scanning crypto markets...")
        return []

    def execute_trade(self, signal: Dict) -> bool:
        """
        Execute crypto trade.

        This delegates to existing bot/broker_integration.py.
        """
        # TODO: Integrate with bot/broker_integration.py
        logger.info(f"Executing crypto trade: {signal}")
        return False

    def get_available_capital(self) -> float:
        """Get available capital for new crypto positions."""
        # Subtract capital allocated to active positions
        allocated = sum(pos.get('size', 0) for pos in self.active_positions)
        return max(0, self.capital - allocated)


class EquityEngine(BaseAssetEngine):
    """
    Equity (stock/ETF) trading engine.

    Strategies:
    - AI momentum swing trades
    - Earnings volatility capture
    - Mean reversion
    - ETF rotation

    This engine will interface with stock brokers:
    - Alpaca (primary)
    - Interactive Brokers
    - TD Ameritrade
    """

    def __init__(self, capital: float, user_tier: str):
        super().__init__(capital, user_tier)
        self.strategy_configs = {
            StrategyType.EQUITY_AI_MOMENTUM_SWING: StrategyConfig(
                name="AI Momentum Swing",
                enabled=True,
                max_positions=5,
                risk_per_trade_pct=2.0,
                min_trade_size=20.0
            ),
            StrategyType.EQUITY_MEAN_REVERSION: StrategyConfig(
                name="Mean Reversion",
                enabled=True,
                max_positions=3,
                risk_per_trade_pct=1.5,
                min_trade_size=25.0
            ),
            StrategyType.EQUITY_ETF_ROTATION: StrategyConfig(
                name="ETF Rotation",
                enabled=True,
                max_positions=3,
                risk_per_trade_pct=2.5,
                min_trade_size=50.0
            )
        }
        logger.info(f"EquityEngine initialized with ${capital:.2f}")

    def select_strategy(self, market_conditions: Dict) -> StrategyType:
        """
        Select equity strategy based on market conditions.

        Logic:
        - Strong momentum → AI momentum swing
        - High volatility → Earnings volatility
        - Ranging market → Mean reversion or ETF rotation
        """
        momentum = market_conditions.get('equity_momentum', 0)
        volatility = market_conditions.get('equity_volatility', 20)

        if abs(momentum) > 30:
            return StrategyType.EQUITY_AI_MOMENTUM_SWING
        elif volatility > 30:
            return StrategyType.EQUITY_EARNINGS_VOLATILITY
        elif volatility < 15:
            return StrategyType.EQUITY_MEAN_REVERSION
        else:
            return StrategyType.EQUITY_ETF_ROTATION

    def scan_opportunities(self) -> List[Dict]:
        """
        Scan equity markets for opportunities.

        TODO: Implement stock screening logic.
        """
        logger.info("Scanning equity markets...")
        # Placeholder - to be implemented
        return []

    def execute_trade(self, signal: Dict) -> bool:
        """
        Execute equity trade via stock broker API.

        TODO: Integrate with Alpaca/IB APIs.
        """
        logger.info(f"Executing equity trade: {signal}")
        # Placeholder - to be implemented
        return False

    def get_available_capital(self) -> float:
        """Get available capital for new equity positions."""
        allocated = sum(pos.get('size', 0) for pos in self.active_positions)
        return max(0, self.capital - allocated)


class DerivativesEngine(BaseAssetEngine):
    """
    Derivatives (futures/options) trading engine.

    Strategies (Phase 2):
    - Macro trend AI
    - Index scalping
    - Volatility breakout

    This engine will interface with derivatives brokers:
    - Interactive Brokers (primary)
    - TD Ameritrade
    """

    def __init__(self, capital: float, user_tier: str):
        super().__init__(capital, user_tier)
        self.strategy_configs = {
            StrategyType.DERIVATIVES_MACRO_TREND: StrategyConfig(
                name="Macro Trend AI",
                enabled=False,  # Phase 2
                max_positions=2,
                risk_per_trade_pct=2.0,
                min_trade_size=100.0
            ),
            StrategyType.DERIVATIVES_INDEX_SCALPING: StrategyConfig(
                name="Index Scalping",
                enabled=False,  # Phase 2
                max_positions=3,
                risk_per_trade_pct=1.5,
                min_trade_size=50.0
            )
        }
        logger.info(f"DerivativesEngine initialized with ${capital:.2f} (Phase 2 - not active)")

    def select_strategy(self, market_conditions: Dict) -> StrategyType:
        """Select derivatives strategy (Phase 2)."""
        # Default to macro trend for now
        return StrategyType.DERIVATIVES_MACRO_TREND

    def scan_opportunities(self) -> List[Dict]:
        """Scan derivatives markets (Phase 2)."""
        logger.info("Derivatives scanning not yet implemented (Phase 2)")
        return []

    def execute_trade(self, signal: Dict) -> bool:
        """Execute derivatives trade (Phase 2)."""
        logger.info("Derivatives trading not yet implemented (Phase 2)")
        return False

    def get_available_capital(self) -> float:
        """Get available capital for derivatives."""
        allocated = sum(pos.get('size', 0) for pos in self.active_positions)
        return max(0, self.capital - allocated)


def create_engine(asset_class: str, capital: float, user_tier: str) -> BaseAssetEngine:
    """
    Factory function to create appropriate asset engine.

    Args:
        asset_class: "crypto", "equity", or "derivatives"
        capital: Allocated capital
        user_tier: User's subscription tier

    Returns:
        Appropriate asset engine instance
    """
    asset_class = asset_class.lower()

    if asset_class == "crypto":
        return CryptoEngine(capital, user_tier)
    elif asset_class == "equity":
        return EquityEngine(capital, user_tier)
    elif asset_class == "derivatives":
        return DerivativesEngine(capital, user_tier)
    else:
        raise ValueError(f"Unknown asset class: {asset_class}")
