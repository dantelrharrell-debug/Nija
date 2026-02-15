"""
NIJA Market Crash Simulator
============================

Simulates various types of market crash scenarios to stress-test trading systems
and state machines. Supports multiple crash patterns:

1. Flash Crash - Sudden, rapid price decline followed by quick recovery
2. Gradual Decline - Slow, sustained downward trend
3. Sector Crash - Specific sector experiences severe decline
4. Black Swan - Extreme volatility with large price swings
5. Contagion - Cascading failures across multiple assets

This module is used for:
- Stress testing trading state machines
- Validating risk management systems
- Testing sector exposure limits
- Portfolio resilience analysis

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger("nija.crash_simulator")


class CrashType(Enum):
    """Types of market crash scenarios"""
    FLASH_CRASH = "flash_crash"
    GRADUAL_DECLINE = "gradual_decline"
    SECTOR_CRASH = "sector_crash"
    BLACK_SWAN = "black_swan"
    CONTAGION = "contagion"
    LIQUIDITY_CRISIS = "liquidity_crisis"


@dataclass
class CrashScenario:
    """Configuration for a market crash scenario"""
    crash_type: CrashType
    name: str
    description: str
    
    # Timing parameters
    duration_minutes: int = 60  # How long the crash lasts
    recovery_minutes: int = 120  # How long recovery takes
    
    # Magnitude parameters
    max_decline_pct: float = 0.30  # Maximum price decline (30%)
    volatility_multiplier: float = 5.0  # Increase in volatility
    
    # Sector-specific (for sector crashes)
    affected_sectors: List[str] = field(default_factory=list)
    sector_decline_pct: float = 0.50  # 50% decline for affected sectors
    
    # Contagion parameters
    contagion_spread_rate: float = 0.5  # How quickly crash spreads
    correlation_increase: float = 0.3  # Increase in asset correlation
    
    # Liquidity parameters
    liquidity_reduction_pct: float = 0.70  # 70% reduction in liquidity
    spread_expansion_multiplier: float = 10.0  # Spreads widen 10x
    
    # Market microstructure
    price_impact_multiplier: float = 5.0  # Increased price impact
    partial_fill_probability: float = 0.60  # 60% chance of partial fill


@dataclass
class CrashSimulationResult:
    """Results from a crash simulation"""
    scenario: CrashScenario
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Price data
    price_data: Dict[str, pd.DataFrame] = field(default_factory=dict)
    
    # Market metrics
    max_drawdown: float = 0.0
    max_volatility: float = 0.0
    correlation_matrix: Optional[pd.DataFrame] = None
    
    # Liquidity metrics
    avg_spread_expansion: float = 0.0
    liquidity_score: float = 1.0  # 1.0 = normal, 0.0 = no liquidity
    
    # Summary statistics
    assets_affected: int = 0
    sectors_affected: int = 0
    crash_duration_actual: int = 0
    recovery_duration_actual: int = 0
    
    summary: str = ""


class MarketCrashSimulator:
    """
    Simulates various market crash scenarios for stress testing.
    
    This class generates realistic market crash data that can be used to:
    - Test trading state machine resilience
    - Validate risk management systems
    - Assess portfolio protection mechanisms
    - Test sector exposure limits
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize market crash simulator
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.random_seed = self.config.get('random_seed', None)
        
        if self.random_seed is not None:
            np.random.seed(self.random_seed)
        
        logger.info("=" * 70)
        logger.info("💥 Market Crash Simulator Initialized")
        logger.info("=" * 70)
    
    def create_flash_crash_scenario(
        self,
        max_decline_pct: float = 0.30,
        duration_minutes: int = 15,
        recovery_minutes: int = 60
    ) -> CrashScenario:
        """
        Create a flash crash scenario configuration
        
        Args:
            max_decline_pct: Maximum price decline (default: 30%)
            duration_minutes: Duration of crash (default: 15 minutes)
            recovery_minutes: Recovery duration (default: 60 minutes)
            
        Returns:
            CrashScenario configuration
        """
        return CrashScenario(
            crash_type=CrashType.FLASH_CRASH,
            name="Flash Crash",
            description="Sudden, rapid price decline followed by quick recovery",
            duration_minutes=duration_minutes,
            recovery_minutes=recovery_minutes,
            max_decline_pct=max_decline_pct,
            volatility_multiplier=8.0,
            liquidity_reduction_pct=0.80,
            spread_expansion_multiplier=15.0,
            partial_fill_probability=0.70
        )
    
    def create_gradual_decline_scenario(
        self,
        max_decline_pct: float = 0.40,
        duration_minutes: int = 240
    ) -> CrashScenario:
        """
        Create a gradual decline scenario
        
        Args:
            max_decline_pct: Total decline (default: 40%)
            duration_minutes: Duration (default: 240 minutes / 4 hours)
            
        Returns:
            CrashScenario configuration
        """
        return CrashScenario(
            crash_type=CrashType.GRADUAL_DECLINE,
            name="Gradual Decline",
            description="Slow, sustained downward trend",
            duration_minutes=duration_minutes,
            recovery_minutes=duration_minutes * 2,
            max_decline_pct=max_decline_pct,
            volatility_multiplier=2.5,
            liquidity_reduction_pct=0.30,
            spread_expansion_multiplier=2.0,
            partial_fill_probability=0.20
        )
    
    def create_sector_crash_scenario(
        self,
        affected_sectors: List[str],
        sector_decline_pct: float = 0.50,
        duration_minutes: int = 120
    ) -> CrashScenario:
        """
        Create a sector-specific crash scenario
        
        Args:
            affected_sectors: List of sector names to crash
            sector_decline_pct: Decline for affected sectors (default: 50%)
            duration_minutes: Duration (default: 120 minutes)
            
        Returns:
            CrashScenario configuration
        """
        return CrashScenario(
            crash_type=CrashType.SECTOR_CRASH,
            name="Sector Crash",
            description=f"Severe decline in {', '.join(affected_sectors)} sectors",
            duration_minutes=duration_minutes,
            recovery_minutes=duration_minutes * 3,
            max_decline_pct=0.15,  # Market-wide decline
            sector_decline_pct=sector_decline_pct,
            affected_sectors=affected_sectors,
            volatility_multiplier=6.0,
            liquidity_reduction_pct=0.60,
            spread_expansion_multiplier=8.0,
            contagion_spread_rate=0.3
        )
    
    def create_black_swan_scenario(
        self,
        max_decline_pct: float = 0.60,
        duration_minutes: int = 180
    ) -> CrashScenario:
        """
        Create a black swan event scenario
        
        Args:
            max_decline_pct: Extreme decline (default: 60%)
            duration_minutes: Duration (default: 180 minutes)
            
        Returns:
            CrashScenario configuration
        """
        return CrashScenario(
            crash_type=CrashType.BLACK_SWAN,
            name="Black Swan Event",
            description="Extreme, unprecedented market event with severe volatility",
            duration_minutes=duration_minutes,
            recovery_minutes=duration_minutes * 4,
            max_decline_pct=max_decline_pct,
            volatility_multiplier=15.0,
            liquidity_reduction_pct=0.90,
            spread_expansion_multiplier=25.0,
            partial_fill_probability=0.85,
            correlation_increase=0.8  # All assets move together
        )
    
    def simulate_crash(
        self,
        scenario: CrashScenario,
        symbols: List[str],
        initial_prices: Dict[str, float],
        sector_map: Optional[Dict[str, str]] = None,
        interval_minutes: int = 1
    ) -> CrashSimulationResult:
        """
        Simulate a market crash scenario
        
        Args:
            scenario: Crash scenario configuration
            symbols: List of trading symbols to simulate
            initial_prices: Dictionary of symbol -> initial price
            sector_map: Optional mapping of symbol -> sector
            interval_minutes: Time interval for price data (default: 1 minute)
            
        Returns:
            CrashSimulationResult with simulated data
        """
        logger.info("=" * 70)
        logger.info(f"💥 Simulating {scenario.name}")
        logger.info("=" * 70)
        logger.info(f"Description: {scenario.description}")
        logger.info(f"Symbols: {len(symbols)}")
        logger.info(f"Duration: {scenario.duration_minutes} minutes")
        logger.info(f"Max Decline: {scenario.max_decline_pct * 100:.1f}%")
        
        # Calculate total simulation periods
        total_minutes = scenario.duration_minutes + scenario.recovery_minutes
        num_periods = total_minutes // interval_minutes
        
        # Generate timestamps
        timestamps = [
            datetime.now() + timedelta(minutes=i * interval_minutes)
            for i in range(num_periods)
        ]
        
        # Initialize price data storage
        price_data = {}
        
        # Simulate each symbol
        for symbol in symbols:
            initial_price = initial_prices.get(symbol, 100.0)
            sector = sector_map.get(symbol, "misc") if sector_map else "misc"
            
            # Determine if this symbol is in an affected sector
            is_affected_sector = (
                scenario.crash_type == CrashType.SECTOR_CRASH
                and sector in scenario.affected_sectors
            )
            
            # Calculate decline for this symbol
            if is_affected_sector:
                decline_pct = scenario.sector_decline_pct
            else:
                decline_pct = scenario.max_decline_pct
            
            # Generate price path
            prices = self._generate_crash_price_path(
                initial_price=initial_price,
                decline_pct=decline_pct,
                duration_periods=scenario.duration_minutes // interval_minutes,
                recovery_periods=scenario.recovery_minutes // interval_minutes,
                volatility_multiplier=scenario.volatility_multiplier,
                crash_type=scenario.crash_type
            )
            
            # Create DataFrame
            df = pd.DataFrame({
                'timestamp': timestamps[:len(prices)],
                'price': prices,
                'symbol': symbol,
                'sector': sector
            })
            
            # Calculate returns and volatility
            df['returns'] = df['price'].pct_change()
            df['volatility'] = df['returns'].rolling(window=5).std()
            
            # Simulate liquidity conditions
            df['spread_bps'] = self._simulate_spread_expansion(
                scenario, df['volatility'].fillna(0.02).values
            )
            
            df['liquidity_score'] = self._simulate_liquidity_reduction(
                scenario, len(prices)
            )
            
            price_data[symbol] = df
        
        # Calculate aggregate metrics
        max_drawdown = self._calculate_max_drawdown(price_data)
        max_volatility = self._calculate_max_volatility(price_data)
        avg_spread_expansion = self._calculate_avg_spread_expansion(price_data)
        avg_liquidity_score = self._calculate_avg_liquidity_score(price_data)
        
        # Count affected assets and sectors
        assets_affected = len(symbols)
        sectors_affected = len(set(sector_map.values())) if sector_map else 0
        
        # Generate summary
        summary = self._generate_crash_summary(
            scenario, max_drawdown, max_volatility,
            avg_spread_expansion, avg_liquidity_score,
            assets_affected, sectors_affected
        )
        
        result = CrashSimulationResult(
            scenario=scenario,
            price_data=price_data,
            max_drawdown=max_drawdown,
            max_volatility=max_volatility,
            avg_spread_expansion=avg_spread_expansion,
            liquidity_score=avg_liquidity_score,
            assets_affected=assets_affected,
            sectors_affected=sectors_affected,
            crash_duration_actual=scenario.duration_minutes,
            recovery_duration_actual=scenario.recovery_minutes,
            summary=summary
        )
        
        logger.info(summary)
        logger.info("=" * 70)
        
        return result
    
    def _generate_crash_price_path(
        self,
        initial_price: float,
        decline_pct: float,
        duration_periods: int,
        recovery_periods: int,
        volatility_multiplier: float,
        crash_type: CrashType
    ) -> np.ndarray:
        """Generate realistic price path for a crash"""
        total_periods = duration_periods + recovery_periods
        
        # Create crash curve
        crash_curve = np.zeros(total_periods)
        
        if crash_type == CrashType.FLASH_CRASH:
            # Sudden drop, quick recovery
            for i in range(total_periods):
                if i < duration_periods:
                    # Exponential decline
                    progress = i / duration_periods
                    crash_curve[i] = -decline_pct * (1 - np.exp(-5 * progress))
                else:
                    # Quick recovery
                    progress = (i - duration_periods) / recovery_periods
                    crash_curve[i] = -decline_pct * (1 - progress) ** 2
        
        elif crash_type == CrashType.GRADUAL_DECLINE:
            # Linear decline, slow recovery
            for i in range(total_periods):
                if i < duration_periods:
                    progress = i / duration_periods
                    crash_curve[i] = -decline_pct * progress
                else:
                    progress = (i - duration_periods) / recovery_periods
                    crash_curve[i] = -decline_pct * (1 - progress ** 0.5)
        
        else:
            # Default: smooth decline and recovery
            for i in range(total_periods):
                if i < duration_periods:
                    progress = i / duration_periods
                    crash_curve[i] = -decline_pct * np.sin(progress * np.pi / 2)
                else:
                    progress = (i - duration_periods) / recovery_periods
                    crash_curve[i] = -decline_pct * np.cos(progress * np.pi / 2)
        
        # Add volatility
        base_volatility = 0.01  # 1% base volatility per period
        volatility = base_volatility * volatility_multiplier
        
        noise = np.random.normal(0, volatility, total_periods)
        
        # Apply crash curve and noise
        prices = np.zeros(total_periods)
        prices[0] = initial_price
        
        for i in range(1, total_periods):
            # Base price from crash curve
            trend_price = initial_price * (1 + crash_curve[i])
            
            # Add volatility
            price_change = prices[i-1] * (crash_curve[i] - crash_curve[i-1] + noise[i])
            prices[i] = prices[i-1] + price_change
            
            # Ensure prices don't go negative
            prices[i] = max(prices[i], initial_price * 0.01)
        
        return prices
    
    def _simulate_spread_expansion(
        self,
        scenario: CrashScenario,
        volatility: np.ndarray
    ) -> np.ndarray:
        """Simulate spread expansion during crash"""
        base_spread_bps = 10.0  # 10 basis points normal
        
        # Spreads widen during crash
        max_spread = base_spread_bps * scenario.spread_expansion_multiplier
        
        # Spread correlates with volatility
        normalized_vol = np.clip(volatility / 0.10, 0, 1)  # Normalize to 0-1
        
        spreads = base_spread_bps + (max_spread - base_spread_bps) * normalized_vol
        
        return spreads
    
    def _simulate_liquidity_reduction(
        self,
        scenario: CrashScenario,
        num_periods: int
    ) -> np.ndarray:
        """Simulate liquidity reduction during crash"""
        liquidity_scores = np.ones(num_periods)
        
        crash_periods = scenario.duration_minutes
        
        # Reduce liquidity during crash
        for i in range(num_periods):
            if i < crash_periods:
                # Liquidity deteriorates
                progress = i / crash_periods
                reduction = scenario.liquidity_reduction_pct * np.sin(progress * np.pi / 2)
                liquidity_scores[i] = 1.0 - reduction
            else:
                # Liquidity recovers
                progress = (i - crash_periods) / (num_periods - crash_periods)
                reduction = scenario.liquidity_reduction_pct * (1 - progress ** 2)
                liquidity_scores[i] = 1.0 - reduction
        
        return liquidity_scores
    
    def _calculate_max_drawdown(self, price_data: Dict[str, pd.DataFrame]) -> float:
        """Calculate maximum drawdown across all symbols"""
        max_dd = 0.0
        
        for symbol, df in price_data.items():
            prices = df['price'].values
            peak = prices[0]
            
            for price in prices:
                if price > peak:
                    peak = price
                dd = (peak - price) / peak
                if dd > max_dd:
                    max_dd = dd
        
        return max_dd
    
    def _calculate_max_volatility(self, price_data: Dict[str, pd.DataFrame]) -> float:
        """Calculate maximum volatility across all symbols"""
        max_vol = 0.0
        
        for symbol, df in price_data.items():
            vol = df['volatility'].max()
            if vol > max_vol:
                max_vol = vol
        
        return max_vol
    
    def _calculate_avg_spread_expansion(self, price_data: Dict[str, pd.DataFrame]) -> float:
        """Calculate average spread expansion"""
        all_spreads = []
        
        for symbol, df in price_data.items():
            all_spreads.extend(df['spread_bps'].values)
        
        return np.mean(all_spreads) if all_spreads else 0.0
    
    def _calculate_avg_liquidity_score(self, price_data: Dict[str, pd.DataFrame]) -> float:
        """Calculate average liquidity score"""
        all_scores = []
        
        for symbol, df in price_data.items():
            all_scores.extend(df['liquidity_score'].values)
        
        return np.mean(all_scores) if all_scores else 1.0
    
    def _generate_crash_summary(
        self,
        scenario: CrashScenario,
        max_drawdown: float,
        max_volatility: float,
        avg_spread: float,
        avg_liquidity: float,
        assets_affected: int,
        sectors_affected: int
    ) -> str:
        """Generate summary of crash simulation"""
        lines = [
            "\n💥 CRASH SIMULATION RESULTS",
            "=" * 70,
            f"Scenario: {scenario.name}",
            f"Type: {scenario.crash_type.value}",
            "",
            "📉 Market Impact:",
            f"  Maximum Drawdown: {max_drawdown * 100:.2f}%",
            f"  Maximum Volatility: {max_volatility * 100:.2f}%",
            f"  Assets Affected: {assets_affected}",
            f"  Sectors Affected: {sectors_affected}",
            "",
            "💧 Liquidity Conditions:",
            f"  Average Spread: {avg_spread:.1f} bps",
            f"  Average Liquidity Score: {avg_liquidity:.2f}",
            "",
            "⏱️  Timeline:",
            f"  Crash Duration: {scenario.duration_minutes} minutes",
            f"  Recovery Duration: {scenario.recovery_minutes} minutes",
        ]
        
        return "\n".join(lines)


def create_crash_simulator(config: Dict = None) -> MarketCrashSimulator:
    """
    Factory function to create MarketCrashSimulator
    
    Args:
        config: Optional configuration
        
    Returns:
        MarketCrashSimulator instance
    """
    return MarketCrashSimulator(config)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create simulator
    simulator = create_crash_simulator()
    
    # Create flash crash scenario
    scenario = simulator.create_flash_crash_scenario(
        max_decline_pct=0.30,
        duration_minutes=15,
        recovery_minutes=60
    )
    
    # Simulate crash
    symbols = ['BTC-USD', 'ETH-USD', 'SOL-USD']
    initial_prices = {
        'BTC-USD': 40000,
        'ETH-USD': 2000,
        'SOL-USD': 100
    }
    
    result = simulator.simulate_crash(
        scenario=scenario,
        symbols=symbols,
        initial_prices=initial_prices
    )
    
    print(result.summary)
