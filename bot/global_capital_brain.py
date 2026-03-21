"""
NIJA Global Capital Brain
==========================

The final top-level decision layer that unifies every capital-routing
concern into one strict four-layer pipeline executed before each trade:

    ┌──────────────────────────────────────────────────────────────────┐
    │          CAPITAL BRAIN — DECISION HIERARCHY                      │
    │                                                                  │
    │  Layer 1 — GLOBAL   : Is this the best account right now?        │
    │  Layer 2 — ACCOUNT  : Is this account healthy enough to trade?   │
    │  Layer 3 — STRATEGY : Did the strategy gate approve this signal? │
    │  Layer 4 — TRADE    : How much capital to deploy? (snowball)     │
    │                                                                  │
    │  Single call: brain.run_hierarchy_check(...)                     │
    │  Single result: HierarchyDecision                                │
    └──────────────────────────────────────────────────────────────────┘

The pipeline short-circuits at the first failed layer so Capital never
flows into a bad account, a bad condition, or a bad signal.  When all
four layers pass, the brain also hands back the final (snowball-adjusted)
position size so the caller never has to apply multipliers separately.

Four interrelated subsystems
-----------------------------

  1. Global Capital Routing
     Before any entry: ``best_account = brain.get_preferred_account(all_accounts)``
     If ``current_account != best_account`` the trade is skipped so capital
     naturally concentrates in the highest-performing account.

  2. Capital Efficiency Score
     A single composite score per account that drives all ranking decisions::

         score = (win_rate      × 0.30)
               + (profit_factor × 0.30)
               + (sharpe        × 0.20)
               + (drawdown_ok   × 0.20)

     All four sub-metrics are normalised to [0, 1] before weighting so the
     score is always in [0, 1] and directly comparable across accounts.

  3. Smarter Reallocation Trigger
     Underperforming accounts are flagged for capital reallocation even before
     the kill-weak-accounts circuit breaker fires::

         IF account_rank < top 30%
         AND underperforming for ≥ 10 consecutive trades
             → recommend moving 25–50 % of capital out

  4. Capital Snowball Mode
     When an account is on a winning streak the brain returns a position-size
     multiplier that compounds winners faster::

         win_streak ≥ 3 → multiplier = 1.5×
         win_streak ≥ 5 → multiplier = 2.0×

Architecture
------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │                      GlobalCapitalBrain                             │
    │                                                                     │
    │  record_trade(account_id, pnl_usd, is_win,                         │
    │               profit_factor=None, sharpe=None, drawdown_pct=None)  │
    │    → updates per-account rolling stats & win streak                │
    │                                                                     │
    │  get_efficiency_score(account_id) → float [0, 1]                   │
    │    → composite score used for ranking and routing                  │
    │                                                                     │
    │  get_ranked_accounts() → List[BrainAccountRank]                    │
    │    → all accounts sorted by efficiency score (best first)          │
    │                                                                     │
    │  get_preferred_account(candidates) → str                           │
    │    → highest-efficiency account_id from the list                   │
    │                                                                     │
    │  should_trade(current_account_id, all_accounts) → (bool, str)      │
    │    → False + reason when current account is not the top performer  │
    │                                                                     │
    │  get_snowball_multiplier(account_id) → float                       │
    │    → 1.0 / 1.5× / 2.0× based on win streak                        │
    │                                                                     │
    │  check_reallocation(account_id, all_accounts)                      │
    │         → Optional[ReallocationDecision]                           │
    │    → non-None when 25–50 % of capital should move out              │
    │                                                                     │
    │  run_hierarchy_check(current_account_id, all_accounts,             │
    │                       is_account_alive, strategy_approved,         │
    │                       base_position_size) → HierarchyDecision      │
    │    → THE unified entry point: runs all 4 layers in order,          │
    │      short-circuits on first failure, returns a HierarchyDecision  │
    │      with per-layer traceability and the final position size.       │
    │                                                                     │
    │  get_report() → dict                                               │
    │    → full snapshot for dashboards / logging                         │
    └─────────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.global_capital_brain import get_global_capital_brain

    brain = get_global_capital_brain()

    # After every closed trade:
    brain.record_trade("coinbase", pnl_usd=42.0, is_win=True,
                       profit_factor=2.1, sharpe=1.4, drawdown_pct=3.5)

    # ── Unified hierarchy check before every new entry ─────────────────
    # Collect layer inputs from the engines that own them:
    is_alive   = account_flow_layer.is_account_tradeable("coinbase")
    strat_ok   = win_rate_maximizer.approve_trade(...)  # already ran above

    decision = brain.run_hierarchy_check(
        current_account_id="coinbase",
        all_accounts=["coinbase", "kraken"],
        is_account_alive=is_alive,
        strategy_approved=strat_ok,
        base_position_size=500.0,
    )

    if not decision.approved:
        logger.info("BLOCKED [%s] — %s", decision.blocked_at, decision.rejection_reason)
        continue

    # decision.final_position_size already has the snowball multiplier applied
    place_order(size_usd=decision.final_position_size)

    # Check whether reallocation is warranted for a stagnant account:
    reco = brain.check_reallocation("coinbase", ["coinbase", "kraken"],
                                    balance_usd=10_000.0)
    if reco:
        logger.warning("Reallocation recommended: %s", reco)

Author: NIJA Trading Systems
Version: 2.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.global_capital_brain")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Efficiency score weights (must sum to 1.0)
WEIGHT_WIN_RATE: float = 0.30
WEIGHT_PROFIT_FACTOR: float = 0.30
WEIGHT_SHARPE: float = 0.20
WEIGHT_DRAWDOWN_OK: float = 0.20

# Rolling window for win-rate calculation
WIN_RATE_WINDOW: int = 20

# EMA smoothing alpha for profit-factor and Sharpe updates
EMA_ALPHA: float = 0.20

# Number of consecutive underperforming trades required for reallocation
UNDERPERFORM_TRADE_THRESHOLD: int = 10

# Reallocation fractions — scaled linearly between these bounds based on rank
REALLOC_FRACTION_MIN: float = 0.25   # 25 % when barely outside top 30 %
REALLOC_FRACTION_MAX: float = 0.50   # 50 % for the worst-ranked accounts

# Win-streak thresholds for Capital Snowball Mode
SNOWBALL_STREAK_LOW: int = 3
SNOWBALL_STREAK_HIGH: int = 5
SNOWBALL_MULT_LOW: float = 1.5
SNOWBALL_MULT_HIGH: float = 2.0

# Minimum trades before routing / snowball decisions are enforced
MIN_TRADES_FOR_ROUTING: int = 5

# Normalisation cap for profit factor (values above this are treated as 1.0)
PROFIT_FACTOR_CAP: float = 4.0

# Normalisation cap for Sharpe (maps [-cap, +cap] → [0, 1])
SHARPE_CAP: float = 3.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ReallocationDecision:
    """Recommendation to move a fraction of capital out of an account."""
    account_id: str
    fraction: float          # 0.25 – 0.50
    amount_usd: float        # fraction × current_balance
    reason: str
    recommended_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "fraction": round(self.fraction, 4),
            "amount_usd": round(self.amount_usd, 4),
            "reason": self.reason,
            "recommended_at": self.recommended_at,
        }


@dataclass
class LayerResult:
    """
    Outcome of a single layer inside the Capital Brain decision hierarchy.

    Attributes:
        layer:       Human-readable layer name, e.g. ``"global"``.
        approved:    ``True`` when this layer allowed the trade to proceed.
        reason:      Short explanation (populated on rejection, empty on pass).
        multiplier:  Position-size multiplier contributed by this layer
                     (1.0 for gate-only layers, > 1 for the trade/snowball layer).
    """
    layer: str
    approved: bool
    reason: str = ""
    multiplier: float = 1.0

    def to_dict(self) -> Dict:
        return {
            "layer": self.layer,
            "approved": self.approved,
            "reason": self.reason,
            "multiplier": round(self.multiplier, 4),
        }


@dataclass
class HierarchyDecision:
    """
    Result of a full Capital Brain hierarchy check.

    The four layers are evaluated in strict order:
    ``global → account → strategy → trade``.  The pipeline short-circuits
    at the first failure so ``approved`` is ``True`` only when all four
    layers pass.

    Attributes:
        approved:             ``True`` when all layers passed.
        blocked_at:           Name of the layer that blocked the trade, or
                              ``None`` when approved.
        rejection_reason:     Human-readable reason from the blocking layer.
        final_position_size:  Base size × snowball multiplier.  Meaningful
                              only when ``approved`` is ``True``.
        snowball_multiplier:  The Trade-layer multiplier that was applied
                              (1.0 / 1.5× / 2.0×).
        win_streak:           Current win streak of the evaluated account.
        layers:               Per-layer :class:`LayerResult` list (always
                              four entries, in pipeline order).
        account_id:           Account that was evaluated.
        evaluated_at:         ISO-8601 timestamp.
    """
    approved: bool
    blocked_at: Optional[str]
    rejection_reason: str
    final_position_size: float
    snowball_multiplier: float
    win_streak: int
    layers: List[LayerResult]
    account_id: str
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        return {
            "approved": self.approved,
            "blocked_at": self.blocked_at,
            "rejection_reason": self.rejection_reason,
            "final_position_size": round(self.final_position_size, 4),
            "snowball_multiplier": round(self.snowball_multiplier, 4),
            "win_streak": self.win_streak,
            "layers": [lr.to_dict() for lr in self.layers],
            "account_id": self.account_id,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class BrainAccountRank:
    """Ranked entry returned by ``get_ranked_accounts``."""
    rank: int
    account_id: str
    efficiency_score: float
    win_rate_pct: float
    profit_factor: float
    sharpe: float
    drawdown_pct: float
    win_streak: int
    snowball_multiplier: float
    mode: str                # "SNOWBALL 🚀" | "NORMAL" | "STAGNANT ⚠️"
    total_trades: int

    def to_dict(self) -> Dict:
        return {
            "rank": self.rank,
            "account_id": self.account_id,
            "efficiency_score": round(self.efficiency_score, 4),
            "win_rate_pct": round(self.win_rate_pct, 2),
            "profit_factor": round(self.profit_factor, 4),
            "sharpe": round(self.sharpe, 4),
            "drawdown_pct": round(self.drawdown_pct, 2),
            "win_streak": self.win_streak,
            "snowball_multiplier": round(self.snowball_multiplier, 4),
            "mode": self.mode,
            "total_trades": self.total_trades,
        }


# ---------------------------------------------------------------------------
# Per-account internal state
# ---------------------------------------------------------------------------

class _BrainAccountState:
    """Rolling statistics tracked per account by the Global Capital Brain."""

    def __init__(self, account_id: str) -> None:
        self.account_id: str = account_id

        # Rolling win-rate window
        self._win_window: Deque[bool] = deque(maxlen=WIN_RATE_WINDOW)

        # EMA-smoothed profit factor and Sharpe ratio
        self._ema_profit_factor: float = 1.0
        self._ema_sharpe: float = 0.0

        # Drawdown (refreshed by update_equity or record_trade)
        self.drawdown_pct: float = 0.0
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0

        # Winning / losing streak counters
        self.win_streak: int = 0
        self.lose_streak: int = 0

        # Consecutive underperforming (negative P&L) trade count
        # Resets on any positive P&L trade
        self.consecutive_underperforming: int = 0

        # Total trades recorded
        self.total_trades: int = 0

        # Cached efficiency score (updated on every record_trade / update_equity)
        self.efficiency_score: float = 0.5   # neutral default

    # ── Rolling metrics ──────────────────────────────────────────────────

    @property
    def rolling_win_rate(self) -> float:
        if not self._win_window:
            return 0.0
        return sum(self._win_window) / len(self._win_window)

    @property
    def ema_profit_factor(self) -> float:
        return self._ema_profit_factor

    @property
    def ema_sharpe(self) -> float:
        return self._ema_sharpe

    # ── Update helpers ───────────────────────────────────────────────────

    def record_trade(
        self,
        pnl_usd: float,
        is_win: bool,
        profit_factor: Optional[float],
        sharpe: Optional[float],
        equity_usd: Optional[float],
    ) -> None:
        self.total_trades += 1
        self._win_window.append(is_win)

        # Win / lose streak bookkeeping
        if is_win:
            self.win_streak += 1
            self.lose_streak = 0
        else:
            self.lose_streak += 1
            self.win_streak = 0

        # Consecutive underperformance counter
        if pnl_usd < 0:
            self.consecutive_underperforming += 1
        else:
            self.consecutive_underperforming = 0

        # EMA-smooth profit factor if supplied
        if profit_factor is not None and profit_factor > 0:
            pf = min(profit_factor, PROFIT_FACTOR_CAP)
            self._ema_profit_factor = (
                EMA_ALPHA * pf + (1.0 - EMA_ALPHA) * self._ema_profit_factor
            )

        # EMA-smooth Sharpe if supplied
        if sharpe is not None and math.isfinite(sharpe):
            clamped = max(-SHARPE_CAP, min(sharpe, SHARPE_CAP))
            self._ema_sharpe = (
                EMA_ALPHA * clamped + (1.0 - EMA_ALPHA) * self._ema_sharpe
            )

        # Update drawdown if equity supplied
        if equity_usd is not None:
            self._refresh_equity(equity_usd)

    def update_equity(self, equity_usd: float) -> None:
        self._refresh_equity(equity_usd)

    def _refresh_equity(self, equity_usd: float) -> None:
        self._current_equity = equity_usd
        if equity_usd > self._peak_equity:
            self._peak_equity = equity_usd
        if self._peak_equity > 0:
            self.drawdown_pct = (
                (self._peak_equity - equity_usd) / self._peak_equity * 100.0
            )


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_profit_factor(pf: float) -> float:
    """Map profit_factor [0, cap] → [0, 1].  PF=1 → 0.25, PF=2 → 0.5."""
    if pf <= 0:
        return 0.0
    clamped = min(pf, PROFIT_FACTOR_CAP)
    return clamped / PROFIT_FACTOR_CAP


def _normalise_sharpe(sharpe: float) -> float:
    """Map Sharpe [-cap, +cap] → [0, 1].  Sharpe=0 → 0.5."""
    clamped = max(-SHARPE_CAP, min(sharpe, SHARPE_CAP))
    return (clamped + SHARPE_CAP) / (2.0 * SHARPE_CAP)


def _normalise_drawdown_ok(drawdown_pct: float) -> float:
    """Map drawdown [0, 100%] → drawdown_ok [1, 0].  0% DD → 1.0, 20% DD → 0.8."""
    return max(0.0, 1.0 - drawdown_pct / 100.0)


def _compute_efficiency_score(state: _BrainAccountState) -> float:
    """Compute the composite Capital Efficiency Score for *state*."""
    win_rate_norm = state.rolling_win_rate                        # already [0,1]
    pf_norm = _normalise_profit_factor(state.ema_profit_factor)
    sharpe_norm = _normalise_sharpe(state.ema_sharpe)
    dd_ok = _normalise_drawdown_ok(state.drawdown_pct)

    score = (
        win_rate_norm * WEIGHT_WIN_RATE
        + pf_norm * WEIGHT_PROFIT_FACTOR
        + sharpe_norm * WEIGHT_SHARPE
        + dd_ok * WEIGHT_DRAWDOWN_OK
    )
    return round(min(max(score, 0.0), 1.0), 6)


def _snowball_multiplier(win_streak: int) -> float:
    """Return the Capital Snowball Mode position-size multiplier."""
    if win_streak >= SNOWBALL_STREAK_HIGH:
        return SNOWBALL_MULT_HIGH
    if win_streak >= SNOWBALL_STREAK_LOW:
        return SNOWBALL_MULT_LOW
    return 1.0


# ---------------------------------------------------------------------------
# GlobalCapitalBrain
# ---------------------------------------------------------------------------

class GlobalCapitalBrain:
    """
    Top-level decision layer that routes capital to the best account,
    calculates composite efficiency scores, detects reallocation needs,
    and boosts position sizes for hot accounts via Capital Snowball Mode.
    """

    def __init__(self) -> None:
        self._accounts: Dict[str, _BrainAccountState] = {}
        self._lock = threading.Lock()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_or_create(self, account_id: str) -> _BrainAccountState:
        """Return (or lazily create) the per-account state.  Call under lock."""
        if account_id not in self._accounts:
            self._accounts[account_id] = _BrainAccountState(account_id)
        return self._accounts[account_id]

    def _refresh_score(self, state: _BrainAccountState) -> None:
        """Recompute and cache the efficiency score.  Call under lock."""
        state.efficiency_score = _compute_efficiency_score(state)

    # ── Trade recording ───────────────────────────────────────────────────────

    def record_trade(
        self,
        account_id: str,
        pnl_usd: float,
        is_win: bool,
        profit_factor: Optional[float] = None,
        sharpe: Optional[float] = None,
        drawdown_pct: Optional[float] = None,
        equity_usd: Optional[float] = None,
    ) -> None:
        """
        Record a closed trade for *account_id* and update all brain metrics.

        Args:
            account_id:    Broker / account identifier (e.g. ``"coinbase"``).
            pnl_usd:       Net P&L of the closed trade in USD.
            is_win:        ``True`` if the trade was profitable.
            profit_factor: Current rolling profit factor (optional).
            sharpe:        Current rolling Sharpe ratio (optional).
            drawdown_pct:  Current drawdown from peak, percent (optional).
            equity_usd:    Current total account equity (optional).
        """
        with self._lock:
            state = self._get_or_create(account_id)

            # Use drawdown_pct shortcut if equity not supplied
            if drawdown_pct is not None and equity_usd is None:
                state.drawdown_pct = max(0.0, drawdown_pct)

            state.record_trade(
                pnl_usd=pnl_usd,
                is_win=is_win,
                profit_factor=profit_factor,
                sharpe=sharpe,
                equity_usd=equity_usd,
            )
            self._refresh_score(state)

        logger.debug(
            "[Brain] %s recorded pnl=%.2f win=%s streak=%d score=%.4f",
            account_id, pnl_usd, is_win, state.win_streak, state.efficiency_score,
        )

    def update_equity(self, account_id: str, equity_usd: float) -> None:
        """Refresh equity / drawdown for *account_id* without recording a trade."""
        with self._lock:
            state = self._get_or_create(account_id)
            state.update_equity(equity_usd)
            self._refresh_score(state)

    # ── Efficiency score ──────────────────────────────────────────────────────

    def get_efficiency_score(self, account_id: str) -> float:
        """
        Return the cached Capital Efficiency Score for *account_id*.

        Score is in ``[0, 1]`` — higher is better.  Returns ``0.5`` (neutral)
        when the account has no recorded trades yet.
        """
        with self._lock:
            state = self._accounts.get(account_id)
            return state.efficiency_score if state else 0.5

    # ── Account ranking ───────────────────────────────────────────────────────

    def get_ranked_accounts(self) -> List[BrainAccountRank]:
        """
        Return all accounts sorted by Capital Efficiency Score (best first).

        Each entry carries the full metric breakdown and the Snowball multiplier.
        """
        with self._lock:
            sorted_states = sorted(
                self._accounts.values(),
                key=lambda s: s.efficiency_score,
                reverse=True,
            )
            result: List[BrainAccountRank] = []
            for i, state in enumerate(sorted_states, start=1):
                mult = _snowball_multiplier(state.win_streak)
                if mult > 1.0:
                    mode = "SNOWBALL 🚀"
                elif state.consecutive_underperforming >= UNDERPERFORM_TRADE_THRESHOLD:
                    mode = "STAGNANT ⚠️"
                else:
                    mode = "NORMAL"
                result.append(BrainAccountRank(
                    rank=i,
                    account_id=state.account_id,
                    efficiency_score=state.efficiency_score,
                    win_rate_pct=round(state.rolling_win_rate * 100, 2),
                    profit_factor=round(state.ema_profit_factor, 4),
                    sharpe=round(state.ema_sharpe, 4),
                    drawdown_pct=round(state.drawdown_pct, 2),
                    win_streak=state.win_streak,
                    snowball_multiplier=mult,
                    mode=mode,
                    total_trades=state.total_trades,
                ))
            return result

    # ── Global Capital Routing (Feature 1) ───────────────────────────────────

    def get_preferred_account(self, candidates: List[str]) -> Optional[str]:
        """
        Return the highest-efficiency account_id from *candidates*.

        Uses the Capital Efficiency Score as the ranking criterion.  Falls back
        to ``candidates[0]`` when no data is available.

        Args:
            candidates: Account_ids to choose among.

        Returns:
            The preferred account_id, or ``None`` when *candidates* is empty.
        """
        if not candidates:
            return None

        ranked = self.get_ranked_accounts()

        # Return the first ranked account that is in the candidate list
        for entry in ranked:
            if entry.account_id in candidates:
                return entry.account_id

        # No ranked data yet — return first candidate unchanged
        return candidates[0]

    def should_trade(
        self,
        current_account_id: str,
        all_accounts: List[str],
    ) -> Tuple[bool, str]:
        """
        Decide whether *current_account_id* should execute a new trade.

        The trade is blocked when:

        1. Another account in *all_accounts* has a higher efficiency score
           **and** the current account has accumulated enough trade history
           to make the comparison meaningful (≥ ``MIN_TRADES_FOR_ROUTING``
           trades).

        Args:
            current_account_id: The account that wants to trade.
            all_accounts:       All known account_ids (including current).

        Returns:
            ``(True, "")`` when trading is allowed.
            ``(False, reason)`` when the trade should be skipped.
        """
        if not all_accounts or len(all_accounts) <= 1:
            return True, ""   # single account — always allowed

        with self._lock:
            current_state = self._accounts.get(current_account_id)

        # Not enough history to enforce routing — fail-open
        if (
            current_state is None
            or current_state.total_trades < MIN_TRADES_FOR_ROUTING
        ):
            return True, ""

        preferred = self.get_preferred_account(all_accounts)

        if preferred and preferred != current_account_id:
            current_score = self.get_efficiency_score(current_account_id)
            best_score = self.get_efficiency_score(preferred)
            reason = (
                f"CAPITAL ROUTING: account '{preferred}' efficiency={best_score:.3f} "
                f"> current '{current_account_id}' efficiency={current_score:.3f} — "
                f"concentrating capital in top performer"
            )
            logger.info("   🧠 [Brain] SKIP TRADE — %s", reason)
            return False, reason

        return True, ""

    # ── Capital Snowball Mode (Feature 4) ─────────────────────────────────────

    def get_snowball_multiplier(self, account_id: str) -> float:
        """
        Return the Capital Snowball Mode position-size multiplier.

        - win_streak ≥ 5 → ``2.0×``
        - win_streak ≥ 3 → ``1.5×``
        - otherwise      → ``1.0×``
        """
        with self._lock:
            state = self._accounts.get(account_id)
            if state is None:
                return 1.0
            mult = _snowball_multiplier(state.win_streak)

        if mult > 1.0:
            logger.debug(
                "[Brain] %s snowball multiplier %.1f× (streak=%d)",
                account_id, mult, state.win_streak,
            )
        return mult

    # ── Smarter Reallocation Trigger (Feature 3) ─────────────────────────────

    def check_reallocation(
        self,
        account_id: str,
        all_accounts: List[str],
        balance_usd: float = 0.0,
    ) -> Optional[ReallocationDecision]:
        """
        Check whether capital should be reallocated away from *account_id*.

        Returns a :class:`ReallocationDecision` when both conditions are met:

        - The account's rank is **outside** the top 30 % (by efficiency score).
        - It has been consecutively underperforming for ≥
          ``UNDERPERFORM_TRADE_THRESHOLD`` trades.

        The recommended fraction scales from 25 % (barely outside top 30 %)
        to 50 % (bottom of the ranking).

        Args:
            account_id:   Account to evaluate.
            all_accounts: All known account_ids for rank calculation.
            balance_usd:  Current account balance (used to compute USD amount).

        Returns:
            A :class:`ReallocationDecision` or ``None``.
        """
        ranked = self.get_ranked_accounts()
        n = len(ranked)
        if n < 2:
            return None   # nothing to compare against

        # Find the account's rank (1-based, lower is better)
        rank: Optional[int] = None
        for entry in ranked:
            if entry.account_id == account_id:
                rank = entry.rank
                break

        if rank is None:
            return None   # account not in ranked list — no data

        # Condition 1: outside top 30 %
        top_30_cutoff = max(1, math.ceil(n * 0.30))
        if rank <= top_30_cutoff:
            return None   # account is in the top tier — no reallocation

        # Condition 2: underperforming for the required number of trades
        with self._lock:
            state = self._accounts.get(account_id)
        if state is None:
            return None
        if state.consecutive_underperforming < UNDERPERFORM_TRADE_THRESHOLD:
            return None   # not yet underperforming long enough

        # Compute reallocation fraction — scales from min at rank = top_30_cutoff+1
        # to max at rank = n
        denominator = max(n - top_30_cutoff, 1)
        rank_fraction = (rank - top_30_cutoff) / denominator   # 0..1
        fraction = REALLOC_FRACTION_MIN + rank_fraction * (
            REALLOC_FRACTION_MAX - REALLOC_FRACTION_MIN
        )
        fraction = round(min(fraction, REALLOC_FRACTION_MAX), 4)
        amount = round(balance_usd * fraction, 2) if balance_usd > 0 else 0.0

        reason = (
            f"Account rank {rank}/{n} (outside top {top_30_cutoff}) "
            f"AND {state.consecutive_underperforming} consecutive losing trades "
            f"≥ threshold {UNDERPERFORM_TRADE_THRESHOLD} — move {fraction:.0%} out"
        )
        logger.warning(
            "[Brain] 🔀 REALLOCATION TRIGGERED for '%s': %s",
            account_id, reason,
        )
        return ReallocationDecision(
            account_id=account_id,
            fraction=fraction,
            amount_usd=amount,
            reason=reason,
        )

    # ── Unified Decision Hierarchy (Feature: Global→Account→Strategy→Trade) ──

    def run_hierarchy_check(
        self,
        current_account_id: str,
        all_accounts: List[str],
        is_account_alive: bool,
        strategy_approved: bool,
        base_position_size: float,
        strategy_reason: str = "",
    ) -> HierarchyDecision:
        """
        Run the full four-layer Capital Brain decision hierarchy.

        Evaluates layers in strict order and short-circuits at the first
        failure.  The pipeline is::

            Layer 1 — GLOBAL   : Is this the best account right now?
            Layer 2 — ACCOUNT  : Is this account healthy enough to trade?
            Layer 3 — STRATEGY : Did the strategy gate approve this signal?
            Layer 4 — TRADE    : Apply Capital Snowball multiplier.

        Args:
            current_account_id: The account attempting to place a trade.
            all_accounts:       All known account_ids (including current).
            is_account_alive:   Result from ``account_flow_layer.is_account_tradeable()``.
                                Supply ``True`` when the account-flow engine is unavailable.
            strategy_approved:  Result from ``win_rate_maximizer.approve_trade()`` (or
                                equivalent strategy gate).  Supply ``True`` when the
                                strategy gate was not run / not available.
            base_position_size: Raw position size in USD before snowball scaling.
            strategy_reason:    Rejection reason from the strategy gate (optional,
                                used only when ``strategy_approved=False``).

        Returns:
            :class:`HierarchyDecision` — a fully traced result with one entry
            per layer and the final (snowball-adjusted) position size.
        """
        layers: List[LayerResult] = []

        # ── Layer 1: GLOBAL — Capital routing ─────────────────────────────────
        global_ok, global_reason = self.should_trade(current_account_id, all_accounts)
        layers.append(LayerResult(
            layer="global",
            approved=global_ok,
            reason=global_reason,
        ))
        if not global_ok:
            return HierarchyDecision(
                approved=False,
                blocked_at="global",
                rejection_reason=global_reason,
                final_position_size=0.0,
                snowball_multiplier=1.0,
                win_streak=self._get_win_streak(current_account_id),
                layers=layers + [
                    LayerResult(layer="account",  approved=False, reason="pipeline short-circuited"),
                    LayerResult(layer="strategy", approved=False, reason="pipeline short-circuited"),
                    LayerResult(layer="trade",    approved=False, reason="pipeline short-circuited"),
                ],
                account_id=current_account_id,
            )

        # ── Layer 2: ACCOUNT — Health check ───────────────────────────────────
        acct_reason = "" if is_account_alive else "account killed — drawdown exceeded kill threshold"
        layers.append(LayerResult(
            layer="account",
            approved=is_account_alive,
            reason=acct_reason,
        ))
        if not is_account_alive:
            return HierarchyDecision(
                approved=False,
                blocked_at="account",
                rejection_reason=acct_reason,
                final_position_size=0.0,
                snowball_multiplier=1.0,
                win_streak=self._get_win_streak(current_account_id),
                layers=layers + [
                    LayerResult(layer="strategy", approved=False, reason="pipeline short-circuited"),
                    LayerResult(layer="trade",    approved=False, reason="pipeline short-circuited"),
                ],
                account_id=current_account_id,
            )

        # ── Layer 3: STRATEGY — Signal quality gate ────────────────────────────
        strat_reason = strategy_reason if not strategy_approved else ""
        layers.append(LayerResult(
            layer="strategy",
            approved=strategy_approved,
            reason=strat_reason,
        ))
        if not strategy_approved:
            return HierarchyDecision(
                approved=False,
                blocked_at="strategy",
                rejection_reason=strat_reason or "strategy gate rejected signal",
                final_position_size=0.0,
                snowball_multiplier=1.0,
                win_streak=self._get_win_streak(current_account_id),
                layers=layers + [
                    LayerResult(layer="trade", approved=False, reason="pipeline short-circuited"),
                ],
                account_id=current_account_id,
            )

        # ── Layer 4: TRADE — Capital Snowball sizing ───────────────────────────
        snowball_mult = self.get_snowball_multiplier(current_account_id)
        final_size = round(base_position_size * snowball_mult, 4)
        win_streak = self._get_win_streak(current_account_id)
        snowball_reason = (
            f"win_streak={win_streak} → {snowball_mult:.1f}× multiplier"
            if snowball_mult > 1.0 else ""
        )
        layers.append(LayerResult(
            layer="trade",
            approved=True,
            reason=snowball_reason,
            multiplier=snowball_mult,
        ))

        logger.debug(
            "[Brain] ✅ %s hierarchy APPROVED — snowball=%.1f× final_size=$%.2f",
            current_account_id, snowball_mult, final_size,
        )
        return HierarchyDecision(
            approved=True,
            blocked_at=None,
            rejection_reason="",
            final_position_size=final_size,
            snowball_multiplier=snowball_mult,
            win_streak=win_streak,
            layers=layers,
            account_id=current_account_id,
        )

    def _get_win_streak(self, account_id: str) -> int:
        """Return the current win streak for *account_id* (thread-safe)."""
        with self._lock:
            state = self._accounts.get(account_id)
            return state.win_streak if state else 0

    # ── Full report ───────────────────────────────────────────────────────────

    def get_report(self) -> Dict:
        """Return a full snapshot suitable for dashboards and logging."""
        ranked = self.get_ranked_accounts()
        snowball = [r.account_id for r in ranked if r.win_streak >= SNOWBALL_STREAK_LOW]
        stagnant = [
            r.account_id for r in ranked
            if r.account_id not in snowball
            and r.rank > max(1, math.ceil(len(ranked) * 0.30))
        ]
        return {
            "accounts": [r.to_dict() for r in ranked],
            "summary": {
                "total_accounts": len(ranked),
                "preferred_account": ranked[0].account_id if ranked else None,
                "snowball_accounts": snowball,
                "stagnant_accounts": stagnant,
            },
            "config": {
                "weight_win_rate": WEIGHT_WIN_RATE,
                "weight_profit_factor": WEIGHT_PROFIT_FACTOR,
                "weight_sharpe": WEIGHT_SHARPE,
                "weight_drawdown_ok": WEIGHT_DRAWDOWN_OK,
                "win_rate_window": WIN_RATE_WINDOW,
                "snowball_streak_low": SNOWBALL_STREAK_LOW,
                "snowball_streak_high": SNOWBALL_STREAK_HIGH,
                "snowball_mult_low": SNOWBALL_MULT_LOW,
                "snowball_mult_high": SNOWBALL_MULT_HIGH,
                "underperform_trade_threshold": UNDERPERFORM_TRADE_THRESHOLD,
                "realloc_fraction_min": REALLOC_FRACTION_MIN,
                "realloc_fraction_max": REALLOC_FRACTION_MAX,
                "min_trades_for_routing": MIN_TRADES_FOR_ROUTING,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_BRAIN: Optional[GlobalCapitalBrain] = None
_BRAIN_LOCK = threading.Lock()


def get_global_capital_brain() -> GlobalCapitalBrain:
    """Return the process-wide :class:`GlobalCapitalBrain` singleton."""
    global _BRAIN
    with _BRAIN_LOCK:
        if _BRAIN is None:
            _BRAIN = GlobalCapitalBrain()
            logger.info(
                "[Brain] GlobalCapitalBrain singleton created — "
                "capital routing + efficiency score + reallocation + snowball mode active"
            )
    return _BRAIN
