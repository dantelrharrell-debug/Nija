"""
NIJA Monte Carlo Stress Testing Engine
======================================

Fund-grade robustness testing that simulates real-world execution imperfections:
- Slippage (market impact and adverse selection)
- Spread expansion (volatile markets widen spreads)
- Random latency (network and exchange delays)
- Partial fills (liquidity constraints)
- Execution delays (time between signal and fill)

This provides realistic performance expectations and helps identify
strategy weaknesses before they cost real money.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import copy

logger = logging.getLogger("nija.monte_carlo")


@dataclass
class ExecutionImperfections:
    """Configuration for execution imperfections"""
    # Slippage (as percentage of price)
    slippage_mean: float = 0.001  # 0.1% average slippage
    slippage_std: float = 0.0005  # Standard deviation
    slippage_max: float = 0.005  # 0.5% maximum
    
    # Spread expansion
    base_spread_bps: float = 10.0  # 10 basis points base spread
    spread_expansion_factor: float = 2.0  # Can expand 2x in volatile markets
    spread_volatility_sensitivity: float = 1.5  # How much volatility affects spread
    
    # Latency (in seconds)
    latency_mean: float = 0.2  # 200ms average
    latency_std: float = 0.1  # 100ms std dev
    latency_max: float = 2.0  # 2 second max
    
    # Partial fills
    partial_fill_probability: float = 0.15  # 15% chance of partial fill
    partial_fill_pct_mean: float = 0.70  # Fill 70% on average when partial
    partial_fill_pct_std: float = 0.15  # Standard deviation
    
    # Execution delay (price moves during order execution)
    execution_delay_bars: int = 1  # How many bars between signal and fill
    adverse_selection_factor: float = 0.3  # 30% adverse price movement


@dataclass
class TradeSimulation:
    """Single trade simulation result"""
    trade_id: int
    symbol: str
    direction: str  # 'long' or 'short'
    
    # Ideal execution
    ideal_entry_price: float
    ideal_exit_price: float
    ideal_quantity: float
    ideal_pnl: float
    
    # Actual execution (with imperfections)
    actual_entry_price: float
    actual_exit_price: float
    actual_quantity: float
    actual_pnl: float
    
    # Imperfections applied
    entry_slippage: float
    exit_slippage: float
    entry_spread: float
    exit_spread: float
    entry_latency: float
    exit_latency: float
    partial_fill: bool
    fill_percentage: float
    
    # Performance degradation
    pnl_degradation: float  # actual_pnl - ideal_pnl
    pnl_degradation_pct: float  # degradation as % of ideal


@dataclass
class MonteCarloResult:
    """Result of Monte Carlo simulation"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    num_simulations: int = 1000
    num_trades: int = 0
    
    # Ideal vs Actual performance
    ideal_total_pnl: float = 0.0
    actual_total_pnl_mean: float = 0.0
    actual_total_pnl_std: float = 0.0
    actual_total_pnl_min: float = 0.0
    actual_total_pnl_max: float = 0.0
    
    # Percentile analysis
    pnl_percentiles: Dict[int, float] = field(default_factory=dict)  # 5th, 25th, 50th, 75th, 95th
    
    # Degradation analysis
    mean_degradation: float = 0.0
    mean_degradation_pct: float = 0.0
    worst_case_degradation_pct: float = 0.0
    
    # Win rate analysis
    ideal_win_rate: float = 0.0
    actual_win_rate_mean: float = 0.0
    actual_win_rate_std: float = 0.0
    
    # Trade-level statistics
    avg_slippage_pct: float = 0.0
    avg_spread_cost_pct: float = 0.0
    partial_fill_rate: float = 0.0
    
    # All simulation results
    simulation_results: List[Dict] = field(default_factory=list)
    
    # Summary
    summary: str = ""


