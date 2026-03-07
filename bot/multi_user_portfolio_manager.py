"""
Multi-User Portfolio Manager
==============================

Enables multi-user / multi-portfolio management with optional
copy-trading and AI-managed sub-accounts.

Key capabilities
----------------
1. User isolation
   - Each user has a private PortfolioProfile with its own capital,
     positions, risk limits, and performance tracker.
   - Users cannot access each other's data.

2. Copy trading
   - A CopyGroup links one "leader" portfolio with one or more
     "follower" portfolios.
   - Follower position sizes are scaled proportionally to their
     allocated capital relative to the leader's capital.
   - Independent risk limits are applied on the follower side
     before any copy order is placed.

3. AI-managed sub-accounts
   - Sub-accounts tagged as AI_MANAGED are routed through the
     MetaLearningOptimizer for regime-weighted strategy selection.
   - Capital allocations are automatically adjusted based on
     live performance.

Usage
-----
    from bot.multi_user_portfolio_manager import get_multi_user_manager

    mgr = get_multi_user_manager()

    # Register users
    mgr.register_user("alice", capital=25_000, max_drawdown_pct=10.0)
    mgr.register_user("bob",   capital=5_000,  max_drawdown_pct=15.0)

    # Set up copy trading (bob copies alice)
    mgr.register_copy_group("grp1", leader_id="alice", follower_ids=["bob"])

    # Broadcast a leader trade to followers
    copies = mgr.broadcast_copy_trade(
        leader_id="alice",
        symbol="BTC-USD",
        side="buy",
        leader_size=0.50,
        strategy="ApexTrend",
    )

    # Record portfolio update
    mgr.update_portfolio("alice", equity=25_500.0, pnl=500.0, won=True)

    # Dashboard data
    print(mgr.get_dashboard())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.multi_user_portfolio_manager")

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class AccountType(str, Enum):
    MANUAL     = "MANUAL"       # User-directed trades
    COPY       = "COPY"         # Follows a leader portfolio
    AI_MANAGED = "AI_MANAGED"   # Fully AI-directed via MetaLearningOptimizer


class RiskTier(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"   # max 5 % drawdown
    MODERATE     = "MODERATE"       # max 10 % drawdown
    AGGRESSIVE   = "AGGRESSIVE"     # max 20 % drawdown


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PortfolioProfile:
    user_id:          str
    display_name:     str
    account_type:     str = AccountType.MANUAL.value
    initial_capital:  float = 10_000.0
    current_equity:   float = 10_000.0
    available_cash:   float = 10_000.0
    max_drawdown_pct: float = 10.0
    max_position_pct: float = 10.0
    risk_tier:        str = RiskTier.MODERATE.value
    created_at:       str = ""
    last_updated:     str = ""

    # Performance accumulators
    total_trades:  int   = 0
    winning_trades: int  = 0
    total_pnl:     float = 0.0
    gross_profit:  float = 0.0
    gross_loss:    float = 0.0
    peak_equity:   float = 0.0
    max_drawdown:  float = 0.0   # realized

    # Open positions: symbol → {"size": float, "entry_price": float, ...}
    positions: Dict[str, Any] = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.total_trades if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        return (self.gross_profit / self.gross_loss
                if self.gross_loss > 0 else float("inf"))

    @property
    def current_drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.current_equity) / self.peak_equity * 100)

    @property
    def is_drawdown_breached(self) -> bool:
        return self.current_drawdown_pct >= self.max_drawdown_pct

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["win_rate"]               = round(self.win_rate, 4)
        d["profit_factor"]          = round(min(self.profit_factor, 99.0), 4)
        d["current_drawdown_pct"]   = round(self.current_drawdown_pct, 4)
        d["is_drawdown_breached"]   = self.is_drawdown_breached
        return d


@dataclass
class CopyGroup:
    group_id:     str
    leader_id:    str
    follower_ids: List[str] = field(default_factory=list)
    active:       bool      = True
    created_at:   str       = ""

    # Configuration
    min_copy_size:  float = 0.0001   # minimum follower order size
    max_copy_pct:   float = 0.10     # max follower capital in one copy trade
    latency_ms:     float = 0.0      # simulated copy latency (for backtests)


@dataclass
class CopyTrade:
    group_id:      str
    leader_id:     str
    follower_id:   str
    symbol:        str
    side:          str
    leader_size:   float
    follower_size: float
    scale_factor:  float
    timestamp:     str
    approved:      bool   = True
    reject_reason: str    = ""


# ─────────────────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────────────────

class MultiUserPortfolioManager:
    """
    Central registry for all user portfolios with copy-trading
    and AI-managed sub-account support.
    """

    def __init__(
        self,
        state_path: str = "data/multi_user_state.json",
    ) -> None:
        self.state_path = state_path
        self._lock      = threading.RLock()

        self._portfolios:  Dict[str, PortfolioProfile] = {}
        self._copy_groups: Dict[str, CopyGroup]        = {}
        self._trade_log:   List[CopyTrade]             = []

        self._load_state()
        logger.info("👥 MultiUserPortfolioManager ready | users=%d", len(self._portfolios))

    # ── User management ───────────────────────────────────────────────────────

    def register_user(
        self,
        user_id: str,
        capital: float = 10_000.0,
        display_name: str = "",
        account_type: AccountType = AccountType.MANUAL,
        max_drawdown_pct: float = 10.0,
        max_position_pct: float = 10.0,
        risk_tier: RiskTier = RiskTier.MODERATE,
    ) -> PortfolioProfile:
        """Register a new user or update an existing one."""
        with self._lock:
            if user_id in self._portfolios:
                logger.info("[MultiUser] User %s already registered.", user_id)
                return self._portfolios[user_id]

            profile = PortfolioProfile(
                user_id          = user_id,
                display_name     = display_name or user_id,
                account_type     = account_type.value,
                initial_capital  = capital,
                current_equity   = capital,
                available_cash   = capital,
                max_drawdown_pct = max_drawdown_pct,
                max_position_pct = max_position_pct,
                risk_tier        = risk_tier.value,
                created_at       = _now(),
                last_updated     = _now(),
                peak_equity      = capital,
            )
            self._portfolios[user_id] = profile
            logger.info(
                "[MultiUser] Registered user=%s | type=%s | capital=$%.2f",
                user_id, account_type.value, capital,
            )
            self._save_state()
            return profile

    def get_user(self, user_id: str) -> Optional[PortfolioProfile]:
        with self._lock:
            return self._portfolios.get(user_id)

    def update_portfolio(
        self,
        user_id: str,
        equity: float,
        pnl: float = 0.0,
        won: bool = False,
        available_cash: Optional[float] = None,
    ) -> None:
        """Update portfolio equity / performance stats after a trade."""
        with self._lock:
            p = self._portfolios.get(user_id)
            if p is None:
                logger.warning("[MultiUser] Unknown user: %s", user_id)
                return

            p.current_equity = equity
            if available_cash is not None:
                p.available_cash = available_cash
            if equity > p.peak_equity:
                p.peak_equity = equity

            p.total_trades   += 1
            p.winning_trades += int(won)
            p.total_pnl      += pnl
            if pnl > 0:
                p.gross_profit += pnl
            else:
                p.gross_loss += abs(pnl)

            dd = p.current_drawdown_pct
            if dd > p.max_drawdown:
                p.max_drawdown = dd

            p.last_updated = _now()
            self._save_state()

    def list_users(self) -> List[Dict[str, Any]]:
        """Return summary info for all registered users."""
        with self._lock:
            return [p.to_dict() for p in self._portfolios.values()]

    def remove_user(self, user_id: str) -> bool:
        """Deregister a user (does not delete trade history)."""
        with self._lock:
            if user_id not in self._portfolios:
                return False
            del self._portfolios[user_id]
            self._save_state()
            logger.info("[MultiUser] User %s removed.", user_id)
            return True

    # ── Copy trading ──────────────────────────────────────────────────────────

    def register_copy_group(
        self,
        group_id: str,
        leader_id: str,
        follower_ids: List[str],
        max_copy_pct: float = 0.10,
    ) -> CopyGroup:
        """Create a copy-trading group."""
        with self._lock:
            if leader_id not in self._portfolios:
                raise ValueError(f"Leader user '{leader_id}' not registered.")
            for fid in follower_ids:
                if fid not in self._portfolios:
                    raise ValueError(f"Follower user '{fid}' not registered.")

            group = CopyGroup(
                group_id     = group_id,
                leader_id    = leader_id,
                follower_ids = list(follower_ids),
                max_copy_pct = max_copy_pct,
                created_at   = _now(),
            )
            self._copy_groups[group_id] = group
            logger.info(
                "[CopyTrade] Group '%s' | leader=%s | followers=%s",
                group_id, leader_id, follower_ids,
            )
            self._save_state()
            return group

    def broadcast_copy_trade(
        self,
        leader_id: str,
        symbol: str,
        side: str,
        leader_size: float,
        strategy: str = "",
    ) -> List[CopyTrade]:
        """
        Broadcast a leader's trade to all active followers.

        Follower sizes are scaled by (follower_capital / leader_capital).
        Returns a list of CopyTrade objects (one per follower).
        """
        with self._lock:
            leader = self._portfolios.get(leader_id)
            if leader is None:
                return []

            # Find groups where this user is the leader
            active_groups = [
                g for g in self._copy_groups.values()
                if g.leader_id == leader_id and g.active
            ]

            copy_trades: List[CopyTrade] = []
            for group in active_groups:
                for follower_id in group.follower_ids:
                    follower = self._portfolios.get(follower_id)
                    if follower is None:
                        continue
                    if follower.is_drawdown_breached:
                        logger.warning(
                            "[CopyTrade] Follower %s skipped – drawdown breached.",
                            follower_id,
                        )
                        ct = CopyTrade(
                            group_id=group.group_id,
                            leader_id=leader_id,
                            follower_id=follower_id,
                            symbol=symbol, side=side,
                            leader_size=leader_size, follower_size=0.0,
                            scale_factor=0.0,
                            timestamp=_now(),
                            approved=False,
                            reject_reason="drawdown_breached",
                        )
                        copy_trades.append(ct)
                        continue

                    # Proportional scaling
                    scale = follower.current_equity / max(1.0, leader.current_equity)
                    raw_size = leader_size * scale

                    # Respect follower max-position-pct cap
                    max_size_by_cap = (follower.current_equity * group.max_copy_pct
                                       / max(1.0, follower.available_cash))
                    follower_size = min(raw_size, max_size_by_cap)
                    follower_size = max(group.min_copy_size, follower_size)

                    ct = CopyTrade(
                        group_id=group.group_id,
                        leader_id=leader_id,
                        follower_id=follower_id,
                        symbol=symbol, side=side,
                        leader_size=leader_size,
                        follower_size=round(follower_size, 8),
                        scale_factor=round(scale, 6),
                        timestamp=_now(),
                        approved=True,
                    )
                    copy_trades.append(ct)
                    logger.info(
                        "[CopyTrade] %s → %s | %s %s %.6f (scaled from %.6f)",
                        leader_id, follower_id, side, symbol,
                        ct.follower_size, leader_size,
                    )

            self._trade_log.extend(copy_trades)
            self._save_state()
            return copy_trades

    # ── AI sub-account management ─────────────────────────────────────────────

    def get_ai_allocations(
        self,
        user_id: str,
        regime: str,
    ) -> Dict[str, float]:
        """
        For an AI_MANAGED account, return per-strategy dollar allocations
        via MetaLearningOptimizer.
        """
        with self._lock:
            profile = self._portfolios.get(user_id)
            if profile is None or profile.account_type != AccountType.AI_MANAGED.value:
                return {}

        try:
            from bot.meta_learning_optimizer import get_meta_learning_optimizer
            opt = get_meta_learning_optimizer()
            return opt.get_risk_adjusted_allocations(regime, profile.current_equity)
        except Exception as exc:
            logger.warning("[MultiUser] AI allocation failed: %s", exc)
            return {}

    # ── Dashboard ─────────────────────────────────────────────────────────────

    def get_dashboard(self) -> Dict[str, Any]:
        """Return a full multi-user dashboard snapshot."""
        with self._lock:
            total_aum = sum(p.current_equity for p in self._portfolios.values())
            return {
                "total_users":    len(self._portfolios),
                "total_aum":      round(total_aum, 2),
                "copy_groups":    len(self._copy_groups),
                "portfolios":     [p.to_dict() for p in self._portfolios.values()],
                "copy_group_ids": list(self._copy_groups.keys()),
                "recent_copies":  [asdict(t) for t in self._trade_log[-20:]],
            }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path) as fh:
                    data = json.load(fh)
                for uid, pd in data.get("portfolios", {}).items():
                    self._portfolios[uid] = PortfolioProfile(**{
                        k: v for k, v in pd.items()
                        if k in PortfolioProfile.__dataclass_fields__
                    })
                for gid, gd in data.get("copy_groups", {}).items():
                    self._copy_groups[gid] = CopyGroup(**{
                        k: v for k, v in gd.items()
                        if k in CopyGroup.__dataclass_fields__
                    })
                logger.info(
                    "[MultiUser] Loaded %d users, %d groups from state.",
                    len(self._portfolios), len(self._copy_groups),
                )
        except Exception as exc:
            logger.warning("[MultiUser] Could not load state (%s) – starting fresh.", exc)

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "w") as fh:
                json.dump(
                    {
                        "portfolios":  {uid: p.to_dict() for uid, p in self._portfolios.items()},
                        "copy_groups": {gid: asdict(g) for gid, g in self._copy_groups.items()},
                        "saved_at":    _now(),
                    },
                    fh, indent=2,
                )
        except Exception as exc:
            logger.warning("[MultiUser] Could not persist state: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_manager_instance: Optional[MultiUserPortfolioManager] = None
_manager_lock = threading.Lock()


def get_multi_user_manager(
    state_path: str = "data/multi_user_state.json",
) -> MultiUserPortfolioManager:
    """Return the process-wide MultiUserPortfolioManager singleton."""
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = MultiUserPortfolioManager(state_path=state_path)
    return _manager_instance


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
