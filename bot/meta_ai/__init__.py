"""
NIJA META-AI STRATEGY EVOLUTION ENGINE
=======================================

Advanced strategy evolution system with:
- Genetic algorithm-based parameter optimization
- Reinforcement learning strategy selection
- Multi-strategy swarm intelligence
- Self-breeding strategy combinations
- Automated alpha discovery

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

from .genetic_evolution import GeneticEvolution
from .reinforcement_learning import RLStrategySelector
from .strategy_swarm import StrategySwarm
from .strategy_breeder import StrategyBreeder
from .alpha_discovery import AlphaDiscovery
from .evolution_engine import MetaAIEvolutionEngine

__all__ = [
    'GeneticEvolution',
    'RLStrategySelector',
    'StrategySwarm',
    'StrategyBreeder',
    'AlphaDiscovery',
    'MetaAIEvolutionEngine',
]

__version__ = '1.0.0'