class MonteCarloStressTestEngine:
    """
    Monte Carlo stress testing engine for trading strategies
    
    Simulates thousands of scenarios with realistic execution imperfections
    to provide robust performance expectations.
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Monte Carlo Stress Test Engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Default execution imperfections
        imperfections_config = self.config.get('imperfections', {})
        self.imperfections = ExecutionImperfections(**imperfections_config)
        
        # Simulation settings
        self.num_simulations = self.config.get('num_simulations', 1000)
        self.random_seed = self.config.get('random_seed', None)
        
        # Set random seed for reproducibility if specified
        if self.random_seed is not None:
            np.random.seed(self.random_seed)
        
        logger.info("=" * 70)
        logger.info("🎲 Monte Carlo Stress Test Engine Initialized")
        logger.info("=" * 70)
        logger.info(f"Simulations per test: {self.num_simulations}")
        logger.info("")
        logger.info("Execution Imperfections:")
        logger.info(f"  Slippage: {self.imperfections.slippage_mean*100:.3f}% ± {self.imperfections.slippage_std*100:.3f}%")
        logger.info(f"  Base Spread: {self.imperfections.base_spread_bps} bps")
        logger.info(f"  Latency: {self.imperfections.latency_mean*1000:.0f}ms ± {self.imperfections.latency_std*1000:.0f}ms")
        logger.info(f"  Partial Fill Probability: {self.imperfections.partial_fill_probability*100:.0f}%")
        logger.info("=" * 70)
    
    def simulate_slippage(self, price: float, is_buy: bool) -> float:
        """
        Simulate price slippage
        
        Args:
            price: Ideal execution price
            is_buy: True if buying, False if selling
            
        Returns:
            Slippage amount (positive = adverse movement)
        """
        # Generate slippage percentage
        slippage_pct = np.random.normal(
            self.imperfections.slippage_mean,
            self.imperfections.slippage_std
        )
        
        # Clip to maximum
        slippage_pct = np.clip(slippage_pct, 0, self.imperfections.slippage_max)
        
        # Slippage is always adverse
        # Buy: pay higher price (positive slippage)
        # Sell: receive lower price (positive slippage cost)
        slippage = price * slippage_pct
        
        return slippage
    
    def simulate_spread(self, price: float, volatility: float = 0.02) -> float:
        """
        Simulate bid-ask spread expansion
        
        Args:
            price: Current price
            volatility: Current volatility (affects spread width)
            
        Returns:
            Half-spread cost (what you pay to cross the spread)
        """
        # Base spread in basis points
        base_spread_pct = self.imperfections.base_spread_bps / 10000
        
        # Expand spread based on volatility
        volatility_factor = 1.0 + (volatility / 0.02) * self.imperfections.spread_volatility_sensitivity
        expansion_factor = min(self.imperfections.spread_expansion_factor, volatility_factor)
        
        # Calculate effective spread
        effective_spread_pct = base_spread_pct * expansion_factor
        
        # Half spread (cost to cross)
        half_spread = price * effective_spread_pct / 2
        
        return half_spread
    
    def simulate_latency(self) -> float:
        """
        Simulate execution latency
        
        Returns:
            Latency in seconds
        """
        latency = np.random.normal(
            self.imperfections.latency_mean,
            self.imperfections.latency_std
        )
        
        # Clip to reasonable range
        latency = np.clip(latency, 0.01, self.imperfections.latency_max)
        
        return latency
    
    def simulate_partial_fill(self, quantity: float) -> Tuple[bool, float, float]:
        """
        Simulate partial fill
        
        Args:
            quantity: Intended order quantity
            
        Returns:
            Tuple of (is_partial, filled_quantity, fill_percentage)
        """
        # Random chance of partial fill
        if np.random.random() < self.imperfections.partial_fill_probability:
            # Partial fill occurred
            fill_pct = np.random.normal(
                self.imperfections.partial_fill_pct_mean,
                self.imperfections.partial_fill_pct_std
            )
            fill_pct = np.clip(fill_pct, 0.3, 1.0)  # Fill at least 30%, at most 100%
            
            filled_quantity = quantity * fill_pct
            return True, filled_quantity, fill_pct
        else:
            # Full fill
            return False, quantity, 1.0
    
    def simulate_execution_delay(
        self,
        signal_price: float,
        price_series: pd.Series,
        signal_index: int,
        is_buy: bool
    ) -> float:
        """
        Simulate price movement during execution delay
        
        Args:
            signal_price: Price when signal was generated
            price_series: Full price series
            signal_index: Index where signal occurred
            is_buy: True if buy order
            
        Returns:
            Actual execution price after delay
        """
        # Check if we have enough data for delay
        if signal_index + self.imperfections.execution_delay_bars >= len(price_series):
            # Use signal price if not enough data
            return signal_price
        
        # Get price after delay
        delayed_price = price_series.iloc[signal_index + self.imperfections.execution_delay_bars]
        
        # Apply adverse selection (price moves against you during delay)
        price_change = delayed_price - signal_price
        
        if is_buy:
            # When buying, adverse movement is upward
            if price_change > 0:
                adverse_movement = price_change * self.imperfections.adverse_selection_factor
            else:
                adverse_movement = 0  # No adverse selection if price fell
        else:
            # When selling, adverse movement is downward
            if price_change < 0:
                adverse_movement = abs(price_change) * self.imperfections.adverse_selection_factor
            else:
                adverse_movement = 0
        
        # Apply adverse selection
        if is_buy:
            execution_price = signal_price + adverse_movement
        else:
            execution_price = signal_price - adverse_movement
        
        return execution_price
    
    def simulate_trade(
        self,
        trade_id: int,
        symbol: str,
        direction: str,
        ideal_entry_price: float,
        ideal_exit_price: float,
        ideal_quantity: float,
        entry_volatility: float = 0.02,
        exit_volatility: float = 0.02,
        price_series: Optional[pd.Series] = None,
        entry_index: int = 0,
        exit_index: int = 0
    ) -> TradeSimulation:
        """
        Simulate a single trade with execution imperfections
        
        Args:
            trade_id: Unique trade identifier
            symbol: Trading symbol
            direction: 'long' or 'short'
            ideal_entry_price: Perfect entry price
            ideal_exit_price: Perfect exit price
            ideal_quantity: Intended position size
            entry_volatility: Market volatility at entry
            exit_volatility: Market volatility at exit
            price_series: Optional price series for execution delay simulation
            entry_index: Index in price_series for entry
            exit_index: Index in price_series for exit
            
        Returns:
            TradeSimulation with results
        """
        is_long = direction.lower() == 'long'
        
        # ENTRY EXECUTION
        # 1. Slippage
        entry_slippage = self.simulate_slippage(ideal_entry_price, is_buy=is_long)
        
        # 2. Spread
        entry_spread = self.simulate_spread(ideal_entry_price, entry_volatility)
        
        # 3. Latency (informational only, doesn't affect price in this simple model)
        entry_latency = self.simulate_latency()
        
        # 4. Execution delay (price movement)
        if price_series is not None:
            entry_price_with_delay = self.simulate_execution_delay(
                ideal_entry_price, price_series, entry_index, is_buy=is_long
            )
        else:
            entry_price_with_delay = ideal_entry_price
        
        # 5. Partial fill
        is_partial, filled_quantity, fill_pct = self.simulate_partial_fill(ideal_quantity)
        
        # Calculate actual entry price (worse than ideal)
        if is_long:
            actual_entry_price = entry_price_with_delay + entry_slippage + entry_spread
        else:
            actual_entry_price = entry_price_with_delay - entry_slippage - entry_spread
        
        # EXIT EXECUTION
        # 1. Slippage
        exit_slippage = self.simulate_slippage(ideal_exit_price, is_buy=not is_long)
        
        # 2. Spread
        exit_spread = self.simulate_spread(ideal_exit_price, exit_volatility)
        
        # 3. Latency
        exit_latency = self.simulate_latency()
        
        # 4. Execution delay
        if price_series is not None:
            exit_price_with_delay = self.simulate_execution_delay(
                ideal_exit_price, price_series, exit_index, is_buy=not is_long
            )
        else:
            exit_price_with_delay = ideal_exit_price
        
        # Calculate actual exit price (worse than ideal)
        if is_long:
            actual_exit_price = exit_price_with_delay - exit_slippage - exit_spread
        else:
            actual_exit_price = exit_price_with_delay + exit_slippage + exit_spread
        
        # Calculate P&L
        if is_long:
            ideal_pnl = (ideal_exit_price - ideal_entry_price) * ideal_quantity
            actual_pnl = (actual_exit_price - actual_entry_price) * filled_quantity
        else:
            ideal_pnl = (ideal_entry_price - ideal_exit_price) * ideal_quantity
            actual_pnl = (actual_entry_price - actual_exit_price) * filled_quantity
        
        # Calculate degradation
        pnl_degradation = actual_pnl - ideal_pnl
        pnl_degradation_pct = (pnl_degradation / abs(ideal_pnl) * 100) if ideal_pnl != 0 else 0
        
        return TradeSimulation(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            ideal_entry_price=ideal_entry_price,
            ideal_exit_price=ideal_exit_price,
            ideal_quantity=ideal_quantity,
            ideal_pnl=ideal_pnl,
            actual_entry_price=actual_entry_price,
            actual_exit_price=actual_exit_price,
            actual_quantity=filled_quantity,
            actual_pnl=actual_pnl,
            entry_slippage=entry_slippage,
            exit_slippage=exit_slippage,
            entry_spread=entry_spread,
            exit_spread=exit_spread,
            entry_latency=entry_latency,
            exit_latency=exit_latency,
            partial_fill=is_partial,
            fill_percentage=fill_pct,
            pnl_degradation=pnl_degradation,
            pnl_degradation_pct=pnl_degradation_pct
        )
    
    def run_monte_carlo(
        self,
        trades: List[Dict],
        price_data: Optional[Dict[str, pd.Series]] = None
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation on a list of trades
        
        Args:
            trades: List of trade dictionaries with:
                - symbol, direction, entry_price, exit_price, quantity
                - Optional: entry_volatility, exit_volatility, entry_index, exit_index
            price_data: Optional dictionary of symbol -> price series for execution delay
            
        Returns:
            MonteCarloResult with statistical analysis
        """
        logger.info("=" * 70)
        logger.info(f"🎲 Running Monte Carlo Simulation ({self.num_simulations} runs)")
        logger.info("=" * 70)
        logger.info(f"Number of trades to simulate: {len(trades)}")
        
        # Calculate ideal performance (no imperfections)
        ideal_total_pnl = 0.0
        ideal_winners = 0
        
        for trade in trades:
            direction = trade['direction']
            entry = trade['entry_price']
            exit = trade['exit_price']
            quantity = trade['quantity']
            
            if direction.lower() == 'long':
                pnl = (exit - entry) * quantity
            else:
                pnl = (entry - exit) * quantity
            
            ideal_total_pnl += pnl
            if pnl > 0:
                ideal_winners += 1
        
        ideal_win_rate = ideal_winners / len(trades) if trades else 0
        
        # Run simulations
        simulation_results = []
        
        for sim_num in range(self.num_simulations):
            sim_total_pnl = 0.0
            sim_winners = 0
            sim_slippage_total = 0.0
            sim_spread_total = 0.0
            sim_partial_fills = 0
            
            for i, trade in enumerate(trades):
                symbol = trade['symbol']
                direction = trade['direction']
                entry = trade['entry_price']
                exit = trade['exit_price']
                quantity = trade['quantity']
                entry_vol = trade.get('entry_volatility', 0.02)
                exit_vol = trade.get('exit_volatility', 0.02)
                
                # Get price series if available
                price_series = price_data.get(symbol) if price_data else None
                entry_idx = trade.get('entry_index', 0)
                exit_idx = trade.get('exit_index', 0)
                
                # Simulate trade
                sim_trade = self.simulate_trade(
                    trade_id=i,
                    symbol=symbol,
                    direction=direction,
                    ideal_entry_price=entry,
                    ideal_exit_price=exit,
                    ideal_quantity=quantity,
                    entry_volatility=entry_vol,
                    exit_volatility=exit_vol,
                    price_series=price_series,
                    entry_index=entry_idx,
                    exit_index=exit_idx
                )
                
                sim_total_pnl += sim_trade.actual_pnl
                if sim_trade.actual_pnl > 0:
                    sim_winners += 1
                
                # Track costs
                sim_slippage_total += sim_trade.entry_slippage + sim_trade.exit_slippage
                sim_spread_total += sim_trade.entry_spread + sim_trade.exit_spread
                if sim_trade.partial_fill:
                    sim_partial_fills += 1
            
            sim_win_rate = sim_winners / len(trades) if trades else 0
            
            simulation_results.append({
                'simulation_num': sim_num,
                'total_pnl': sim_total_pnl,
                'win_rate': sim_win_rate,
                'slippage_cost': sim_slippage_total,
                'spread_cost': sim_spread_total,
                'partial_fills': sim_partial_fills,
            })
        
        # Analyze results
        pnl_values = [r['total_pnl'] for r in simulation_results]
        win_rates = [r['win_rate'] for r in simulation_results]
        
        actual_pnl_mean = np.mean(pnl_values)
        actual_pnl_std = np.std(pnl_values)
        actual_pnl_min = np.min(pnl_values)
        actual_pnl_max = np.max(pnl_values)
        
        # Calculate percentiles
        percentiles = {
            5: np.percentile(pnl_values, 5),
            25: np.percentile(pnl_values, 25),
            50: np.percentile(pnl_values, 50),
            75: np.percentile(pnl_values, 75),
            95: np.percentile(pnl_values, 95),
        }
        
        # Degradation analysis
        mean_degradation = ideal_total_pnl - actual_pnl_mean
        mean_degradation_pct = (mean_degradation / abs(ideal_total_pnl) * 100) if ideal_total_pnl != 0 else 0
        worst_case_degradation_pct = ((ideal_total_pnl - actual_pnl_min) / abs(ideal_total_pnl) * 100) if ideal_total_pnl != 0 else 0
        
        # Win rate analysis
        actual_win_rate_mean = np.mean(win_rates)
        actual_win_rate_std = np.std(win_rates)
        
        # Average costs
        avg_slippage = np.mean([r['slippage_cost'] for r in simulation_results])
        avg_spread = np.mean([r['spread_cost'] for r in simulation_results])
        avg_slippage_pct = (avg_slippage / abs(ideal_total_pnl) * 100) if ideal_total_pnl != 0 else 0
        avg_spread_pct = (avg_spread / abs(ideal_total_pnl) * 100) if ideal_total_pnl != 0 else 0
        partial_fill_rate = np.mean([r['partial_fills'] for r in simulation_results]) / len(trades) if trades else 0
        
        # Generate summary
        summary = self._generate_summary(
            ideal_total_pnl, actual_pnl_mean, actual_pnl_std,
            percentiles, mean_degradation_pct, worst_case_degradation_pct,
            ideal_win_rate, actual_win_rate_mean,
            avg_slippage_pct, avg_spread_pct, partial_fill_rate
        )
        
        result = MonteCarloResult(
            num_simulations=self.num_simulations,
            num_trades=len(trades),
            ideal_total_pnl=ideal_total_pnl,
            actual_total_pnl_mean=actual_pnl_mean,
            actual_total_pnl_std=actual_pnl_std,
            actual_total_pnl_min=actual_pnl_min,
            actual_total_pnl_max=actual_pnl_max,
            pnl_percentiles=percentiles,
            mean_degradation=mean_degradation,
            mean_degradation_pct=mean_degradation_pct,
            worst_case_degradation_pct=worst_case_degradation_pct,
            ideal_win_rate=ideal_win_rate,
            actual_win_rate_mean=actual_win_rate_mean,
            actual_win_rate_std=actual_win_rate_std,
            avg_slippage_pct=avg_slippage_pct,
            avg_spread_cost_pct=avg_spread_pct,
            partial_fill_rate=partial_fill_rate,
            simulation_results=simulation_results,
            summary=summary
        )
        
        logger.info(summary)
        logger.info("=" * 70)
        
        return result
    
    def _generate_summary(
        self,
        ideal_pnl: float,
        actual_pnl_mean: float,
        actual_pnl_std: float,
        percentiles: Dict,
        mean_degradation_pct: float,
        worst_degradation_pct: float,
        ideal_win_rate: float,
        actual_win_rate: float,
        avg_slippage_pct: float,
        avg_spread_pct: float,
        partial_fill_rate: float
    ) -> str:
        """Generate summary"""
        lines = [
            "\n🎲 MONTE CARLO STRESS TEST RESULTS",
            "=" * 70,
            "",
            "📊 Performance Comparison:",
            f"  Ideal P&L: ${ideal_pnl:,.2f}",
            f"  Actual P&L (mean): ${actual_pnl_mean:,.2f} ± ${actual_pnl_std:,.2f}",
            f"  Performance Degradation: {mean_degradation_pct:.2f}%",
            "",
            "📈 P&L Percentiles:",
            f"  5th percentile (worst): ${percentiles[5]:,.2f}",
            f"  25th percentile: ${percentiles[25]:,.2f}",
            f"  50th percentile (median): ${percentiles[50]:,.2f}",
            f"  75th percentile: ${percentiles[75]:,.2f}",
            f"  95th percentile (best): ${percentiles[95]:,.2f}",
            "",
            "🎯 Win Rate:",
            f"  Ideal: {ideal_win_rate*100:.1f}%",
            f"  Actual (mean): {actual_win_rate*100:.1f}%",
            "",
            "💸 Execution Costs:",
            f"  Slippage: {avg_slippage_pct:.3f}% of P&L",
            f"  Spread: {avg_spread_pct:.3f}% of P&L",
            f"  Partial Fill Rate: {partial_fill_rate*100:.1f}%",
            "",
            "⚠️  Risk Analysis:",
            f"  Mean Degradation: {mean_degradation_pct:.2f}%",
            f"  Worst Case Degradation: {worst_degradation_pct:.2f}%",
        ]
        
        return "\n".join(lines)


