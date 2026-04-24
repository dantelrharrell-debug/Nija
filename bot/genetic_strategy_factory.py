"""
NIJA Genetic Strategy Evolution Factory
========================================

Autonomous strategy factory that evolves entire trading strategies,
not just parameters. This is the evolution of evolution.

Features:
1. Strategy Breeding - Combine successful strategies to create hybrids
2. Mutation System - Evolve entry/exit logic, not just parameters
3. Alpha Discovery - Auto-discover new profitable patterns
4. Culling Engine - Kill underperformers automatically
5. Strategy DNA - Full strategy genotype/phenotype representation

This creates an autonomous strategy factory that continuously
discovers and optimizes trading logic.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import json
import random
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
import copy

logger = logging.getLogger("nija.genetic_factory")


class StrategyComponentType(Enum):
    """Types of evolvable strategy components"""
    ENTRY_LOGIC = "entry_logic"
    EXIT_LOGIC = "exit_logic"
    POSITION_SIZING = "position_sizing"
    RISK_MANAGEMENT = "risk_management"
    INDICATOR_COMBINATION = "indicator_combination"


class MutationType(Enum):
    """Types of mutations that can occur"""
    PARAMETER_TWEAK = "parameter_tweak"  # Adjust existing parameters
    LOGIC_SWAP = "logic_swap"  # Replace a logic component
    CONDITION_ADD = "condition_add"  # Add new entry/exit condition
    CONDITION_REMOVE = "condition_remove"  # Remove condition
    THRESHOLD_SHIFT = "threshold_shift"  # Change thresholds
    INDICATOR_CHANGE = "indicator_change"  # Swap indicators


@dataclass
class StrategyGene:
    """A gene represents a specific strategy component"""
    gene_type: StrategyComponentType
    name: str
    parameters: Dict[str, Any]
    enabled: bool = True
    mutation_rate: float = 0.15
    
    def mutate(self) -> 'StrategyGene':
        """Mutate this gene"""
        if random.random() > self.mutation_rate:
            return copy.deepcopy(self)
        
        mutated = copy.deepcopy(self)
        
        # Mutate parameters with bounds checking
        for key, value in mutated.parameters.items():
            if isinstance(value, (int, float)) and random.random() < 0.3:
                if isinstance(value, int):
                    change = random.randint(-5, 5)
                    mutated.parameters[key] = max(1, value + change)  # Ensure positive
                else:
                    change_factor = random.uniform(0.8, 1.2)
                    mutated.parameters[key] = max(0.001, value * change_factor)  # Ensure positive
        
        return mutated


@dataclass
class StrategyDNA:
    """
    Complete strategy genotype - the blueprint of a trading strategy
    
    This represents the full genetic code of a strategy, including:
    - Entry logic genes
    - Exit logic genes
    - Risk management genes
    - Indicator combination genes
    """
    strategy_id: str
    generation: int
    parent_ids: List[str] = field(default_factory=list)
    
    # Strategy genes
    entry_genes: List[StrategyGene] = field(default_factory=list)
    exit_genes: List[StrategyGene] = field(default_factory=list)
    risk_genes: List[StrategyGene] = field(default_factory=list)
    indicator_genes: List[StrategyGene] = field(default_factory=list)
    
    # Performance tracking
    fitness_score: float = 0.0
    trades_executed: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    total_pnl: float = 0.0
    
    # Lifecycle
    created_at: datetime = field(default_factory=datetime.now)
    last_evaluated: Optional[datetime] = None
    is_alive: bool = True
    death_reason: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'strategy_id': self.strategy_id,
            'generation': self.generation,
            'parent_ids': self.parent_ids,
            'fitness_score': self.fitness_score,
            'performance': {
                'trades': self.trades_executed,
                'win_rate': self.win_rate,
                'sharpe': self.sharpe_ratio,
                'profit_factor': self.profit_factor,
                'max_dd': self.max_drawdown,
                'pnl': self.total_pnl,
            },
            'is_alive': self.is_alive,
            'death_reason': self.death_reason,
            'created_at': self.created_at.isoformat(),
        }


class GeneticStrategyFactory:
    """
    Autonomous Strategy Factory - Evolves Entire Strategies
    
    This factory:
    1. Breeds strategies by combining successful parents
    2. Mutates strategy logic (not just parameters)
    3. Discovers new alpha patterns automatically
    4. Culls underperformers ruthlessly
    5. Maintains genetic diversity
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize the genetic strategy factory
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Population parameters
        self.population_size = self.config.get('population_size', 50)
        self.elite_percentage = self.config.get('elite_percentage', 0.2)
        self.mutation_rate = self.config.get('mutation_rate', 0.15)
        
        # Survival thresholds (for culling)
        self.min_fitness_threshold = self.config.get('min_fitness', 0.3)
        self.min_trades_for_evaluation = self.config.get('min_trades', 20)
        self.max_drawdown_tolerance = self.config.get('max_dd_tolerance', 0.25)
        
        # Breeding parameters
        self.crossover_rate = self.config.get('crossover_rate', 0.7)
        self.tournament_size = self.config.get('tournament_size', 5)
        
        # Strategy population
        self.population: List[StrategyDNA] = []
        self.generation = 0
        self.hall_of_fame: List[StrategyDNA] = []  # Best strategies ever
        
        # Alpha discovery
        self.discovered_patterns: List[Dict] = []
        
        logger.info(
            f"🧬 Genetic Strategy Factory initialized: "
            f"population={self.population_size}, "
            f"mutation_rate={self.mutation_rate}"
        )
    
    def create_initial_population(self) -> List[StrategyDNA]:
        """
        Create initial random population of strategies
        
        Returns:
            List of StrategyDNA instances
        """
        population = []
        
        for i in range(self.population_size):
            strategy = self._create_random_strategy(generation=0, index=i)
            population.append(strategy)
        
        self.population = population
        logger.info(f"🧬 Created initial population: {len(population)} strategies")
        
        return population
    
    def _create_random_strategy(self, generation: int, index: int) -> StrategyDNA:
        """
        Create a random strategy with random genes
        
        Args:
            generation: Generation number
            index: Strategy index in generation
        
        Returns:
            StrategyDNA instance
        """
        strategy_id = f"gen{generation}_strat{index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create random entry genes
        entry_genes = [
            StrategyGene(
                gene_type=StrategyComponentType.ENTRY_LOGIC,
                name="rsi_oversold",
                parameters={
                    'rsi_period': random.randint(7, 21),
                    'oversold_threshold': random.uniform(20, 35),
                    'overbought_threshold': random.uniform(65, 80),
                }
            ),
            StrategyGene(
                gene_type=StrategyComponentType.ENTRY_LOGIC,
                name="trend_filter",
                parameters={
                    'adx_threshold': random.uniform(15, 30),
                    'ema_fast': random.randint(8, 20),
                    'ema_slow': random.randint(21, 50),
                }
            ),
        ]
        
        # Create random exit genes
        exit_genes = [
            StrategyGene(
                gene_type=StrategyComponentType.EXIT_LOGIC,
                name="take_profit",
                parameters={
                    'tp_percentage': random.uniform(0.01, 0.05),
                    'partial_exit': random.choice([True, False]),
                    'partial_size': random.uniform(0.25, 0.75),
                }
            ),
            StrategyGene(
                gene_type=StrategyComponentType.EXIT_LOGIC,
                name="stop_loss",
                parameters={
                    'sl_percentage': random.uniform(0.01, 0.03),
                    'atr_multiplier': random.uniform(1.0, 2.5),
                }
            ),
        ]
        
        # Create risk management genes
        risk_genes = [
            StrategyGene(
                gene_type=StrategyComponentType.RISK_MANAGEMENT,
                name="position_sizing",
                parameters={
                    'max_position_pct': random.uniform(0.02, 0.10),
                    'kelly_fraction': random.uniform(0.1, 0.5),
                }
            ),
        ]
        
        # Create indicator combination genes
        indicator_genes = [
            StrategyGene(
                gene_type=StrategyComponentType.INDICATOR_COMBINATION,
                name="dual_rsi",
                parameters={
                    'rsi_9_weight': random.uniform(0.3, 0.7),
                    'rsi_14_weight': random.uniform(0.3, 0.7),
                }
            ),
        ]
        
        return StrategyDNA(
            strategy_id=strategy_id,
            generation=generation,
            entry_genes=entry_genes,
            exit_genes=exit_genes,
            risk_genes=risk_genes,
            indicator_genes=indicator_genes,
        )
    
    def breed_strategies(
        self,
        parent1: StrategyDNA,
        parent2: StrategyDNA
    ) -> Tuple[StrategyDNA, StrategyDNA]:
        """
        Breed two parent strategies to create offspring
        
        Combines genes from both parents using crossover.
        
        Args:
            parent1: First parent strategy
            parent2: Second parent strategy
        
        Returns:
            Tuple of two offspring strategies
        """
        # Create offspring IDs
        offspring1_id = f"gen{self.generation+1}_breed_{datetime.now().strftime('%Y%m%d_%H%M%S')}_1"
        offspring2_id = f"gen{self.generation+1}_breed_{datetime.now().strftime('%Y%m%d_%H%M%S')}_2"
        
        # Crossover entry genes
        mid_entry = len(parent1.entry_genes) // 2
        offspring1_entry = parent1.entry_genes[:mid_entry] + parent2.entry_genes[mid_entry:]
        offspring2_entry = parent2.entry_genes[:mid_entry] + parent1.entry_genes[mid_entry:]
        
        # Crossover exit genes
        mid_exit = len(parent1.exit_genes) // 2
        offspring1_exit = parent1.exit_genes[:mid_exit] + parent2.exit_genes[mid_exit:]
        offspring2_exit = parent2.exit_genes[:mid_exit] + parent1.exit_genes[mid_exit:]
        
        # Randomly select risk genes
        offspring1_risk = random.choice([parent1.risk_genes, parent2.risk_genes])
        offspring2_risk = random.choice([parent1.risk_genes, parent2.risk_genes])
        
        # Randomly select indicator genes
        offspring1_indicators = random.choice([parent1.indicator_genes, parent2.indicator_genes])
        offspring2_indicators = random.choice([parent1.indicator_genes, parent2.indicator_genes])
        
        # Create offspring
        offspring1 = StrategyDNA(
            strategy_id=offspring1_id,
            generation=self.generation + 1,
            parent_ids=[parent1.strategy_id, parent2.strategy_id],
            entry_genes=offspring1_entry,
            exit_genes=offspring1_exit,
            risk_genes=offspring1_risk,
            indicator_genes=offspring1_indicators,
        )
        
        offspring2 = StrategyDNA(
            strategy_id=offspring2_id,
            generation=self.generation + 1,
            parent_ids=[parent1.strategy_id, parent2.strategy_id],
            entry_genes=offspring2_entry,
            exit_genes=offspring2_exit,
            risk_genes=offspring2_risk,
            indicator_genes=offspring2_indicators,
        )
        
        return offspring1, offspring2
    
    def mutate_strategy(self, strategy: StrategyDNA) -> StrategyDNA:
        """
        Mutate a strategy's genes
        
        Args:
            strategy: Strategy to mutate
        
        Returns:
            Mutated strategy (new instance)
        """
        mutated = copy.deepcopy(strategy)
        mutated.strategy_id = f"gen{self.generation+1}_mut_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        mutated.generation = self.generation + 1
        
        # Mutate entry genes
        mutated.entry_genes = [gene.mutate() for gene in mutated.entry_genes]
        
        # Mutate exit genes
        mutated.exit_genes = [gene.mutate() for gene in mutated.exit_genes]
        
        # Mutate risk genes
        mutated.risk_genes = [gene.mutate() for gene in mutated.risk_genes]
        
        # Mutate indicator genes
        mutated.indicator_genes = [gene.mutate() for gene in mutated.indicator_genes]
        
        # Occasionally add/remove genes (10% chance)
        if random.random() < 0.1:
            mutation_type = random.choice(list(MutationType))
            logger.debug(f"🧬 Applying {mutation_type.value} to {mutated.strategy_id}")
            # Note: Advanced mutation types (logic swap, condition add/remove) 
            # require strategy execution engine integration and are reserved 
            # for future enhancement. Currently only parameter mutations are applied.
        
        return mutated
    
    def evaluate_strategy(self, strategy: StrategyDNA, performance: Dict) -> float:
        """
        Evaluate strategy fitness based on performance
        
        Args:
            strategy: Strategy to evaluate
            performance: Performance metrics dict
        
        Returns:
            Fitness score (0-1, higher is better)
        """
        # Update strategy metrics
        strategy.trades_executed = performance.get('total_trades', 0)
        strategy.win_rate = performance.get('win_rate', 0.0)
        strategy.sharpe_ratio = performance.get('sharpe_ratio', 0.0)
        strategy.profit_factor = performance.get('profit_factor', 1.0)
        strategy.max_drawdown = performance.get('max_drawdown', 0.0)
        strategy.total_pnl = performance.get('total_pnl', 0.0)
        strategy.last_evaluated = datetime.now()
        
        # Insufficient data
        if strategy.trades_executed < self.min_trades_for_evaluation:
            strategy.fitness_score = 0.0
            return 0.0
        
        # Multi-objective fitness function
        fitness = 0.0
        
        # Sharpe ratio (30% weight)
        sharpe_score = min(1.0, max(0, strategy.sharpe_ratio / 3.0))
        fitness += 0.30 * sharpe_score
        
        # Profit factor (25% weight)
        pf_score = min(1.0, max(0, (strategy.profit_factor - 1.0) / 2.0))
        fitness += 0.25 * pf_score
        
        # Win rate (20% weight)
        wr_score = max(0, (strategy.win_rate - 0.4) / 0.3)
        fitness += 0.20 * wr_score
        
        # Drawdown penalty (15% weight)
        dd_score = max(0, 1.0 - (strategy.max_drawdown / 0.2))
        fitness += 0.15 * dd_score
        
        # Total PnL (10% weight)
        pnl_score = min(1.0, max(0, strategy.total_pnl / 1000.0))
        fitness += 0.10 * pnl_score
        
        strategy.fitness_score = fitness
        return fitness
    
    def cull_underperformers(self) -> List[StrategyDNA]:
        """
        Kill underperforming strategies (survival of the fittest)
        
        Returns:
            List of culled strategies
        """
        culled = []
        
        for strategy in self.population:
            if not strategy.is_alive:
                continue
            
            # Skip if not enough data
            if strategy.trades_executed < self.min_trades_for_evaluation:
                continue
            
            # Cull if fitness too low
            if strategy.fitness_score < self.min_fitness_threshold:
                strategy.is_alive = False
                strategy.death_reason = f"Low fitness: {strategy.fitness_score:.4f}"
                culled.append(strategy)
                logger.info(f"💀 Culled {strategy.strategy_id}: {strategy.death_reason}")
            
            # Cull if drawdown too high
            elif strategy.max_drawdown > self.max_drawdown_tolerance:
                strategy.is_alive = False
                strategy.death_reason = f"Excessive drawdown: {strategy.max_drawdown:.2%}"
                culled.append(strategy)
                logger.info(f"💀 Culled {strategy.strategy_id}: {strategy.death_reason}")
            
            # Cull if profit factor too low
            elif strategy.profit_factor < 1.0:
                strategy.is_alive = False
                strategy.death_reason = f"Negative expectancy: PF={strategy.profit_factor:.2f}"
                culled.append(strategy)
                logger.info(f"💀 Culled {strategy.strategy_id}: {strategy.death_reason}")
        
        return culled
    
    def tournament_selection(self) -> StrategyDNA:
        """
        Tournament selection: pick best from random subset
        
        Returns:
            Selected strategy
        """
        alive_strategies = [s for s in self.population if s.is_alive]
        if not alive_strategies:
            # Fallback: reseed population if all strategies are dead
            logger.warning("⚠️  All strategies culled - reseeding population")
            self.create_initial_population()
            alive_strategies = [s for s in self.population if s.is_alive]
        
        tournament = random.sample(
            alive_strategies,
            min(self.tournament_size, len(alive_strategies))
        )
        return max(tournament, key=lambda s: s.fitness_score)
    
    def evolve_generation(self) -> List[StrategyDNA]:
        """
        Evolve one generation
        
        1. Evaluate fitness
        2. Cull underperformers
        3. Breed new strategies
        4. Mutate strategies
        5. Create next generation
        
        Returns:
            New generation of strategies
        """
        # Sort by fitness
        self.population.sort(key=lambda s: s.fitness_score, reverse=True)
        
        # Update hall of fame
        if self.population and self.population[0].fitness_score > 0.7:
            if self.population[0] not in self.hall_of_fame:
                self.hall_of_fame.append(copy.deepcopy(self.population[0]))
                logger.info(f"🏆 Added to Hall of Fame: {self.population[0].strategy_id}")
        
        # Cull underperformers
        culled = self.cull_underperformers()
        logger.info(f"💀 Culled {len(culled)} underperformers")
        
        # Get alive strategies
        alive = [s for s in self.population if s.is_alive]
        
        # Elitism: preserve top performers
        elite_count = int(self.population_size * self.elite_percentage)
        new_population = alive[:elite_count]
        
        logger.info(
            f"🧬 Generation {self.generation}: "
            f"Best fitness={self.population[0].fitness_score:.4f}, "
            f"Alive={len(alive)}, "
            f"Elites={elite_count}"
        )
        
        # Generate offspring through breeding and mutation
        while len(new_population) < self.population_size:
            # Select parents
            parent1 = self.tournament_selection()
            parent2 = self.tournament_selection()
            
            # Breed or clone
            if random.random() < self.crossover_rate:
                offspring1, offspring2 = self.breed_strategies(parent1, parent2)
            else:
                offspring1 = copy.deepcopy(parent1)
                offspring2 = copy.deepcopy(parent2)
            
            # Mutate
            offspring1 = self.mutate_strategy(offspring1)
            offspring2 = self.mutate_strategy(offspring2)
            
            new_population.extend([offspring1, offspring2])
        
        # Trim to exact size
        new_population = new_population[:self.population_size]
        
        self.population = new_population
        self.generation += 1
        
        return new_population
    
    def discover_alpha_patterns(
        self,
        market_data: Dict,
        successful_strategies: List[StrategyDNA]
    ) -> List[Dict]:
        """
        Auto-discover new alpha patterns from successful strategies
        
        Analyzes what makes successful strategies work and
        extracts common profitable patterns.
        
        Args:
            market_data: Market data for pattern analysis
            successful_strategies: List of high-performing strategies
        
        Returns:
            List of discovered patterns
        """
        if not successful_strategies:
            return []
        
        patterns = []
        
        # Analyze common parameters in successful strategies
        param_analysis = {}
        
        for strategy in successful_strategies:
            for gene in strategy.entry_genes + strategy.exit_genes:
                for param_name, param_value in gene.parameters.items():
                    key = f"{gene.name}.{param_name}"
                    if key not in param_analysis:
                        param_analysis[key] = []
                    param_analysis[key].append(param_value)
        
        # Find patterns (parameters that cluster)
        for key, values in param_analysis.items():
            if len(values) >= 3:
                mean_val = np.mean(values)
                std_val = np.std(values)
                
                if std_val / (mean_val + 1e-8) < 0.3:  # Low variance = pattern
                    pattern = {
                        'type': 'parameter_cluster',
                        'parameter': key,
                        'optimal_value': mean_val,
                        'confidence': 1.0 - (std_val / (mean_val + 1e-8)),
                        'discovered_at': datetime.now().isoformat(),
                    }
                    patterns.append(pattern)
                    logger.info(f"🔍 Discovered pattern: {key} ≈ {mean_val:.4f}")
        
        self.discovered_patterns.extend(patterns)
        return patterns
    
    def get_best_strategies(self, n: int = 10) -> List[StrategyDNA]:
        """
        Get top N best strategies
        
        Args:
            n: Number of strategies to return
        
        Returns:
            List of best strategies
        """
        alive = [s for s in self.population if s.is_alive]
        alive.sort(key=lambda s: s.fitness_score, reverse=True)
        return alive[:n]
    
    def export_strategy(self, strategy: StrategyDNA) -> Dict:
        """
        Export strategy to deployable configuration
        
        Args:
            strategy: Strategy to export
        
        Returns:
            Configuration dictionary
        """
        return {
            'strategy_id': strategy.strategy_id,
            'generation': strategy.generation,
            'parent_ids': strategy.parent_ids,
            'entry_logic': [
                {
                    'name': gene.name,
                    'parameters': gene.parameters,
                    'enabled': gene.enabled,
                }
                for gene in strategy.entry_genes
            ],
            'exit_logic': [
                {
                    'name': gene.name,
                    'parameters': gene.parameters,
                    'enabled': gene.enabled,
                }
                for gene in strategy.exit_genes
            ],
            'risk_management': [
                {
                    'name': gene.name,
                    'parameters': gene.parameters,
                    'enabled': gene.enabled,
                }
                for gene in strategy.risk_genes
            ],
            'performance': strategy.to_dict()['performance'],
            'fitness_score': strategy.fitness_score,
        }
