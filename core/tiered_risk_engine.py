"""
NIJA Tiered Risk Engine

Multi-layer risk protection system that all trades must pass through:

    Capital Guard → Drawdown Guard → Volatility Guard → Execution Gate

This enforces:
- Tier-specific risk rules
- Daily loss caps
- Black swan detection
- Kill switch logic

Protects:
- User capital
- Platform reputation
- Long-term profitability

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
from enum import Enum
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger("nija.tiered_risk_engine")


class RiskLevel(Enum):
    """Risk assessment levels."""
    SAFE = "safe"           # Trade approved
    WARNING = "warning"     # Trade allowed with caution
    DANGER = "danger"       # Trade should be rejected
    CRITICAL = "critical"   # Kill switch - stop all trading


@dataclass
class RiskLimits:
    """Risk limits for a specific tier."""
    tier_name: str
    max_position_size_pct: float      # % of total capital per trade
    max_daily_loss_pct: float         # Maximum daily loss allowed
    max_drawdown_pct: float           # Maximum drawdown from peak
    max_concurrent_positions: int     # Maximum simultaneous positions
    volatility_threshold: float       # Maximum market volatility to trade
    min_trade_size_usd: float        # Minimum trade size in USD
    max_trade_size_usd: float        # Maximum trade size in USD


class TieredRiskEngine:
    """
    Multi-layer risk engine that validates all trades.

    Each trade passes through 4 gates:
    1. Capital Guard - Position sizing and capital limits
    2. Drawdown Guard - Daily/weekly loss limits
    3. Volatility Guard - Market condition checks
    4. Execution Gate - Final validation before execution
    """

    # Tier-specific risk limits
    TIER_RISK_LIMITS = {
        "STARTER": RiskLimits(
            tier_name="STARTER",
            max_position_size_pct=15.0,
            max_daily_loss_pct=10.0,
            max_drawdown_pct=20.0,
            max_concurrent_positions=1,
            volatility_threshold=80.0,
            min_trade_size_usd=10.0,
            max_trade_size_usd=25.0
        ),
        "SAVER": RiskLimits(
            tier_name="SAVER",
            max_position_size_pct=10.0,
            max_daily_loss_pct=8.0,
            max_drawdown_pct=15.0,
            max_concurrent_positions=1,
            volatility_threshold=75.0,
            min_trade_size_usd=10.0,
            max_trade_size_usd=40.0
        ),
        "INVESTOR": RiskLimits(
            tier_name="INVESTOR",
            max_position_size_pct=7.0,
            max_daily_loss_pct=10.0,
            max_drawdown_pct=20.0,
            max_concurrent_positions=3,
            volatility_threshold=80.0,
            min_trade_size_usd=20.0,
            max_trade_size_usd=75.0
        ),
        "INCOME": RiskLimits(
            tier_name="INCOME",
            max_position_size_pct=5.0,
            max_daily_loss_pct=12.0,
            max_drawdown_pct=25.0,
            max_concurrent_positions=5,
            volatility_threshold=85.0,
            min_trade_size_usd=30.0,
            max_trade_size_usd=150.0
        ),
        "LIVABLE": RiskLimits(
            tier_name="LIVABLE",
            max_position_size_pct=4.0,
            max_daily_loss_pct=15.0,
            max_drawdown_pct=30.0,
            max_concurrent_positions=8,
            volatility_threshold=90.0,
            min_trade_size_usd=50.0,
            max_trade_size_usd=500.0
        ),
        "BALLER": RiskLimits(
            tier_name="BALLER",
            max_position_size_pct=3.0,
            max_daily_loss_pct=20.0,
            max_drawdown_pct=35.0,
            max_concurrent_positions=15,
            volatility_threshold=95.0,
            min_trade_size_usd=100.0,
            max_trade_size_usd=5000.0
        )
    }

    def __init__(
        self,
        user_tier: str,
        total_capital: float,
        peak_capital: Optional[float] = None
    ):
        """
        Initialize tiered risk engine.

        Args:
            user_tier: User's subscription tier
            total_capital: Current total capital
            peak_capital: All-time peak capital (for drawdown calculation)
        """
        self.user_tier = user_tier.upper()
        self.total_capital = total_capital
        self.peak_capital = peak_capital or total_capital

        # Get tier-specific risk limits
        self.limits = self.TIER_RISK_LIMITS.get(
            self.user_tier,
            self.TIER_RISK_LIMITS["SAVER"]  # Default to SAVER if unknown tier
        )

        # Daily tracking
        self.daily_pnl = 0.0
        self.daily_reset_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Kill switch state
        self.kill_switch_active = False
        self.kill_switch_reason = None

        logger.info(f"TieredRiskEngine initialized: tier={self.user_tier}, capital=${total_capital:.2f}")

    def validate_trade(
        self,
        trade_size: float,
        current_positions: int,
        market_volatility: float,
        asset_class: str = "crypto"
    ) -> Tuple[bool, RiskLevel, str]:
        """
        Validate a trade through all risk gates.

        Args:
            trade_size: Proposed trade size in USD
            current_positions: Number of currently open positions
            market_volatility: Current market volatility (0-100 scale)
            asset_class: Asset class being traded

        Returns:
            Tuple of (approved, risk_level, message)
        """
        # Reset daily tracking if needed
        self._check_daily_reset()

        # Gate 0: Kill switch check
        if self.kill_switch_active:
            return (False, RiskLevel.CRITICAL, f"Kill switch active: {self.kill_switch_reason}")

        # Gate 1: Capital Guard
        capital_ok, capital_msg = self._check_capital_guard(trade_size, current_positions)
        if not capital_ok:
            return (False, RiskLevel.DANGER, capital_msg)

        # Gate 2: Drawdown Guard
        drawdown_ok, drawdown_msg = self._check_drawdown_guard()
        if not drawdown_ok:
            return (False, RiskLevel.DANGER, drawdown_msg)

        # Gate 3: Volatility Guard
        volatility_ok, volatility_msg = self._check_volatility_guard(market_volatility)
        if not volatility_ok:
            return (False, RiskLevel.WARNING, volatility_msg)

        # Gate 4: Execution Gate (final validation)
        execution_ok, execution_msg = self._check_execution_gate(trade_size)
        if not execution_ok:
            return (False, RiskLevel.DANGER, execution_msg)

        # All gates passed
        return (True, RiskLevel.SAFE, "Trade approved by all risk gates")

    def _check_capital_guard(
        self,
        trade_size: float,
        current_positions: int
    ) -> Tuple[bool, str]:
        """
        Gate 1: Capital Guard

        Validates:
        - Trade size within tier limits
        - Position size % of capital
        - Maximum concurrent positions
        """
        # Check minimum trade size
        if trade_size < self.limits.min_trade_size_usd:
            return (False, f"Trade size ${trade_size:.2f} below minimum ${self.limits.min_trade_size_usd:.2f}")

        # Check maximum trade size
        if trade_size > self.limits.max_trade_size_usd:
            return (False, f"Trade size ${trade_size:.2f} exceeds maximum ${self.limits.max_trade_size_usd:.2f}")

        # Check position size as % of capital
        position_pct = (trade_size / self.total_capital) * 100.0
        if position_pct > self.limits.max_position_size_pct:
            return (False, f"Position size {position_pct:.1f}% exceeds limit {self.limits.max_position_size_pct:.1f}%")

        # Check concurrent positions
        if current_positions >= self.limits.max_concurrent_positions:
            return (False, f"At max positions ({current_positions}/{self.limits.max_concurrent_positions})")

        return (True, "Capital guard passed")

    def _check_drawdown_guard(self) -> Tuple[bool, str]:
        """
        Gate 2: Drawdown Guard

        Validates:
        - Daily loss limits
        - Overall drawdown from peak
        """
        # Check daily loss
        if self.daily_pnl < 0:
            daily_loss_pct = abs(self.daily_pnl / self.total_capital) * 100.0
            if daily_loss_pct >= self.limits.max_daily_loss_pct:
                # Activate kill switch for today
                self.activate_kill_switch(f"Daily loss limit reached: {daily_loss_pct:.1f}%")
                return (False, f"Daily loss limit reached: {daily_loss_pct:.1f}%")

        # Check overall drawdown
        if self.total_capital < self.peak_capital:
            drawdown_pct = ((self.peak_capital - self.total_capital) / self.peak_capital) * 100.0
            if drawdown_pct >= self.limits.max_drawdown_pct:
                self.activate_kill_switch(f"Maximum drawdown reached: {drawdown_pct:.1f}%")
                return (False, f"Maximum drawdown reached: {drawdown_pct:.1f}%")

        return (True, "Drawdown guard passed")

    def _check_volatility_guard(self, market_volatility: float) -> Tuple[bool, str]:
        """
        Gate 3: Volatility Guard

        Validates:
        - Market volatility within acceptable range
        - Black swan detection
        """
        if market_volatility > self.limits.volatility_threshold:
            return (False, f"Market volatility {market_volatility:.1f} exceeds threshold {self.limits.volatility_threshold:.1f}")

        # Black swan detection (volatility > 95 for any tier)
        if market_volatility > 95.0:
            self.activate_kill_switch(f"Black swan event detected: volatility {market_volatility:.1f}")
            return (False, "Black swan event - all trading halted")

        return (True, "Volatility guard passed")

    def _check_execution_gate(self, trade_size: float) -> Tuple[bool, str]:
        """
        Gate 4: Execution Gate

        Final validation before trade execution.
        """
        # Ensure we have enough capital
        if trade_size > self.total_capital:
            return (False, f"Insufficient capital: need ${trade_size:.2f}, have ${self.total_capital:.2f}")

        return (True, "Execution gate passed")

    def update_daily_pnl(self, pnl: float):
        """Update daily P&L tracking."""
        self._check_daily_reset()
        self.daily_pnl += pnl
        logger.info(f"Daily P&L updated: ${self.daily_pnl:.2f}")

    def update_capital(self, new_capital: float):
        """
        Update capital and track peak.

        Args:
            new_capital: New total capital
        """
        self.total_capital = new_capital
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital
            logger.info(f"New peak capital: ${self.peak_capital:.2f}")

    def activate_kill_switch(self, reason: str):
        """
        Activate kill switch - stops all trading.

        Args:
            reason: Reason for activation
        """
        self.kill_switch_active = True
        self.kill_switch_reason = reason
        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        """Deactivate kill switch - resumes trading."""
        self.kill_switch_active = False
        self.kill_switch_reason = None
        logger.info("Kill switch deactivated - trading resumed")

    def _check_daily_reset(self):
        """Reset daily tracking at midnight."""
        now = datetime.now()
        reset_time = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if now.date() > self.daily_reset_time.date():
            logger.info(f"Daily reset: previous P&L was ${self.daily_pnl:.2f}")
            self.daily_pnl = 0.0
            self.daily_reset_time = reset_time

            # Auto-deactivate kill switch on daily reset (unless it's a drawdown issue)
            if self.kill_switch_active and "drawdown" not in self.kill_switch_reason.lower():
                self.deactivate_kill_switch()

    def get_available_capital(self, current_positions_value: float = 0.0) -> float:
        """
        Calculate available capital for new positions.

        Args:
            current_positions_value: Total value of currently open positions

        Returns:
            Available capital for new trades
        """
        return max(0.0, self.total_capital - current_positions_value)

    def get_risk_status(self) -> Dict:
        """
        Get current risk status summary.

        Returns:
            Dictionary with risk metrics
        """
        drawdown_pct = ((self.peak_capital - self.total_capital) / self.peak_capital) * 100.0 if self.peak_capital > 0 else 0.0
        daily_loss_pct = (abs(self.daily_pnl) / self.total_capital) * 100.0 if self.total_capital > 0 and self.daily_pnl < 0 else 0.0

        return {
            "tier": self.user_tier,
            "total_capital": self.total_capital,
            "peak_capital": self.peak_capital,
            "drawdown_pct": drawdown_pct,
            "daily_pnl": self.daily_pnl,
            "daily_loss_pct": daily_loss_pct,
            "kill_switch_active": self.kill_switch_active,
            "kill_switch_reason": self.kill_switch_reason,
            "limits": {
                "max_position_pct": self.limits.max_position_size_pct,
                "max_daily_loss_pct": self.limits.max_daily_loss_pct,
                "max_drawdown_pct": self.limits.max_drawdown_pct,
                "max_positions": self.limits.max_concurrent_positions,
                "volatility_threshold": self.limits.volatility_threshold
            }
        }
