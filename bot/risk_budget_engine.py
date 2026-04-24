"""
NIJA Risk Budget Engine
=======================

Calculates position sizes using a risk-first approach:

    risk_per_trade  = account_balance * risk_pct
    stop_distance   = |entry_price - stop_price| / entry_price
    position_size   = risk_per_trade / stop_distance

The result is then clamped to the tightest constraint among:
    - exchange_minimum  (broker minimum order value)
    - tier_floor        (account-tier minimum position)
    - min_position      (absolute floor from config)
    - max_position_cap  (maximum single-position exposure)

Advanced (Institutional) Layer
-------------------------------
Dynamic risk scaling based on recent performance (last N trades):

    Win rate > 65%   →  risk_per_trade bumped to 1.25 %
    Losing streak    →  risk_per_trade reduced to 0.50 %
    Otherwise        →  risk_per_trade stays at baseline (1.00 %)

This protects capital automatically and lets winners compound.

Author : NIJA Trading Systems
Version: 1.0
Date   : March 2026
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.risk_budget_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_RISK_PCT: float = 0.01    # 1.00 % baseline risk per trade
WINNING_RISK_PCT: float = 0.0125       # 1.25 % when win rate > WIN_RATE_THRESHOLD
LOSING_RISK_PCT: float = 0.005         # 0.50 % when a losing streak is detected

WIN_RATE_THRESHOLD: float = 0.65       # 65 % win rate triggers upward scaling
LOSING_STREAK_THRESHOLD: int = 3       # 3+ consecutive losses = losing streak
LOOKBACK_TRADES: int = 10              # Number of recent trades for performance check

SAFETY_CLAMP_PCT: float = 0.25        # Hard ceiling: position_size ≤ 25% of account_balance

# Trade outcome sentinels – use these instead of bare strings.
OUTCOME_WIN: str = "win"
OUTCOME_LOSS: str = "loss"


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """Represents the outcome of a single completed trade."""

    outcome: str    # OUTCOME_WIN or OUTCOME_LOSS
    pnl: float = 0.0  # Realised profit/loss in USD (positive = profit)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RiskBudgetConfig:
    """Configuration for the Risk Budget Engine."""

    # Baseline risk fraction (1 % of account per trade)
    base_risk_pct: float = DEFAULT_BASE_RISK_PCT

    # Performance-scaled risk fractions
    winning_risk_pct: float = WINNING_RISK_PCT
    losing_risk_pct: float = LOSING_RISK_PCT

    # Performance detection settings
    win_rate_threshold: float = WIN_RATE_THRESHOLD
    losing_streak_threshold: int = LOSING_STREAK_THRESHOLD
    lookback_trades: int = LOOKBACK_TRADES

    # Position-size constraints (all in USD unless noted)
    min_position: float = 1.0          # Absolute minimum position value ($)
    tier_floor: float = 5.0            # Account-tier minimum position value ($)
    exchange_minimum: float = 2.0      # Exchange minimum order value ($)
    max_position_cap: float = 10_000.0  # Maximum single-position exposure ($)

    # Safety clamp: position_size must not exceed this fraction of account_balance
    balance_safety_clamp_pct: float = SAFETY_CLAMP_PCT  # 25% hard ceiling

    # Dynamic scaling toggle
    enable_dynamic_scaling: bool = True


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class RiskBudgetEngine:
    """
    Computes risk-adjusted position sizes for every trade.

    Usage
    -----
    engine = RiskBudgetEngine()
    result = engine.calculate_position_size(
        account_balance=5000.0,
        entry_price=100.0,
        stop_price=95.0,
    )
    print(result['position_size_usd'])  # e.g. $95.24
    """

    def __init__(self, config: Optional[RiskBudgetConfig] = None) -> None:
        self.config = config or RiskBudgetConfig()
        self.trade_history: List[TradeRecord] = []

        logger.info("=" * 65)
        logger.info("💰 Risk Budget Engine Initialized")
        logger.info("=" * 65)
        logger.info(f"  Baseline risk       : {self.config.base_risk_pct:.2%}")
        logger.info(f"  Winning risk        : {self.config.winning_risk_pct:.2%}")
        logger.info(f"  Losing risk         : {self.config.losing_risk_pct:.2%}")
        logger.info(f"  Win-rate threshold  : {self.config.win_rate_threshold:.0%}")
        logger.info(f"  Losing streak limit : {self.config.losing_streak_threshold} trades")
        logger.info(f"  Position floor      : ${self.config.min_position:.2f}")
        logger.info(f"  Tier floor          : ${self.config.tier_floor:.2f}")
        logger.info(f"  Exchange minimum    : ${self.config.exchange_minimum:.2f}")
        logger.info(f"  Max position cap    : ${self.config.max_position_cap:,.2f}")
        logger.info(f"  Safety clamp        : {self.config.balance_safety_clamp_pct:.0%} of account balance")
        logger.info(f"  Dynamic scaling     : {'ON' if self.config.enable_dynamic_scaling else 'OFF'}")
        logger.info("=" * 65)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_price: float,
        *,
        override_risk_pct: Optional[float] = None,
    ) -> Dict:
        """
        Calculate the position size using the risk-budget formula.

        Parameters
        ----------
        account_balance : float
            Total usable account balance in USD.
        entry_price : float
            Planned entry price for the trade.
        stop_price : float
            Stop-loss price for the trade.
        override_risk_pct : float, optional
            Force a specific risk fraction (bypasses dynamic scaling).

        Returns
        -------
        dict with keys:
            position_size_usd   – final clamped position size
            risk_per_trade_usd  – dollar amount being risked
            stop_distance_pct   – stop distance as a fraction of entry
            risk_pct_used       – effective risk fraction applied
            scaling_reason      – why this risk % was chosen
            clamped             – True if the size was clamped
            clamp_reason        – which constraint triggered clamping
            valid               – False if inputs are invalid
            error               – error message when valid is False
        """
        result: Dict = {
            "position_size_usd": 0.0,
            "risk_per_trade_usd": 0.0,
            "stop_distance_pct": 0.0,
            "risk_pct_used": 0.0,
            "scaling_reason": "baseline",
            "clamped": False,
            "clamp_reason": "",
            "valid": False,
            "error": "",
        }

        # --- input validation ---
        if account_balance <= 0:
            result["error"] = f"Invalid account_balance: {account_balance}"
            logger.error("❌ %s", result["error"])
            return result

        if entry_price <= 0:
            result["error"] = f"Invalid entry_price: {entry_price}"
            logger.error("❌ %s", result["error"])
            return result

        if stop_price <= 0:
            result["error"] = f"Invalid stop_price: {stop_price}"
            logger.error("❌ %s", result["error"])
            return result

        if stop_price == entry_price:
            result["error"] = "stop_price must differ from entry_price"
            logger.error("❌ %s", result["error"])
            return result

        # --- determine effective risk % ---
        if override_risk_pct is not None:
            risk_pct = override_risk_pct
            scaling_reason = "override"
        elif self.config.enable_dynamic_scaling:
            risk_pct, scaling_reason = self._dynamic_risk_pct()
        else:
            risk_pct = self.config.base_risk_pct
            scaling_reason = "baseline"

        # --- core formula ---
        risk_per_trade = account_balance * risk_pct
        stop_distance = abs(entry_price - stop_price) / entry_price

        if stop_distance == 0:
            result["error"] = "Computed stop_distance is zero; check prices"
            logger.error("❌ %s", result["error"])
            return result

        raw_position_size = risk_per_trade / stop_distance

        # --- safety clamp: position_size ≤ account_balance * 25% ---
        safety_cap = account_balance * self.config.balance_safety_clamp_pct
        if raw_position_size > safety_cap:
            logger.info(
                "🔒 SAFETY CLAMP: raw=$%.2f → capped=$%.2f (%.0f%% of $%.2f balance)",
                raw_position_size,
                safety_cap,
                self.config.balance_safety_clamp_pct * 100,
                account_balance,
            )
            raw_position_size = safety_cap

        # --- clamp ---
        clamped_size, clamped, clamp_reason = self._clamp_position(raw_position_size)

        result.update(
            {
                "position_size_usd": round(clamped_size, 2),
                "risk_per_trade_usd": round(risk_per_trade, 2),
                "stop_distance_pct": round(stop_distance, 6),
                "risk_pct_used": risk_pct,
                "scaling_reason": scaling_reason,
                "clamped": clamped,
                "clamp_reason": clamp_reason,
                "valid": True,
            }
        )

        logger.info(
            "📐 RiskBudget | balance=$%.2f | risk_pct=%.2f%% | stop_dist=%.3f%% "
            "| raw=$%.2f → final=$%.2f | %s",
            account_balance,
            risk_pct * 100,
            stop_distance * 100,
            raw_position_size,
            clamped_size,
            f"CLAMPED ({clamp_reason})" if clamped else "OK",
        )
        return result

    def record_trade_outcome(self, outcome: str, pnl: float = 0.0) -> None:
        """
        Record a completed trade outcome for dynamic scaling.

        Parameters
        ----------
        outcome : str
            ``OUTCOME_WIN`` or ``OUTCOME_LOSS``
        pnl : float
            Realised profit/loss in USD (positive = profit).
        """
        if outcome not in (OUTCOME_WIN, OUTCOME_LOSS):
            raise ValueError(f"outcome must be {OUTCOME_WIN!r} or {OUTCOME_LOSS!r}, got: {outcome!r}")

        self.trade_history.append(TradeRecord(outcome=outcome, pnl=pnl))
        logger.debug("📝 Trade recorded: %s | P&L $%.2f", outcome, pnl)

    def get_performance_summary(self) -> Dict:
        """
        Return a summary of recent performance used by dynamic scaling.

        Returns
        -------
        dict with:
            lookback          – number of trades inspected
            win_rate          – fraction of wins
            losing_streak     – current consecutive-loss count
            risk_pct          – effective risk % that would be applied
            scaling_reason    – reason for that risk %
        """
        recent = self._recent_trades()
        win_rate = self._win_rate(recent)
        losing_streak = self._current_losing_streak()
        risk_pct, scaling_reason = self._dynamic_risk_pct()

        return {
            "lookback": len(recent),
            "win_rate": round(win_rate, 4),
            "losing_streak": losing_streak,
            "risk_pct": risk_pct,
            "scaling_reason": scaling_reason,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dynamic_risk_pct(self) -> tuple:
        """
        Return (risk_pct, reason) based on recent trade history.

        Priority order:
        1. Losing streak  → conservative
        2. High win rate  → aggressive
        3. Default        → baseline
        """
        recent = self._recent_trades()

        # Losing streak check takes priority (capital protection)
        losing_streak = self._current_losing_streak()
        if losing_streak >= self.config.losing_streak_threshold:
            logger.debug(
                "📉 Losing streak (%d) ≥ threshold (%d) → risk %.2f%%",
                losing_streak,
                self.config.losing_streak_threshold,
                self.config.losing_risk_pct * 100,
            )
            return self.config.losing_risk_pct, f"losing_streak_{losing_streak}"

        # Win-rate check
        if len(recent) >= self.config.lookback_trades:
            win_rate = self._win_rate(recent)
            if win_rate > self.config.win_rate_threshold:
                logger.debug(
                    "📈 Win rate %.1f%% > threshold %.1f%% → risk %.2f%%",
                    win_rate * 100,
                    self.config.win_rate_threshold * 100,
                    self.config.winning_risk_pct * 100,
                )
                return self.config.winning_risk_pct, f"high_win_rate_{win_rate:.2%}"

        return self.config.base_risk_pct, "baseline"

    def _recent_trades(self) -> List[TradeRecord]:
        """Return the most recent N trades from history."""
        return self.trade_history[-self.config.lookback_trades :]

    def _win_rate(self, trades: List[TradeRecord]) -> float:
        """Compute win rate for a list of trade records."""
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.outcome == OUTCOME_WIN)
        return wins / len(trades)

    def _current_losing_streak(self) -> int:
        """Count consecutive losses at the tail of the trade history."""
        streak = 0
        for trade in reversed(self.trade_history):
            if trade.outcome == OUTCOME_LOSS:
                streak += 1
            else:
                break
        return streak

    def _clamp_position(self, raw_size: float) -> tuple:
        """
        Apply floor and cap constraints to the raw position size.

        Returns
        -------
        (clamped_size, was_clamped, reason)
        """
        cfg = self.config
        # Use max() because we must satisfy ALL three minimums simultaneously;
        # the tightest (highest) constraint wins.
        floor = max(cfg.min_position, cfg.tier_floor, cfg.exchange_minimum)
        cap = cfg.max_position_cap

        if raw_size < floor:
            return floor, True, f"floor=${floor:.2f}"

        if raw_size > cap:
            return cap, True, f"cap=${cap:,.2f}"

        return raw_size, False, ""


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def calculate_risk_position(
    account_balance: float,
    entry_price: float,
    stop_price: float,
    config: Optional[RiskBudgetConfig] = None,
) -> Dict:
    """
    Stateless convenience wrapper around :class:`RiskBudgetEngine`.

    Useful for one-off calculations where a persistent engine instance
    is not needed (e.g., backtesting pipelines).

    Parameters
    ----------
    account_balance : float
        Total usable account balance in USD.
    entry_price : float
        Planned entry price.
    stop_price : float
        Stop-loss price.
    config : RiskBudgetConfig, optional
        Custom configuration; uses defaults when omitted.

    Returns
    -------
    dict – same structure as :meth:`RiskBudgetEngine.calculate_position_size`
    """
    engine = RiskBudgetEngine(config)
    return engine.calculate_position_size(account_balance, entry_price, stop_price)