def create_monte_carlo_engine(config: Dict = None) -> MonteCarloStressTestEngine:
    """
    Factory function to create MonteCarloStressTestEngine
    
    Args:
        config: Optional configuration
        
    Returns:
        MonteCarloStressTestEngine instance
    """
    return MonteCarloStressTestEngine(config)


# Example usage
if __name__ == "__main__":
    import logging
    
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create engine
    engine = create_monte_carlo_engine({
        'num_simulations': 1000,
        'imperfections': {
            'slippage_mean': 0.001,  # 0.1%
            'partial_fill_probability': 0.15,  # 15% chance
        }
    })
    
    # Mock trades
    trades = [
        {
            'symbol': 'BTC-USD',
            'direction': 'long',
            'entry_price': 40000,
            'exit_price': 41000,
            'quantity': 0.5,
            'entry_volatility': 0.02,
            'exit_volatility': 0.025,
        },
        {
            'symbol': 'ETH-USD',
            'direction': 'long',
            'entry_price': 2000,
            'exit_price': 2050,
            'quantity': 10,
            'entry_volatility': 0.02,
            'exit_volatility': 0.02,
        },
        {
            'symbol': 'SOL-USD',
            'direction': 'short',
            'entry_price': 100,
            'exit_price': 98,
            'quantity': 100,
            'entry_volatility': 0.03,
            'exit_volatility': 0.025,
        },
    ]
    
    # Run simulation
    result = engine.run_monte_carlo(trades)
    
    print(result.summary)
    
    print("\nKey Insights:")
    print(f"  Expected degradation: {result.mean_degradation_pct:.2f}%")
    print(f"  5th percentile P&L: ${result.pnl_percentiles[5]:,.2f}")
    print(f"  95th percentile P&L: ${result.pnl_percentiles[95]:,.2f}")
