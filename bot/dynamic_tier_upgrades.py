"""
Dynamic Tier Upgrades

Automatically promotes accounts to higher tiers based on trading performance,
not just balance. This rewards good trading behavior and risk management.

Instead of static tiers based only on balance:
- STARTER ($50-$99)
- SAVER ($100-$249)
- etc.

Accounts can be upgraded dynamically when they prove they deserve it:
- High win rate
- Consistent execution
- Good risk management (low drawdown)
- Minimum trade count

Author: NIJA Trading Systems
Date: January 23, 2026
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import logging

from tier_config import TradingTier, get_tier_from_balance, get_tier_config

logger = logging.getLogger("nija.dynamic_tiers")


@dataclass
class PerformanceMetrics:
    """Trading performance metrics for tier upgrade evaluation"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    current_balance: float = 0.0
    starting_balance: float = 0.0
    peak_balance: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    days_active: int = 0

    def calculate_metrics(self):
        """Calculate derived metrics"""
        if self.total_trades > 0:
            self.win_rate_pct = (self.winning_trades / self.total_trades) * 100

        if self.peak_balance > 0 and self.current_balance < self.peak_balance:
            drawdown = self.peak_balance - self.current_balance
            self.max_drawdown_pct = (drawdown / self.peak_balance) * 100


@dataclass
class TierUpgradeRule:
    """Requirements for upgrading from one tier to another"""
    from_tier: TradingTier
    to_tier: TradingTier

    # Minimum requirements (all must be met)
    min_balance: Optional[float] = None  # Minimum balance required
    min_trades: Optional[int] = None  # Minimum number of trades
    min_win_rate: Optional[float] = None  # Minimum win rate percentage
    max_drawdown: Optional[float] = None  # Maximum drawdown percentage
    min_days_active: Optional[int] = None  # Minimum days trading

    description: str = ""

    def check_eligibility(self, metrics: PerformanceMetrics) -> Tuple[bool, str]:
        """
        Check if performance metrics meet upgrade requirements.

        Returns:
            Tuple of (eligible, reason)
        """
        reasons = []

        # Check balance requirement
        if self.min_balance and metrics.current_balance < self.min_balance:
            reasons.append(f"Balance ${metrics.current_balance:.2f} < ${self.min_balance:.2f}")

        # Check trade count requirement
        if self.min_trades and metrics.total_trades < self.min_trades:
            reasons.append(f"Trades {metrics.total_trades} < {self.min_trades}")

        # Check win rate requirement
        if self.min_win_rate and metrics.win_rate_pct < self.min_win_rate:
            reasons.append(f"Win rate {metrics.win_rate_pct:.1f}% < {self.min_win_rate:.1f}%")

        # Check drawdown requirement
        if self.max_drawdown and metrics.max_drawdown_pct > self.max_drawdown:
            reasons.append(f"Drawdown {metrics.max_drawdown_pct:.1f}% > {self.max_drawdown:.1f}%")

        # Check days active requirement
        if self.min_days_active and metrics.days_active < self.min_days_active:
            reasons.append(f"Days active {metrics.days_active} < {self.min_days_active}")

        if reasons:
            return (False, "Not eligible: " + ", ".join(reasons))

        return (True, f"Eligible for {self.to_tier.value} tier upgrade")


