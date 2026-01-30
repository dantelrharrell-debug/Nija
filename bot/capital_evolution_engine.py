"""
🔥 NIJA CAPITAL EVOLUTION ENGINE 🔥

Auto-Scaling System = Capital Evolution Engine

Three evolution modes that automatically adjust based on current capital:

STARTER — SURVIVAL MODE ($15 → $249)
- 3 positions
- 4% risk
- Goal: ACCELERATE COMPOUNDING

ADVANCED — MULTIPLIER MODE ($500 → $999)
- 4 positions
- 4% risk
- COPY TRADING ENABLED
- Goal: MULTI-ACCOUNT SCALE

ELITE — DOMINATION MODE ($1000+)
- 6 positions
- 5% risk
- Leverage enabled
- Goal: CAPITAL ACCELERATION + SaaS SCALE

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

logger = logging.getLogger("nija.capital_evolution")


class EvolutionMode(Enum):
    """Capital evolution mode classifications"""
    STARTER_SURVIVAL = "STARTER_SURVIVAL"  # $15-$249: Survival mode
    ADVANCED_MULTIPLIER = "ADVANCED_MULTIPLIER"  # $500-$999: Multiplier mode
    ELITE_DOMINATION = "ELITE_DOMINATION"  # $1000+: Domination mode


@dataclass
class EvolutionModeConfig:
    """Configuration for each evolution mode"""
    mode: EvolutionMode
    capital_min: float
    capital_max: float
    max_positions: int
    risk_per_trade_pct: float
    copy_trading_enabled: bool
    leverage_enabled: bool
    goal: str
    description: str

    def get_display_name(self) -> str:
        """Get formatted display name"""
        if self.mode == EvolutionMode.STARTER_SURVIVAL:
            return "🔥 STARTER — SURVIVAL MODE"
        elif self.mode == EvolutionMode.ADVANCED_MULTIPLIER:
            return "⚡ ADVANCED — MULTIPLIER MODE"
        elif self.mode == EvolutionMode.ELITE_DOMINATION:
            return "👑 ELITE — DOMINATION MODE"
        return self.mode.value


# Evolution mode configurations matching the problem statement
EVOLUTION_CONFIGS: Dict[EvolutionMode, EvolutionModeConfig] = {
    EvolutionMode.STARTER_SURVIVAL: EvolutionModeConfig(
        mode=EvolutionMode.STARTER_SURVIVAL,
        capital_min=15.0,
        capital_max=249.0,
        max_positions=3,
        risk_per_trade_pct=4.0,
        copy_trading_enabled=False,
        leverage_enabled=False,
        goal="ACCELERATE COMPOUNDING",
        description="Survival mode focused on rapid capital growth through compounding"
    ),
    EvolutionMode.ADVANCED_MULTIPLIER: EvolutionModeConfig(
        mode=EvolutionMode.ADVANCED_MULTIPLIER,
        capital_min=500.0,
        capital_max=999.0,
        max_positions=4,
        risk_per_trade_pct=4.0,
        copy_trading_enabled=True,
        leverage_enabled=False,
        goal="MULTI-ACCOUNT SCALE",
        description="Multiplier mode with copy trading for multi-account scaling"
    ),
    EvolutionMode.ELITE_DOMINATION: EvolutionModeConfig(
        mode=EvolutionMode.ELITE_DOMINATION,
        capital_min=1000.0,
        capital_max=float('inf'),
        max_positions=6,
        risk_per_trade_pct=5.0,
        copy_trading_enabled=True,
        leverage_enabled=True,
        goal="CAPITAL ACCELERATION + SaaS SCALE",
        description="Domination mode with maximum leverage and position capacity"
    ),
}


class CapitalEvolutionEngine:
    """
    🔥 NIJA Capital Evolution Engine 🔥

    Auto-scaling system that adapts trading parameters based on current capital.
    Automatically transitions between three evolution modes as capital grows.

    Features:
    - Automatic mode detection based on capital balance
    - Progressive scaling: more positions and risk as capital grows
    - Copy trading activation at ADVANCED tier
    - Leverage activation at ELITE tier
    - Seamless transitions between modes
    """

    def __init__(self, initial_capital: float, current_capital: Optional[float] = None):
        """
        Initialize Capital Evolution Engine

        Args:
            initial_capital: Starting capital amount
            current_capital: Current capital (defaults to initial_capital)
        """
        self.initial_capital = initial_capital
        self.current_capital = current_capital or initial_capital
        self.peak_capital = self.current_capital

        # Detect initial mode
        self.current_mode = self._detect_evolution_mode(self.current_capital)
        self.mode_config = EVOLUTION_CONFIGS[self.current_mode]

        # Track mode transitions
        self.mode_transitions: list = []
        self._log_mode_transition(None, self.current_mode, self.current_capital)

        logger.info("=" * 80)
        logger.info("🔥 CAPITAL EVOLUTION ENGINE INITIALIZED 🔥")
        logger.info("=" * 80)
        logger.info(f"Initial Capital: ${initial_capital:.2f}")
        logger.info(f"Current Capital: ${self.current_capital:.2f}")
        logger.info(f"Current Mode: {self.mode_config.get_display_name()}")
        logger.info(f"  Max Positions: {self.mode_config.max_positions}")
        logger.info(f"  Risk Per Trade: {self.mode_config.risk_per_trade_pct}%")
        logger.info(f"  Copy Trading: {'ENABLED ✅' if self.mode_config.copy_trading_enabled else 'DISABLED'}")
        logger.info(f"  Leverage: {'ENABLED ✅' if self.mode_config.leverage_enabled else 'DISABLED'}")
        logger.info(f"  Goal: {self.mode_config.goal}")
        logger.info("=" * 80)

    def _detect_evolution_mode(self, capital: float) -> EvolutionMode:
        """
        Detect evolution mode based on capital balance

        Special handling for transition zone ($250-$499):
        - Maintains STARTER mode to avoid premature jump to ADVANCED

        Args:
            capital: Current capital balance

        Returns:
            EvolutionMode enum
        """
        # Check for ELITE mode first (highest tier)
        if capital >= EVOLUTION_CONFIGS[EvolutionMode.ELITE_DOMINATION].capital_min:
            return EvolutionMode.ELITE_DOMINATION

        # Check for ADVANCED mode
        if capital >= EVOLUTION_CONFIGS[EvolutionMode.ADVANCED_MULTIPLIER].capital_min:
            return EvolutionMode.ADVANCED_MULTIPLIER

        # Default to STARTER mode
        # This includes:
        # - $15-$249 (official STARTER range)
        # - $250-$499 (transition zone, stays in STARTER)
        # - Below $15 (edge case, treated as STARTER)
        return EvolutionMode.STARTER_SURVIVAL

    def _log_mode_transition(self, old_mode: Optional[EvolutionMode],
                            new_mode: EvolutionMode, capital: float) -> None:
        """Log and record mode transition"""
        transition = {
            'timestamp': datetime.now(),
            'from_mode': old_mode.value if old_mode else None,
            'to_mode': new_mode.value,
            'capital': capital
        }
        self.mode_transitions.append(transition)

        if old_mode and old_mode != new_mode:
            old_config = EVOLUTION_CONFIGS[old_mode]
            new_config = EVOLUTION_CONFIGS[new_mode]

            logger.info("🚀 " + "=" * 76)
            logger.info(f"🚀 EVOLUTION MODE TRANSITION!")
            logger.info("🚀 " + "=" * 76)
            logger.info(f"Capital: ${capital:.2f}")
            logger.info(f"From: {old_config.get_display_name()}")
            logger.info(f"  To: {new_config.get_display_name()}")
            logger.info("")
            logger.info("Configuration Changes:")
            logger.info(f"  Max Positions: {old_config.max_positions} → {new_config.max_positions}")
            logger.info(f"  Risk Per Trade: {old_config.risk_per_trade_pct}% → {new_config.risk_per_trade_pct}%")
            logger.info(f"  Copy Trading: {old_config.copy_trading_enabled} → {new_config.copy_trading_enabled}")
            logger.info(f"  Leverage: {old_config.leverage_enabled} → {new_config.leverage_enabled}")
            logger.info(f"  Goal: {new_config.goal}")
            logger.info("🚀 " + "=" * 76)

    def update_capital(self, new_capital: float) -> Optional[EvolutionMode]:
        """
        Update current capital and check for mode transitions

        Args:
            new_capital: New capital balance

        Returns:
            New mode if transition occurred, None otherwise
        """
        old_capital = self.current_capital
        old_mode = self.current_mode

        self.current_capital = new_capital

        # Update peak capital
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital

        # Detect if mode should change
        new_mode = self._detect_evolution_mode(new_capital)

        if new_mode != old_mode:
            # Mode transition occurred
            self.current_mode = new_mode
            self.mode_config = EVOLUTION_CONFIGS[new_mode]
            self._log_mode_transition(old_mode, new_mode, new_capital)
            return new_mode

        # No transition
        logger.debug(f"Capital updated: ${old_capital:.2f} → ${new_capital:.2f} "
                    f"(Mode: {self.mode_config.get_display_name()})")
        return None

    def get_max_positions(self) -> int:
        """Get maximum concurrent positions for current mode"""
        return self.mode_config.max_positions

    def get_risk_per_trade_pct(self) -> float:
        """Get risk percentage per trade for current mode"""
        return self.mode_config.risk_per_trade_pct

    def is_copy_trading_enabled(self) -> bool:
        """Check if copy trading is enabled for current mode"""
        return self.mode_config.copy_trading_enabled

    def is_leverage_enabled(self) -> bool:
        """Check if leverage is enabled for current mode"""
        return self.mode_config.leverage_enabled

    def get_evolution_status(self) -> Dict:
        """
        Get comprehensive evolution status

        Returns:
            Dictionary with evolution metrics
        """
        config = self.mode_config

        # Calculate progress to next tier
        next_mode = None
        progress_pct = 0.0
        remaining_to_next = 0.0

        if self.current_mode == EvolutionMode.STARTER_SURVIVAL:
            next_mode = EvolutionMode.ADVANCED_MULTIPLIER
            next_config = EVOLUTION_CONFIGS[next_mode]
            total_range = next_config.capital_min - config.capital_min
            current_progress = self.current_capital - config.capital_min
            progress_pct = (current_progress / total_range) * 100
            remaining_to_next = next_config.capital_min - self.current_capital
        elif self.current_mode == EvolutionMode.ADVANCED_MULTIPLIER:
            next_mode = EvolutionMode.ELITE_DOMINATION
            next_config = EVOLUTION_CONFIGS[next_mode]
            total_range = next_config.capital_min - config.capital_min
            current_progress = self.current_capital - config.capital_min
            progress_pct = (current_progress / total_range) * 100
            remaining_to_next = next_config.capital_min - self.current_capital

        return {
            'initial_capital': self.initial_capital,
            'current_capital': self.current_capital,
            'peak_capital': self.peak_capital,
            'total_profit': self.current_capital - self.initial_capital,
            'roi_pct': ((self.current_capital - self.initial_capital) / self.initial_capital) * 100,
            'current_mode': self.current_mode.value,
            'mode_display_name': config.get_display_name(),
            'max_positions': config.max_positions,
            'risk_per_trade_pct': config.risk_per_trade_pct,
            'copy_trading_enabled': config.copy_trading_enabled,
            'leverage_enabled': config.leverage_enabled,
            'goal': config.goal,
            'next_mode': next_mode.value if next_mode else None,
            'progress_to_next_pct': min(progress_pct, 100.0),
            'remaining_to_next': max(remaining_to_next, 0.0),
            'mode_transitions': len(self.mode_transitions) - 1,  # Exclude initial
        }

    def get_evolution_report(self) -> str:
        """Generate comprehensive evolution report"""
        status = self.get_evolution_status()
        config = self.mode_config

        report = [
            "\n" + "=" * 90,
            "🔥 CAPITAL EVOLUTION ENGINE - STATUS REPORT 🔥",
            "=" * 90,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "💰 CAPITAL STATUS",
            "-" * 90,
            f"  Initial Capital:      ${status['initial_capital']:>12,.2f}",
            f"  Current Capital:      ${status['current_capital']:>12,.2f}",
            f"  Peak Capital:         ${status['peak_capital']:>12,.2f}",
            f"  Total Profit:         ${status['total_profit']:>12,.2f}",
            f"  ROI:                  {status['roi_pct']:>12.2f}%",
            "",
            "🚀 EVOLUTION MODE",
            "-" * 90,
            f"  Mode: {config.get_display_name()}",
            f"  Capital Range: ${config.capital_min:.0f} - ${config.capital_max:.0f}",
            f"  Goal: {config.goal}",
            "",
            "⚙️  CURRENT CONFIGURATION",
            "-" * 90,
            f"  Max Positions:        {status['max_positions']}",
            f"  Risk Per Trade:       {status['risk_per_trade_pct']:.1f}%",
            f"  Copy Trading:         {'ENABLED ✅' if status['copy_trading_enabled'] else 'DISABLED ❌'}",
            f"  Leverage:             {'ENABLED ✅' if status['leverage_enabled'] else 'DISABLED ❌'}",
            "",
        ]

        # Add progress to next tier if applicable
        if status['next_mode']:
            next_config = EVOLUTION_CONFIGS[EvolutionMode(status['next_mode'])]
            report.extend([
                "📈 PROGRESS TO NEXT TIER",
                "-" * 90,
                f"  Next Mode: {next_config.get_display_name()}",
                f"  Progress: {status['progress_to_next_pct']:.1f}%",
                f"  Remaining: ${status['remaining_to_next']:.2f}",
                f"  Target: ${next_config.capital_min:.2f}",
                "",
                "  Next Tier Upgrades:",
                f"    Max Positions: {config.max_positions} → {next_config.max_positions}",
                f"    Risk Per Trade: {config.risk_per_trade_pct}% → {next_config.risk_per_trade_pct}%",
                f"    Copy Trading: {config.copy_trading_enabled} → {next_config.copy_trading_enabled}",
                f"    Leverage: {config.leverage_enabled} → {next_config.leverage_enabled}",
                "",
            ])
        else:
            report.extend([
                "👑 MAXIMUM TIER ACHIEVED",
                "-" * 90,
                "  You are at the ELITE DOMINATION tier!",
                "  All features unlocked. Continue scaling for SaaS expansion.",
                "",
            ])

        # Add transition history
        if status['mode_transitions'] > 0:
            report.extend([
                "📊 MODE TRANSITION HISTORY",
                "-" * 90,
                f"  Total Transitions: {status['mode_transitions']}",
                "",
            ])
            for i, transition in enumerate(self.mode_transitions[1:], 1):  # Skip initial
                from_name = EVOLUTION_CONFIGS[EvolutionMode(transition['from_mode'])].get_display_name() if transition['from_mode'] else "Initial"
                to_name = EVOLUTION_CONFIGS[EvolutionMode(transition['to_mode'])].get_display_name()
                report.append(f"  {i}. {transition['timestamp'].strftime('%Y-%m-%d %H:%M')} | "
                            f"{from_name} → {to_name} | ${transition['capital']:.2f}")
            report.append("")

        report.append("=" * 90 + "\n")

        return "\n".join(report)

    def get_quick_summary(self) -> str:
        """Get a quick one-line summary"""
        status = self.get_evolution_status()
        summary = (
            f"{self.mode_config.get_display_name()} | "
            f"💰 ${status['current_capital']:.2f} "
            f"({status['roi_pct']:+.1f}% ROI) | "
            f"🎯 {status['max_positions']} pos | "
            f"{status['risk_per_trade_pct']:.0f}% risk"
        )

        if status['next_mode']:
            summary += f" | 📈 {status['progress_to_next_pct']:.0f}% to next tier"

        return summary


def get_evolution_engine(initial_capital: float,
                        current_capital: Optional[float] = None) -> CapitalEvolutionEngine:
    """
    Get or create capital evolution engine instance

    Args:
        initial_capital: Starting capital
        current_capital: Current capital (optional)

    Returns:
        CapitalEvolutionEngine instance
    """
    return CapitalEvolutionEngine(initial_capital, current_capital)


# Singleton instance (optional pattern)
_evolution_engine: Optional[CapitalEvolutionEngine] = None


def get_singleton_evolution_engine(initial_capital: float = None,
                                   current_capital: Optional[float] = None,
                                   reset: bool = False) -> Optional[CapitalEvolutionEngine]:
    """
    Get singleton evolution engine instance

    Args:
        initial_capital: Starting capital (required on first call)
        current_capital: Current capital (optional)
        reset: Force reset and create new instance

    Returns:
        CapitalEvolutionEngine instance or None if not initialized
    """
    global _evolution_engine

    if _evolution_engine is None or reset:
        if initial_capital is None:
            logger.warning("Cannot create evolution engine without initial_capital")
            return None
        _evolution_engine = CapitalEvolutionEngine(initial_capital, current_capital)

    return _evolution_engine


if __name__ == "__main__":
    # Test/demonstration
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )

    print("\n" + "=" * 90)
    print("🔥 CAPITAL EVOLUTION ENGINE - DEMONSTRATION 🔥")
    print("=" * 90 + "\n")

    # Test Case 1: STARTER mode
    print("Test Case 1: Starting with $50 (STARTER MODE)")
    print("-" * 90)
    engine = get_evolution_engine(initial_capital=50.0)
    print(engine.get_quick_summary())
    print()

    # Simulate capital growth to ADVANCED
    print("Test Case 2: Growing to $500 (ADVANCED MODE)")
    print("-" * 90)
    engine.update_capital(500.0)
    print(engine.get_quick_summary())
    print()

    # Simulate capital growth to ELITE
    print("Test Case 3: Growing to $1000 (ELITE MODE)")
    print("-" * 90)
    engine.update_capital(1000.0)
    print(engine.get_quick_summary())
    print()

    # Generate full report
    print(engine.get_evolution_report())

    # Test intermediate values
    print("\n" + "=" * 90)
    print("TESTING INTERMEDIATE VALUES")
    print("=" * 90 + "\n")

    test_capitals = [15, 50, 100, 249, 250, 499, 500, 750, 999, 1000, 2500, 10000]
    for capital in test_capitals:
        test_engine = get_evolution_engine(initial_capital=capital)
        mode = test_engine.current_mode
        config = test_engine.mode_config
        print(f"${capital:>6,.0f} → {config.get_display_name():<30} | "
              f"Pos: {config.max_positions} | Risk: {config.risk_per_trade_pct}% | "
              f"Copy: {config.copy_trading_enabled} | Leverage: {config.leverage_enabled}")
