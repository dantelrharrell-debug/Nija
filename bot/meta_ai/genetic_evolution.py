"""
Genetic Evolution Engine for Strategy Parameter Optimization
=============================================================

Uses genetic algorithms to evolve trading strategy parameters:
- Tournament selection for parent selection
- Single-point and multi-point crossover
- Gaussian mutation for continuous parameters
- Elitism to preserve top performers
- Fitness evaluation based on backtest performance

Author: NIJA Trading Systems
"""

import random
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from .evolution_config import (
    GENETIC_CONFIG,
    PARAMETER_SEARCH_SPACE,
    SURVIVAL_THRESHOLDS,
)

logger = logging.getLogger("nija.meta_ai.genetic")


@dataclass
class StrategyGenome:
    """
    Represents a strategy's genetic code (parameters)
    """
    id: str
    generation: int
    parameters: Dict[str, float]
    fitness: float = 0.0
    trades_count: int = 0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


class GeneticEvolution:
    """
    Genetic Algorithm for Strategy Evolution
    
    Evolves trading strategy parameters through:
    1. Selection - Tournament selection of fittest individuals
    2. Crossover - Combine parameters from two parents
    3. Mutation - Random parameter changes
    4. Evaluation - Backtest performance as fitness
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize genetic evolution engine
        
        Args:
            config: Configuration dictionary (uses GENETIC_CONFIG if None)
        """
        self.config = config or GENETIC_CONFIG
        self.population: List[StrategyGenome] = []
        self.generation = 0
        self.best_genome: Optional[StrategyGenome] = None
        self.fitness_history: List[float] = []
        
        logger.info(
            f"🧬 Genetic Evolution initialized: "
            f"population={self.config['population_size']}, "
            f"generations={self.config['generations']}"
        )
    
    def initialize_population(self) -> List[StrategyGenome]:
        """
        Create initial random population
        
        Returns:
            List of StrategyGenome instances
        """
        population = []
        
        for i in range(self.config['population_size']):
            genome = self._create_random_genome(generation=0, index=i)
            population.append(genome)
        
        self.population = population
        logger.info(f"🧬 Initialized population with {len(population)} strategies")
        return population
    
    def _create_random_genome(self, generation: int, index: int) -> StrategyGenome:
        """
        Create a random strategy genome within search space
        
        Args:
            generation: Generation number
            index: Individual index in generation
            
        Returns:
            StrategyGenome with random parameters
        """
        parameters = {}
        
        for param_name, (min_val, max_val) in PARAMETER_SEARCH_SPACE.items():
            # Random value within range
            if isinstance(min_val, int) and isinstance(max_val, int):
                # Integer parameter
                parameters[param_name] = random.randint(min_val, max_val)
            else:
                # Float parameter
                parameters[param_name] = random.uniform(min_val, max_val)
        
        genome_id = f"gen{generation}_ind{index}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        return StrategyGenome(
            id=genome_id,
            generation=generation,
            parameters=parameters,
        )
    
    def evaluate_fitness(
        self,
        genome: StrategyGenome,
        backtest_results: Dict
    ) -> float:
        """
        Calculate fitness score from backtest results
        
        Args:
            genome: Strategy genome to evaluate
            backtest_results: Dict with performance metrics
            
        Returns:
            Fitness score (higher is better)
        """
        # Extract metrics
        sharpe = backtest_results.get('sharpe_ratio', 0)
        profit_factor = backtest_results.get('profit_factor', 1.0)
        win_rate = backtest_results.get('win_rate', 0.5)
        max_dd = backtest_results.get('max_drawdown', 1.0)
        expectancy = backtest_results.get('expectancy', 0)
        trades_count = backtest_results.get('total_trades', 0)
        
        # Update genome metrics
        genome.sharpe_ratio = sharpe
        genome.profit_factor = profit_factor
        genome.win_rate = win_rate
        genome.max_drawdown = max_dd
        genome.trades_count = trades_count
        
        # Insufficient data
        if trades_count < self.config['min_trades']:
            genome.fitness = 0.0
            return 0.0
        
        # Multi-objective fitness function
        # Weighted combination of multiple metrics
        fitness = 0.0
        
        # Sharpe ratio (25% weight)
        fitness += 0.25 * max(0, sharpe / 2.0)  # Normalize to ~1.0 for Sharpe=2.0
        
        # Profit factor (20% weight)
        fitness += 0.20 * max(0, (profit_factor - 1.0) / 2.0)  # PF=3.0 gives 0.20
        
        # Win rate (15% weight)
        fitness += 0.15 * max(0, (win_rate - 0.4) / 0.3)  # 40-70% maps to 0-0.15
        
        # Max drawdown penalty (15% weight)
        # Lower drawdown = higher fitness
        dd_score = max(0, 1.0 - (max_dd / 0.2))  # 0% DD = 1.0, 20% DD = 0
        fitness += 0.15 * dd_score
        
        # Expectancy (15% weight)
        fitness += 0.15 * max(0, expectancy / 0.5)  # Expectancy=0.5R gives 0.15
        
        # Trade count bonus (10% weight)
        # More trades = more statistical significance
        trade_score = min(1.0, trades_count / 100.0)  # 100+ trades = max score
        fitness += 0.10 * trade_score
        
        genome.fitness = fitness
        return fitness
    
    def tournament_selection(self, k: int = None) -> StrategyGenome:
        """
        Tournament selection: pick best from k random individuals
        
        Args:
            k: Tournament size (uses config if None)
            
        Returns:
            Selected genome
        """
        k = k or self.config['tournament_size']
        tournament = random.sample(self.population, min(k, len(self.population)))
        return max(tournament, key=lambda g: g.fitness)
    
    def crossover(
        self,
        parent1: StrategyGenome,
        parent2: StrategyGenome
    ) -> Tuple[StrategyGenome, StrategyGenome]:
        """
        Single-point crossover between two parents
        
        Args:
            parent1: First parent genome
            parent2: Second parent genome
            
        Returns:
            Tuple of two offspring genomes
        """
        # Crossover point
        params = list(PARAMETER_SEARCH_SPACE.keys())
        crossover_point = random.randint(1, len(params) - 1)
        
        # Create offspring
        offspring1_params = {}
        offspring2_params = {}
        
        for i, param in enumerate(params):
            if i < crossover_point:
                offspring1_params[param] = parent1.parameters[param]
                offspring2_params[param] = parent2.parameters[param]
            else:
                offspring1_params[param] = parent2.parameters[param]
                offspring2_params[param] = parent1.parameters[param]
        
        # Create offspring genomes
        offspring1 = StrategyGenome(
            id=f"gen{self.generation+1}_cross_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_1",
            generation=self.generation + 1,
            parameters=offspring1_params,
        )
        
        offspring2 = StrategyGenome(
            id=f"gen{self.generation+1}_cross_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_2",
            generation=self.generation + 1,
            parameters=offspring2_params,
        )
        
        return offspring1, offspring2
    
    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """
        Gaussian mutation of strategy parameters
        
        Args:
            genome: Genome to mutate
            
        Returns:
            Mutated genome (new instance)
        """
        mutated_params = genome.parameters.copy()
        
        for param_name, value in mutated_params.items():
            # Mutate with probability
            if random.random() < self.config['mutation_rate']:
                min_val, max_val = PARAMETER_SEARCH_SPACE[param_name]
                param_range = max_val - min_val
                
                # Gaussian mutation (10% std dev of range)
                mutation = np.random.normal(0, param_range * 0.1)
                new_value = value + mutation
                
                # Clamp to valid range
                mutated_params[param_name] = np.clip(new_value, min_val, max_val)
        
        # Create mutated genome
        mutated = StrategyGenome(
            id=f"gen{self.generation+1}_mut_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            generation=self.generation + 1,
            parameters=mutated_params,
        )
        
        return mutated
    
    def evolve_generation(self) -> List[StrategyGenome]:
        """
        Evolve one generation
        
        Returns:
            New generation of genomes
        """
        # Sort by fitness
        self.population.sort(key=lambda g: g.fitness, reverse=True)
        
        # Track best
        if self.population:
            self.best_genome = self.population[0]
            self.fitness_history.append(self.best_genome.fitness)
        
        # Elitism: preserve top performers
        elite_count = int(self.config['population_size'] * self.config['elite_percentage'])
        new_population = self.population[:elite_count].copy()
        
        logger.info(
            f"🧬 Generation {self.generation}: "
            f"Best fitness={self.best_genome.fitness:.4f}, "
            f"Avg fitness={np.mean([g.fitness for g in self.population]):.4f}, "
            f"Preserving {elite_count} elites"
        )
        
        # Generate offspring
        while len(new_population) < self.config['population_size']:
            # Selection
            parent1 = self.tournament_selection()
            parent2 = self.tournament_selection()
            
            # Crossover
            if random.random() < self.config['crossover_rate']:
                offspring1, offspring2 = self.crossover(parent1, parent2)
            else:
                # Clone parents if no crossover
                offspring1 = parent1
                offspring2 = parent2
            
            # Mutation
            offspring1 = self.mutate(offspring1)
            offspring2 = self.mutate(offspring2)
            
            new_population.extend([offspring1, offspring2])
        
        # Trim to exact population size
        new_population = new_population[:self.config['population_size']]
        
        self.population = new_population
        self.generation += 1
        
        return new_population
    
    def get_best_strategy(self) -> Optional[StrategyGenome]:
        """
        Get the best strategy found so far
        
        Returns:
            Best genome or None
        """
        return self.best_genome
    
    def get_population_diversity(self) -> float:
        """
        Calculate population diversity (genetic variation)
        
        Returns:
            Diversity score (0-1, higher = more diverse)
        """
        if len(self.population) < 2:
            return 0.0
        
        # Calculate pairwise parameter differences
        params = list(PARAMETER_SEARCH_SPACE.keys())
        differences = []
        
        for i in range(len(self.population)):
            for j in range(i + 1, len(self.population)):
                genome1 = self.population[i]
                genome2 = self.population[j]
                
                # Normalized difference for each parameter
                param_diffs = []
                for param in params:
                    min_val, max_val = PARAMETER_SEARCH_SPACE[param]
                    range_val = max_val - min_val
                    diff = abs(genome1.parameters[param] - genome2.parameters[param])
                    param_diffs.append(diff / range_val)
                
                # Average difference for this pair
                differences.append(np.mean(param_diffs))
        
        # Overall diversity is average pairwise difference
        diversity = np.mean(differences) if differences else 0.0
        return diversity
    
    def export_genome(self, genome: StrategyGenome) -> Dict:
        """
        Export genome to dictionary for storage/deployment
        
        Args:
            genome: Genome to export
            
        Returns:
            Dictionary representation
        """
        return {
            'id': genome.id,
            'generation': genome.generation,
            'parameters': genome.parameters,
            'fitness': genome.fitness,
            'metrics': {
                'sharpe_ratio': genome.sharpe_ratio,
                'profit_factor': genome.profit_factor,
                'win_rate': genome.win_rate,
                'max_drawdown': genome.max_drawdown,
                'trades_count': genome.trades_count,
            },
            'created_at': genome.created_at.isoformat(),
        }