# Dynamic Tier Upgrade Rules
# These define the performance-based criteria for tier promotions
UPGRADE_RULES: Dict[TradingTier, TierUpgradeRule] = {
    TradingTier.STARTER: TierUpgradeRule(
        from_tier=TradingTier.STARTER,
        to_tier=TradingTier.SAVER,
        min_balance=100.0,  # OR performance criteria below
        min_trades=20,
        min_win_rate=55.0,
        max_drawdown=10.0,
        min_days_active=7,
        description="Upgrade from STARTER → SAVER: Prove consistent profitable trading"
    ),
    TradingTier.SAVER: TierUpgradeRule(
        from_tier=TradingTier.SAVER,
        to_tier=TradingTier.INVESTOR,
        min_balance=250.0,  # OR performance criteria below
        min_trades=40,
        min_win_rate=58.0,
        max_drawdown=12.0,
        min_days_active=14,
        description="Upgrade from SAVER → INVESTOR: Demonstrate risk management"
    ),
    TradingTier.INVESTOR: TierUpgradeRule(
        from_tier=TradingTier.INVESTOR,
        to_tier=TradingTier.INCOME,
        min_balance=1000.0,  # OR performance criteria below
        min_trades=60,
        min_win_rate=60.0,
        max_drawdown=15.0,
        min_days_active=30,
        description="Upgrade from INVESTOR → INCOME: Consistent profitability"
    ),
    TradingTier.INCOME: TierUpgradeRule(
        from_tier=TradingTier.INCOME,
        to_tier=TradingTier.LIVABLE,
        min_balance=5000.0,  # OR performance criteria below
        min_trades=100,
        min_win_rate=62.0,
        max_drawdown=18.0,
        min_days_active=60,
        description="Upgrade from INCOME → LIVABLE: Professional-level execution"
    ),
    TradingTier.LIVABLE: TierUpgradeRule(
        from_tier=TradingTier.LIVABLE,
        to_tier=TradingTier.BALLER,
        min_balance=25000.0,  # OR performance criteria below
        min_trades=200,
        min_win_rate=65.0,
        max_drawdown=20.0,
        min_days_active=90,
        description="Upgrade from LIVABLE → BALLER: Elite trading performance"
    ),
}


def evaluate_tier_upgrade(current_tier: TradingTier, metrics: PerformanceMetrics,
                          allow_balance_only: bool = True) -> Tuple[TradingTier, bool, str]:
    """
    Evaluate if account qualifies for a tier upgrade based on performance.

    Two paths to upgrade:
    1. Balance-based: Meet the minimum balance (traditional method)
    2. Performance-based: Meet trading performance criteria (new dynamic method)

    Args:
        current_tier: Current trading tier
        metrics: Performance metrics for evaluation
        allow_balance_only: If True, allow upgrade based on balance alone

    Returns:
        Tuple of (recommended_tier, was_upgraded, reason)
    """
    # Calculate derived metrics
    metrics.calculate_metrics()

    # Check if upgrade rule exists for current tier
    if current_tier not in UPGRADE_RULES:
        # Already at highest tier or no upgrade path
        return (current_tier, False, f"{current_tier.value} is at max tier")

    upgrade_rule = UPGRADE_RULES[current_tier]

    # PATH 1: Balance-based upgrade (traditional)
    if allow_balance_only and upgrade_rule.min_balance and metrics.current_balance >= upgrade_rule.min_balance:
        logger.info(f"✅ TIER UPGRADE (Balance): {current_tier.value} → {upgrade_rule.to_tier.value}")
        logger.info(f"   Balance: ${metrics.current_balance:.2f} ≥ ${upgrade_rule.min_balance:.2f}")
        return (upgrade_rule.to_tier, True,
                f"Balance-based upgrade: ${metrics.current_balance:.2f} ≥ ${upgrade_rule.min_balance:.2f}")

    # PATH 2: Performance-based upgrade (dynamic)
    eligible, reason = upgrade_rule.check_eligibility(metrics)

    if eligible:
        logger.info(f"✅ TIER UPGRADE (Performance): {current_tier.value} → {upgrade_rule.to_tier.value}")
        logger.info(f"   Trades: {metrics.total_trades}, Win Rate: {metrics.win_rate_pct:.1f}%")
        logger.info(f"   Drawdown: {metrics.max_drawdown_pct:.1f}%, Days: {metrics.days_active}")
        return (upgrade_rule.to_tier, True, f"Performance-based upgrade: {reason}")

    # No upgrade available
    return (current_tier, False, f"No upgrade: {reason}")


