"""
Strategy Breeder - Self-Breeding Strategy System
=================================================

Creates new strategies by combining successful parent strategies:
- Selects top-performing strategies as parents
- Creates hybrid strategies through parameter blending
- Mutates offspring for variation
- Tests offspring performance before deployment

Author: NIJA Trading Systems
"""

import random
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from .evolution_config import BREEDER_CONFIG, PARAMETER_SEARCH_SPACE
from .genetic_evolution import StrategyGenome

logger = logging.getLogger("nija.meta_ai.breeder")


@dataclass
class BreedingRecord:
    """
    Records a breeding event
    """
    parent1_id: str
    parent2_id: str
    offspring_id: str
    breeding_method: str  # 'hybrid' or 'mutation'
    timestamp: datetime
    parent1_fitness: float
    parent2_fitness: float
    offspring_fitness: float = 0.0


class StrategyBreeder:
    """
    Self-Breeding Strategy System

    Combines successful strategies to create new variants:
    - Hybrid breeding: blend parameters from two parents
    - Adaptive mutation: intelligent parameter perturbation
    - Performance tracking of offspring
    - Genealogy tracking for strategy lineage
    """

    def __init__(self, config: Dict = None):
        """
        Initialize strategy breeder

        Args:
            config: Configuration dictionary (uses BREEDER_CONFIG if None)
        """
        self.config = config or BREEDER_CONFIG
        self.breeding_history: List[BreedingRecord] = []
        self.last_breeding: Optional[datetime] = None
        self.generation_count = 0

        logger.info(
            f"🧬 Strategy Breeder initialized: "
            f"frequency={self.config['breeding_frequency']} days, "
            f"offspring_per_gen={self.config['offspring_per_generation']}"
        )

    def should_breed(self) -> bool:
        """
        Check if it's time for a new breeding cycle

        Returns:
            True if breeding should occur
        """
        if self.last_breeding is None:
            return True

        days_since_breeding = (
            datetime.utcnow() - self.last_breeding
        ).total_seconds() / 86400

        return days_since_breeding >= self.config['breeding_frequency']

    def select_parents(
        self,
        population: List[StrategyGenome]
    ) -> List[Tuple[StrategyGenome, StrategyGenome]]:
        """
        Select parent pairs for breeding

        Args:
            population: List of strategy genomes with fitness scores

        Returns:
            List of parent pairs
        """
        # Sort by fitness
        sorted_pop = sorted(population, key=lambda g: g.fitness, reverse=True)

        # Take top N performers
        top_n = self.config['parent_selection_top_n']
        parents = sorted_pop[:top_n]

        if len(parents) < 2:
            logger.warning("⚠️  Not enough strategies for breeding")
            return []

        # Create pairs
        pairs = []
        num_offspring = self.config['offspring_per_generation']

        for _ in range(num_offspring):
            # Randomly pair parents (with replacement)
            parent1 = random.choice(parents)
            parent2 = random.choice(parents)

            # Ensure different parents
            max_attempts = 10
            attempt = 0
            while parent1.id == parent2.id and attempt < max_attempts:
                parent2 = random.choice(parents)
                attempt += 1

            pairs.append((parent1, parent2))

        logger.info(f"👨‍👩‍👧 Selected {len(pairs)} parent pairs for breeding")
        return pairs

    def create_hybrid(
        self,
        parent1: StrategyGenome,
        parent2: StrategyGenome
    ) -> StrategyGenome:
        """
        Create hybrid strategy by blending parent parameters

        Args:
            parent1: First parent genome
            parent2: Second parent genome

        Returns:
            Hybrid offspring genome
        """
        hybrid_params = {}

        for param_name in PARAMETER_SEARCH_SPACE.keys():
            val1 = parent1.parameters[param_name]
            val2 = parent2.parameters[param_name]

            # Random blend based on inheritance rate
            if random.random() < self.config['trait_inheritance_rate']:
                # Weighted average favoring fitter parent
                if parent1.fitness >= parent2.fitness:
                    weight1 = 0.7
                    weight2 = 0.3
                else:
                    weight1 = 0.3
                    weight2 = 0.7

                hybrid_value = weight1 * val1 + weight2 * val2
            else:
                # Random selection from one parent
                hybrid_value = random.choice([val1, val2])

            # Clamp to valid range
            min_val, max_val = PARAMETER_SEARCH_SPACE[param_name]
            hybrid_params[param_name] = np.clip(hybrid_value, min_val, max_val)

        # Create hybrid genome
        offspring_id = (
            f"hybrid_{parent1.id[:8]}_{parent2.id[:8]}_"
            f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        )

        hybrid = StrategyGenome(
            id=offspring_id,
            generation=max(parent1.generation, parent2.generation) + 1,
            parameters=hybrid_params,
        )

        return hybrid

    def create_mutant(
        self,
        parent: StrategyGenome,
        mutation_strength: float = 0.2
    ) -> StrategyGenome:
        """
        Create mutated strategy from single parent

        Args:
            parent: Parent genome
            mutation_strength: Strength of mutation (0-1)

        Returns:
            Mutated offspring genome
        """
        mutant_params = parent.parameters.copy()

        # Mutate random subset of parameters
        params_to_mutate = random.sample(
            list(PARAMETER_SEARCH_SPACE.keys()),
            k=random.randint(1, len(PARAMETER_SEARCH_SPACE) // 2)
        )

        for param_name in params_to_mutate:
            current_value = mutant_params[param_name]
            min_val, max_val = PARAMETER_SEARCH_SPACE[param_name]
            param_range = max_val - min_val

            # Gaussian mutation with strength parameter
            mutation = np.random.normal(0, param_range * mutation_strength)
            new_value = current_value + mutation

            # Clamp to valid range
            mutant_params[param_name] = np.clip(new_value, min_val, max_val)

        # Create mutant genome
        offspring_id = (
            f"mutant_{parent.id[:8]}_"
            f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        )

        mutant = StrategyGenome(
            id=offspring_id,
            generation=parent.generation + 1,
            parameters=mutant_params,
        )

        return mutant

    def breed_generation(
        self,
        population: List[StrategyGenome]
    ) -> List[StrategyGenome]:
        """
        Execute full breeding cycle

        Args:
            population: Current strategy population with fitness scores

        Returns:
            List of offspring strategies
        """
        if not self.should_breed():
            logger.debug("⏳ Not time for breeding yet")
            return []

        # Select parent pairs
        parent_pairs = self.select_parents(population)

        if not parent_pairs:
            return []

        offspring = []

        for parent1, parent2 in parent_pairs:
            # Decide: hybrid or mutation
            if random.random() < self.config['hybrid_probability']:
                # Create hybrid
                child = self.create_hybrid(parent1, parent2)
                breeding_method = 'hybrid'
            else:
                # Create mutant from fitter parent
                parent = parent1 if parent1.fitness >= parent2.fitness else parent2
                child = self.create_mutant(parent)
                breeding_method = 'mutation'

            offspring.append(child)

            # Record breeding
            record = BreedingRecord(
                parent1_id=parent1.id,
                parent2_id=parent2.id,
                offspring_id=child.id,
                breeding_method=breeding_method,
                timestamp=datetime.utcnow(),
                parent1_fitness=parent1.fitness,
                parent2_fitness=parent2.fitness,
            )
            self.breeding_history.append(record)

        self.last_breeding = datetime.utcnow()
        self.generation_count += 1

        logger.info(
            f"🌱 Bred generation {self.generation_count}: "
            f"{len(offspring)} offspring created"
        )

        return offspring

    def get_breeding_stats(self) -> Dict:
        """
        Get breeding statistics

        Returns:
            Dictionary with breeding stats
        """
        if not self.breeding_history:
            return {
                'total_breedings': 0,
                'generations': 0,
                'avg_parent_fitness': 0.0,
                'hybrid_count': 0,
                'mutation_count': 0,
            }

        hybrid_count = sum(
            1 for r in self.breeding_history
            if r.breeding_method == 'hybrid'
        )

        mutation_count = sum(
            1 for r in self.breeding_history
            if r.breeding_method == 'mutation'
        )

        avg_parent_fitness = np.mean([
            (r.parent1_fitness + r.parent2_fitness) / 2
            for r in self.breeding_history
        ])

        return {
            'total_breedings': len(self.breeding_history),
            'generations': self.generation_count,
            'avg_parent_fitness': avg_parent_fitness,
            'hybrid_count': hybrid_count,
            'mutation_count': mutation_count,
        }

    def get_genealogy(self, strategy_id: str, max_depth: int = 10, _visited: set = None) -> List[BreedingRecord]:
        """
        Get breeding genealogy for a strategy

        Args:
            strategy_id: Strategy ID
            max_depth: Maximum depth to traverse (prevents infinite recursion)
            _visited: Internal set to track visited strategies (prevents cycles)

        Returns:
            List of breeding records in ancestry
        """
        if _visited is None:
            _visited = set()

        # Prevent cycles
        if strategy_id in _visited:
            return []

        # Prevent excessive depth
        if max_depth <= 0:
            return []

        _visited.add(strategy_id)
        genealogy = []

        # Find all breeding records involving this strategy
        for record in self.breeding_history:
            if record.offspring_id == strategy_id:
                genealogy.append(record)
                # Recursively find parent genealogies with depth limit
                genealogy.extend(self.get_genealogy(record.parent1_id, max_depth - 1, _visited.copy()))
                genealogy.extend(self.get_genealogy(record.parent2_id, max_depth - 1, _visited.copy()))

        return genealogy
