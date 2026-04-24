"""
Meta-AI Evolution Engine Integration Example
=============================================

Demonstrates how to integrate the Meta-AI Evolution Engine
with existing NIJA trading strategies.

Author: NIJA Trading Systems
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime
from bot.meta_ai import MetaAIEvolutionEngine
from bot.meta_ai.reinforcement_learning import MarketState


class MetaAITradingBot:
    """
    Example trading bot that uses Meta-AI Evolution Engine
    """

    def __init__(self):
        """Initialize bot with Meta-AI engine"""
        print("🚀 Initializing Meta-AI Trading Bot...")

        # Initialize Meta-AI Evolution Engine
        self.meta_ai = MetaAIEvolutionEngine(config={
            'enabled': True,
            'mode': 'adaptive',  # Use all features
            'evaluation_frequency': 24,  # Evolve every 24 hours
        })

        # Initialize engine components
        self.meta_ai.initialize()

        print(f"✅ Meta-AI Engine initialized in '{self.meta_ai.mode}' mode")
        print(f"   Population: {len(self.meta_ai.genetic_engine.population)} strategies")
        print(f"   Swarm size: {len(self.meta_ai.strategy_swarm.strategies)} active strategies")

    def get_market_state(self, market_data: dict) -> MarketState:
        """
        Convert market data to MarketState for RL

        Args:
            market_data: Dict with market metrics

        Returns:
            MarketState instance
        """
        # Extract market features
        volatility = market_data.get('volatility', 0.5)  # 0-1
        trend_strength = market_data.get('adx', 25) / 50  # Normalize ADX to 0-1
        volume_ratio = market_data.get('volume_ratio', 1.0)
        volume_regime = min(volume_ratio / 2.0, 1.0)  # Normalize to 0-1

        # Calculate momentum from RSI or price change
        rsi = market_data.get('rsi', 50)
        momentum = (rsi - 50) / 50  # -1 to 1

        # Time features
        now = datetime.utcnow()
        time_of_day = now.hour
        day_of_week = now.weekday()

        return MarketState(
            volatility=volatility,
            trend_strength=trend_strength,
            volume_regime=volume_regime,
            momentum=momentum,
            time_of_day=time_of_day,
            day_of_week=day_of_week,
        )

    def select_strategy(self, market_data: dict) -> dict:
        """
        Select best strategy for current market conditions

        Args:
            market_data: Current market data

        Returns:
            Dict with strategy ID and parameters
        """
        # Convert to market state
        market_state = self.get_market_state(market_data)

        # Use Meta-AI to select strategy
        strategy_id = self.meta_ai.select_strategy(market_state)

        if not strategy_id:
            print("⚠️  No strategy selected")
            return None

        # Get strategy parameters
        strategy_genome = None
        if self.meta_ai.genetic_engine:
            for genome in self.meta_ai.genetic_engine.population:
                if genome.id == strategy_id:
                    strategy_genome = genome
                    break

        if not strategy_genome:
            print(f"⚠️  Strategy {strategy_id} not found")
            return None

        # Get capital allocation
        allocation = self.meta_ai.get_strategy_allocation(strategy_id)

        return {
            'strategy_id': strategy_id,
            'parameters': strategy_genome.parameters,
            'allocation': allocation,
            'fitness': strategy_genome.fitness,
        }

    def execute_trade(self, strategy_info: dict, market_data: dict):
        """
        Execute trade using selected strategy

        Args:
            strategy_info: Strategy information from select_strategy()
            market_data: Current market data
        """
        if not strategy_info:
            return

        strategy_id = strategy_info['strategy_id']
        parameters = strategy_info['parameters']
        allocation = strategy_info['allocation']

        print(f"\n📊 Using strategy: {strategy_id[:32]}...")
        print(f"   Allocation: {allocation*100:.1f}%")
        print(f"   Fitness: {strategy_info['fitness']:.4f}")
        print(f"   RSI Period: {parameters.get('rsi_period', 14):.0f}")
        print(f"   ADX Threshold: {parameters.get('adx_threshold', 25):.0f}")
        print(f"   Position Size: {parameters.get('position_size_min', 0.02):.2%}")

        # Here you would:
        # 1. Apply strategy parameters to your trading logic
        # 2. Calculate position size based on allocation
        # 3. Execute the trade

        # Simulate trade for example
        trade_return = 0.025  # 2.5% profit (example)

        print(f"   Trade executed: +{trade_return:.2%}")

        return trade_return

    def update_performance(
        self,
        strategy_id: str,
        trade_return: float,
        market_state: MarketState,
        next_market_state: MarketState
    ):
        """
        Update strategy performance after trade

        Args:
            strategy_id: Strategy that was used
            trade_return: Trade return (e.g., 0.025 for 2.5%)
            market_state: Market state when trade was opened
            next_market_state: Market state after trade
        """
        # Update swarm performance
        self.meta_ai.update_swarm_performance(
            strategy_id=strategy_id,
            trade_return=trade_return,
            metrics={
                'sharpe_ratio': 1.8,  # Would calculate from trade history
                'win_rate': 0.60,
                'profit_factor': 2.1,
            }
        )

        # Update RL experience
        reward = trade_return * 100  # Scale reward
        self.meta_ai.update_rl_experience(
            state=market_state,
            strategy_id=strategy_id,
            reward=reward,
            next_state=next_market_state,
        )

        print(f"✅ Updated performance for {strategy_id[:32]}...")

    def run_evolution_cycle(self):
        """
        Run evolution cycle if needed
        """
        if not self.meta_ai.should_evaluate():
            return

        print("\n🔄 Running evolution cycle...")

        # Evaluate population (would use real backtest results)
        backtest_results = {}
        for genome in self.meta_ai.genetic_engine.population[:5]:  # Example: top 5
            backtest_results[genome.id] = {
                'sharpe_ratio': 1.5 + (genome.fitness * 0.5),
                'profit_factor': 2.0,
                'win_rate': 0.58,
                'max_drawdown': 0.12,
                'expectancy': 0.35,
                'total_trades': 50,
            }

        self.meta_ai.evaluate_population(backtest_results)

        # Evolve strategies
        new_strategies = self.meta_ai.evolve_strategies()

        print(f"✅ Evolution complete: {len(new_strategies)} new strategies")

        # Show stats
        stats = self.meta_ai.get_engine_stats()
        print(f"\n📊 Engine Stats:")
        print(f"   Evolution cycle: {stats['evolution_cycle']}")
        if 'genetic' in stats:
            print(f"   Best fitness: {stats['genetic']['best_fitness']:.4f}")
            print(f"   Diversity: {stats['genetic']['diversity']:.4f}")
        if 'swarm' in stats:
            print(f"   Swarm diversity: {stats['swarm']['diversity']:.2f}")
        if 'alpha_discovery' in stats:
            print(f"   Alphas discovered: {stats['alpha_discovery']['total_discovered']}")


def main():
    """Main example execution"""
    print("=" * 70)
    print("NIJA Meta-AI Trading Bot - Integration Example")
    print("=" * 70)

    # Initialize bot
    bot = MetaAITradingBot()

    # Simulate trading loop
    print("\n📈 Simulating trading session...")

    for i in range(5):
        print(f"\n--- Trade {i+1} ---")

        # Get market data (simulated)
        market_data = {
            'volatility': 0.6,
            'adx': 32.5,
            'volume_ratio': 1.4,
            'rsi': 58,
        }

        # Select strategy
        strategy_info = bot.select_strategy(market_data)

        # Execute trade
        if strategy_info:
            trade_return = bot.execute_trade(strategy_info, market_data)

            # Update performance
            market_state = bot.get_market_state(market_data)
            next_market_state = bot.get_market_state(market_data)  # Would be actual next state

            bot.update_performance(
                strategy_info['strategy_id'],
                trade_return,
                market_state,
                next_market_state
            )

    # Run evolution
    print("\n" + "=" * 70)
    bot.run_evolution_cycle()

    print("\n" + "=" * 70)
    print("✅ Example complete!")
    print("=" * 70)


if __name__ == '__main__':
    main()