def get_upgrade_progress(current_tier: TradingTier, metrics: PerformanceMetrics) -> Dict:
    """
    Get progress towards next tier upgrade.

    Returns a dictionary showing how close the account is to upgrading.
    """
    if current_tier not in UPGRADE_RULES:
        return {
            "current_tier": current_tier.value,
            "next_tier": None,
            "progress": "At maximum tier"
        }

    metrics.calculate_metrics()
    upgrade_rule = UPGRADE_RULES[current_tier]

    progress = {
        "current_tier": current_tier.value,
        "next_tier": upgrade_rule.to_tier.value,
        "requirements": {},
        "progress_pct": 0.0
    }

    completed = 0
    total = 0

    # Check each requirement
    if upgrade_rule.min_balance:
        total += 1
        progress["requirements"]["balance"] = {
            "current": metrics.current_balance,
            "required": upgrade_rule.min_balance,
            "met": metrics.current_balance >= upgrade_rule.min_balance
        }
        if metrics.current_balance >= upgrade_rule.min_balance:
            completed += 1

    if upgrade_rule.min_trades:
        total += 1
        progress["requirements"]["trades"] = {
            "current": metrics.total_trades,
            "required": upgrade_rule.min_trades,
            "met": metrics.total_trades >= upgrade_rule.min_trades
        }
        if metrics.total_trades >= upgrade_rule.min_trades:
            completed += 1

    if upgrade_rule.min_win_rate:
        total += 1
        progress["requirements"]["win_rate"] = {
            "current": metrics.win_rate_pct,
            "required": upgrade_rule.min_win_rate,
            "met": metrics.win_rate_pct >= upgrade_rule.min_win_rate
        }
        if metrics.win_rate_pct >= upgrade_rule.min_win_rate:
            completed += 1

    if upgrade_rule.max_drawdown:
        total += 1
        progress["requirements"]["max_drawdown"] = {
            "current": metrics.max_drawdown_pct,
            "required": upgrade_rule.max_drawdown,
            "met": metrics.max_drawdown_pct <= upgrade_rule.max_drawdown
        }
        if metrics.max_drawdown_pct <= upgrade_rule.max_drawdown:
            completed += 1

    if upgrade_rule.min_days_active:
        total += 1
        progress["requirements"]["days_active"] = {
            "current": metrics.days_active,
            "required": upgrade_rule.min_days_active,
            "met": metrics.days_active >= upgrade_rule.min_days_active
        }
        if metrics.days_active >= upgrade_rule.min_days_active:
            completed += 1

    if total > 0:
        progress["progress_pct"] = (completed / total) * 100

    progress["completed"] = completed
    progress["total"] = total

    return progress


if __name__ == "__main__":
    # Test dynamic tier upgrades
    logging.basicConfig(level=logging.INFO)

    print("\n" + "="*70)
    print("DYNAMIC TIER UPGRADE SYSTEM".center(70))
    print("="*70)

    # Test Case 1: STARTER → SAVER (Performance-based)
    print("\nTest 1: STARTER with good performance")
    metrics = PerformanceMetrics(
        total_trades=25,
        winning_trades=15,
        losing_trades=10,
        current_balance=85.0,  # Below $100 minimum
        starting_balance=50.0,
        peak_balance=90.0,
        days_active=10
    )
    metrics.calculate_metrics()

    new_tier, upgraded, reason = evaluate_tier_upgrade(
        TradingTier.STARTER, metrics, allow_balance_only=True
    )

    print(f"Current: STARTER (${metrics.current_balance:.2f})")
    print(f"Result: {new_tier.value}")
    print(f"Upgraded: {upgraded}")
    print(f"Reason: {reason}")
    print(f"Win Rate: {metrics.win_rate_pct:.1f}%")
    print(f"Drawdown: {metrics.max_drawdown_pct:.1f}%")

    # Test Case 2: STARTER → SAVER (Balance-based)
    print("\n" + "-"*70)
    print("Test 2: STARTER with sufficient balance")
    metrics2 = PerformanceMetrics(
        total_trades=5,
        winning_trades=3,
        losing_trades=2,
        current_balance=120.0,  # Above $100 minimum
        starting_balance=50.0,
        peak_balance=120.0,
        days_active=3
    )

    new_tier2, upgraded2, reason2 = evaluate_tier_upgrade(
        TradingTier.STARTER, metrics2, allow_balance_only=True
    )

    print(f"Current: STARTER (${metrics2.current_balance:.2f})")
    print(f"Result: {new_tier2.value}")
    print(f"Upgraded: {upgraded2}")
    print(f"Reason: {reason2}")

    # Test Case 3: Progress tracking
    print("\n" + "-"*70)
    print("Test 3: Upgrade progress tracking")
    progress = get_upgrade_progress(TradingTier.STARTER, metrics)

    print(f"\nProgress to {progress['next_tier']}:")
    print(f"Overall: {progress['progress_pct']:.0f}% ({progress['completed']}/{progress['total']} requirements met)")
    print("\nRequirements:")
    for req_name, req_data in progress['requirements'].items():
        status = "✅" if req_data['met'] else "❌"
        print(f"  {status} {req_name}: {req_data['current']} / {req_data['required']}")
