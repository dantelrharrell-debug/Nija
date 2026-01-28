"""
Meta-AI Evolution Engine
=========================

Main orchestration engine that coordinates:
- Genetic evolution of strategy parameters
- Reinforcement learning strategy selection
- Multi-strategy swarm intelligence
- Self-breeding strategy combinations
- Automated alpha discovery

Author: NIJA Trading Systems
"""

import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging
import json

from .genetic_evolution import GeneticEvolution, StrategyGenome
from .reinforcement_learning import RLStrategySelector, MarketState
from .strategy_swarm import StrategySwarm
from .strategy_breeder import StrategyBreeder
from .alpha_discovery import AlphaDiscovery
from .evolution_config import (
    EVOLUTION_ENGINE_CONFIG,
    GENETIC_CONFIG,
    RL_CONFIG,
    SWARM_CONFIG,
    BREEDER_CONFIG,
    ALPHA_CONFIG,
)

logger = logging.getLogger("nija.meta_ai")


class MetaAIEvolutionEngine:
    """
    Meta-AI Strategy Evolution Engine
    
    God-mode trading system that:
    1. Evolves strategies using genetic algorithms
    2. Selects optimal strategies via reinforcement learning
    3. Manages strategy swarm with dynamic allocation
    4. Breeds new strategies from successful parents
    5. Discovers new alpha signals automatically
    
    This creates a self-improving, adaptive trading system
    that continuously evolves and optimizes itself.
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Meta-AI Evolution Engine
        
        Args:
            config: Configuration dictionary (uses EVOLUTION_ENGINE_CONFIG if None)
        """
        self.config = config or EVOLUTION_ENGINE_CONFIG
        self.enabled = self.config['enabled']
        self.mode = self.config['mode']
        
        # Initialize sub-engines based on mode
        self.genetic_engine = None
        self.rl_selector = None
        self.strategy_swarm = None
        self.strategy_breeder = None
        self.alpha_discovery = None
        
        if self.mode in ['genetic', 'adaptive']:
            self.genetic_engine = GeneticEvolution(GENETIC_CONFIG)
        
        if self.mode in ['rl', 'adaptive']:
            # Will be initialized when we know number of strategies
            self.rl_selector = None
        
        if self.mode in ['swarm', 'adaptive']:
            self.strategy_swarm = StrategySwarm(SWARM_CONFIG)
        
        if self.mode in ['adaptive']:
            self.strategy_breeder = StrategyBreeder(BREEDER_CONFIG)
            self.alpha_discovery = AlphaDiscovery(ALPHA_CONFIG)
        
        # Evolution state
        self.last_evaluation: Optional[datetime] = None
        self.evolution_cycle = 0
        self.deployed_strategies: List[StrategyGenome] = []
        
        logger.info(
            f"🧠 Meta-AI Evolution Engine initialized: "
            f"mode={self.mode}, "
            f"enabled={self.enabled}"
        )
    
    def initialize(self):
        """
        Initialize the evolution engine and create initial population
        """
        if not self.enabled:
            logger.info("⚠️  Meta-AI Evolution Engine is disabled")
            return
        
        logger.info("🚀 Initializing Meta-AI Evolution Engine...")
        
        # Initialize genetic population
        if self.genetic_engine:
            population = self.genetic_engine.initialize_population()
            logger.info(f"🧬 Initialized genetic population: {len(population)} strategies")
            
            # Initialize RL selector with population size
            if self.mode in ['rl', 'adaptive']:
                self.rl_selector = RLStrategySelector(
                    num_strategies=len(population),
                    config=RL_CONFIG
                )
                logger.info(f"🤖 Initialized RL strategy selector")
        
        # Add initial strategies to swarm
        if self.strategy_swarm and self.genetic_engine:
            for i, genome in enumerate(self.genetic_engine.population[:SWARM_CONFIG['num_strategies']]):
                self.strategy_swarm.add_strategy(
                    strategy_id=genome.id,
                    initial_performance={'sharpe_ratio': 0.5}  # Neutral initial performance
                )
        
        logger.info("✅ Meta-AI Evolution Engine initialization complete")
    
    def should_evaluate(self) -> bool:
        """
        Check if it's time for an evolution cycle
        
        Returns:
            True if evaluation should occur
        """
        if self.last_evaluation is None:
            return True
        
        hours_since_eval = (
            datetime.utcnow() - self.last_evaluation
        ).total_seconds() / 3600
        
        return hours_since_eval >= self.config['evaluation_frequency']
    
    def evaluate_population(self, backtest_results: Dict[str, Dict]):
        """
        Evaluate population fitness using backtest results
        
        Args:
            backtest_results: Dict mapping strategy_id to performance metrics
        """
        if not self.genetic_engine:
            return
        
        logger.info(f"📊 Evaluating population fitness...")
        
        for genome in self.genetic_engine.population:
            if genome.id in backtest_results:
                metrics = backtest_results[genome.id]
                fitness = self.genetic_engine.evaluate_fitness(genome, metrics)
                
                logger.debug(
                    f"Strategy {genome.id[:16]}... fitness={fitness:.4f} "
                    f"(Sharpe={metrics.get('sharpe_ratio', 0):.2f})"
                )
    
    def evolve_strategies(self) -> List[StrategyGenome]:
        """
        Execute one evolution cycle
        
        Returns:
            List of new/evolved strategies
        """
        if not self.should_evaluate():
            logger.debug("⏳ Not time for evolution cycle yet")
            return []
        
        logger.info(f"🔄 Starting evolution cycle {self.evolution_cycle + 1}...")
        
        new_strategies = []
        
        # 1. Genetic Evolution
        if self.genetic_engine:
            logger.info("🧬 Running genetic evolution...")
            evolved_population = self.genetic_engine.evolve_generation()
            new_strategies.extend(evolved_population)
            
            best = self.genetic_engine.get_best_strategy()
            if best:
                logger.info(
                    f"🏆 Best strategy: {best.id} "
                    f"(fitness={best.fitness:.4f}, "
                    f"Sharpe={best.sharpe_ratio:.2f})"
                )
        
        # 2. Strategy Breeding
        if self.strategy_breeder and self.genetic_engine:
            logger.info("🌱 Running strategy breeding...")
            offspring = self.strategy_breeder.breed_generation(
                self.genetic_engine.population
            )
            new_strategies.extend(offspring)
            logger.info(f"Created {len(offspring)} offspring strategies")
        
        # 3. Alpha Discovery
        if self.alpha_discovery:
            logger.info("🔬 Running alpha discovery scan...")
            new_alphas = self.alpha_discovery.scan_for_alphas()
            logger.info(f"Discovered {len(new_alphas)} new alpha signals")
        
        # 4. Swarm Rebalancing
        if self.strategy_swarm and self.strategy_swarm.should_rebalance():
            logger.info("⚖️  Rebalancing strategy swarm...")
            self.strategy_swarm._rebalance_allocations()
        
        self.last_evaluation = datetime.utcnow()
        self.evolution_cycle += 1
        
        logger.info(
            f"✅ Evolution cycle {self.evolution_cycle} complete: "
            f"{len(new_strategies)} new strategies"
        )
        
        return new_strategies
    
    def select_strategy(self, market_state: MarketState) -> Optional[str]:
        """
        Select optimal strategy for current market conditions
        
        Args:
            market_state: Current market state
            
        Returns:
            Strategy ID to use, or None
        """
        if not self.rl_selector:
            # No RL selector, use best from genetic evolution
            if self.genetic_engine and self.genetic_engine.best_genome:
                return self.genetic_engine.best_genome.id
            return None
        
        # Use RL to select strategy
        strategy_idx = self.rl_selector.select_strategy(market_state, explore=True)
        
        # Map index to strategy ID
        if self.genetic_engine and strategy_idx < len(self.genetic_engine.population):
            genome = self.genetic_engine.population[strategy_idx]
            return genome.id
        
        return None
    
    def update_rl_experience(
        self,
        state: MarketState,
        strategy_id: str,
        reward: float,
        next_state: MarketState
    ):
        """
        Update RL selector with trading experience
        
        Args:
            state: Market state when strategy was selected
            strategy_id: Strategy that was used
            reward: Reward received (e.g., profit/loss)
            next_state: Resulting market state
        """
        if not self.rl_selector or not self.genetic_engine:
            return
        
        # Find strategy index
        strategy_idx = None
        for i, genome in enumerate(self.genetic_engine.population):
            if genome.id == strategy_id:
                strategy_idx = i
                break
        
        if strategy_idx is not None:
            self.rl_selector.add_experience(
                state=state,
                action=strategy_idx,
                reward=reward,
                next_state=next_state
            )
            
            # Periodic replay training
            if self.rl_selector.total_steps % 10 == 0:
                self.rl_selector.replay_train()
    
    def update_swarm_performance(
        self,
        strategy_id: str,
        trade_return: float,
        metrics: Dict = None
    ):
        """
        Update strategy performance in swarm
        
        Args:
            strategy_id: Strategy ID
            trade_return: Trade return (e.g., 0.05 for 5%)
            metrics: Optional performance metrics
        """
        if not self.strategy_swarm:
            return
        
        self.strategy_swarm.update_strategy_performance(
            strategy_id=strategy_id,
            trade_return=trade_return,
            metrics=metrics
        )
    
    def get_strategy_allocation(self, strategy_id: str) -> float:
        """
        Get capital allocation for a strategy
        
        Args:
            strategy_id: Strategy ID
            
        Returns:
            Allocation percentage (0-1)
        """
        if not self.strategy_swarm:
            return 1.0 / max(1, len(self.deployed_strategies))
        
        return self.strategy_swarm.get_strategy_allocation(strategy_id)
    
    def deploy_strategy(self, strategy_id: str):
        """
        Deploy a strategy for live trading
        
        Args:
            strategy_id: Strategy to deploy
        """
        # Find strategy genome
        if self.genetic_engine:
            for genome in self.genetic_engine.population:
                if genome.id == strategy_id:
                    self.deployed_strategies.append(genome)
                    logger.info(f"🚀 Deployed strategy: {strategy_id}")
                    return
        
        logger.warning(f"⚠️  Strategy {strategy_id} not found for deployment")
    
    def get_engine_stats(self) -> Dict:
        """
        Get comprehensive engine statistics
        
        Returns:
            Dictionary with all engine stats
        """
        stats = {
            'enabled': self.enabled,
            'mode': self.mode,
            'evolution_cycle': self.evolution_cycle,
            'deployed_strategies': len(self.deployed_strategies),
        }
        
        if self.genetic_engine:
            stats['genetic'] = {
                'generation': self.genetic_engine.generation,
                'population_size': len(self.genetic_engine.population),
                'best_fitness': self.genetic_engine.best_genome.fitness if self.genetic_engine.best_genome else 0.0,
                'diversity': self.genetic_engine.get_population_diversity(),
            }
        
        if self.rl_selector:
            stats['reinforcement_learning'] = self.rl_selector.get_stats()
        
        if self.strategy_swarm:
            stats['swarm'] = self.strategy_swarm.get_swarm_stats()
        
        if self.strategy_breeder:
            stats['breeding'] = self.strategy_breeder.get_breeding_stats()
        
        if self.alpha_discovery:
            stats['alpha_discovery'] = self.alpha_discovery.get_discovery_stats()
        
        return stats
    
    def save_state(self, filepath: str):
        """
        Save engine state to file
        
        Args:
            filepath: Path to save state
        """
        state = {
            'config': self.config,
            'evolution_cycle': self.evolution_cycle,
            'deployed_strategies': [
                self.genetic_engine.export_genome(g) for g in self.deployed_strategies
            ] if self.genetic_engine else [],
            'stats': self.get_engine_stats(),
        }
        
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"💾 Meta-AI engine state saved to {filepath}")
    
    def is_enabled(self) -> bool:
        """Check if engine is enabled"""
        return self.enabled
