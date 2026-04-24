"""
NIJA Multi-Account Compounding Engine
======================================

True multi-account compounding engine that:
  1. Tracks per-account capital state across all connected brokers.
  2. Automatically selects the compounding tier for each account based on
     its current balance ($100 → $1 K → $10 K journey).
  3. Computes proportional per-account trade sizes and broadcasts them to
     every connected broker via :meth:`route_all`.
  4. Reinvests realised profits back into the trading pool to compound
     growth over time.

Scaling Tiers
-------------
::

    ┌─────────────────┬────────────┬───────────────┬───────────────────────┐
    │ Tier             │ Balance     │ Risk/trade    │ Max concurrent pos.   │
    ├─────────────────┼────────────┼───────────────┼───────────────────────┤
    │ MICRO            │ < $100      │ 3 %           │ 2                     │
    │ SEED             │ $100–$500   │ 3 %           │ 3                     │
    │ STARTER          │ $500–$1 K   │ 2.5 %         │ 4                     │
    │ GROWTH           │ $1 K–$5 K   │ 2 %           │ 5                     │
    │ SCALE            │ $5 K–$25 K  │ 1.5 %         │ 6                     │
    │ ELITE            │ > $25 K     │ 1 %           │ 8                     │
    └─────────────────┴────────────┴───────────────┴───────────────────────┘

Usage
-----
    from bot.multi_account_compounding_engine import get_multi_account_compounding_engine

    engine = get_multi_account_compounding_engine()

    # Refresh balances once per trading cycle:
    engine.refresh(multi_account_manager)

    # Compute trade sizes and broadcast to all connected brokers:
    results = engine.execute_all(
        symbol="BTC-USD",
        side="buy",
        strategy="ApexV71",
        platform_size_usd=200.0,   # the platform account's intended size
    )

    for r in results:
        print(r.account_id, r.broker, r.size_usd, r.success)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.multi_account_compounding")

# ---------------------------------------------------------------------------
# Scaling tiers
# ---------------------------------------------------------------------------


class CompoundTier(str, Enum):
    """Account-balance-driven compounding tier."""
    MICRO   = "MICRO"    # < $100
    SEED    = "SEED"     # $100 – $500
    STARTER = "STARTER"  # $500 – $1 000
    GROWTH  = "GROWTH"   # $1 000 – $5 000
    SCALE   = "SCALE"    # $5 000 – $25 000
    ELITE   = "ELITE"    # > $25 000


@dataclass
class TierConfig:
    """Per-tier trading parameters."""
    tier: CompoundTier
    min_balance: float
    max_balance: float
    risk_per_trade_pct: float   # fraction of balance risked per trade (0–1)
    max_positions: int          # maximum concurrent positions
    reinvest_pct: float         # fraction of profit reinvested (vs. locked)


_TIER_CONFIGS: Dict[CompoundTier, TierConfig] = {
    CompoundTier.MICRO:   TierConfig(CompoundTier.MICRO,        0,     100,  0.030, 2, 0.80),
    CompoundTier.SEED:    TierConfig(CompoundTier.SEED,        100,     500,  0.030, 3, 0.80),
    CompoundTier.STARTER: TierConfig(CompoundTier.STARTER,     500,   1_000, 0.025, 4, 0.82),
    CompoundTier.GROWTH:  TierConfig(CompoundTier.GROWTH,    1_000,   5_000, 0.020, 5, 0.85),
    CompoundTier.SCALE:   TierConfig(CompoundTier.SCALE,     5_000,  25_000, 0.015, 6, 0.87),
    CompoundTier.ELITE:   TierConfig(CompoundTier.ELITE,    25_000, float("inf"), 0.010, 8, 0.90),
}

# Minimum trade size — below this, skip the account to avoid dust orders.
_MIN_TRADE_USD: float = 5.0


def _resolve_tier(balance: float) -> TierConfig:
    """Return the TierConfig matching *balance*."""
    for cfg in reversed(list(_TIER_CONFIGS.values())):
        if balance >= cfg.min_balance:
            return cfg
    return _TIER_CONFIGS[CompoundTier.MICRO]


# ---------------------------------------------------------------------------
# Per-account state
# ---------------------------------------------------------------------------


@dataclass
class AccountState:
    """Runtime compounding state for one account."""
    account_id: str               # "platform_kraken", "user_alice_kraken", …
    exchange: str                 # "KRAKEN", "COINBASE", …
    balance_usd: float = 0.0
    locked_profits: float = 0.0   # profits preserved (not re-traded)
    reinvested_profits: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl_usd: float = 0.0
    last_updated: float = field(default_factory=time.time)

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.total_trades if self.total_trades else 0.0

    @property
    def tier(self) -> TierConfig:
        return _resolve_tier(self.balance_usd)

    def record_trade(self, pnl_usd: float) -> None:
        """Update state after a completed trade."""
        self.total_trades += 1
        self.total_pnl_usd += pnl_usd
        if pnl_usd > 0:
            self.winning_trades += 1
            cfg = self.tier
            reinvest = pnl_usd * cfg.reinvest_pct
            lock = pnl_usd - reinvest
            self.reinvested_profits += reinvest
            self.locked_profits += lock
            self.balance_usd += reinvest   # only reinvested portion grows the pool
        else:
            loss = abs(pnl_usd)
            self.balance_usd = max(0.0, self.balance_usd - loss)
        self.last_updated = time.time()


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------


@dataclass
class CompoundExecResult:
    """Result from a single per-account execution attempt."""
    account_id: str
    broker: str
    symbol: str
    side: str
    size_usd: float
    success: bool
    fill_price: float = 0.0
    filled_usd: float = 0.0
    error: Optional[str] = None
    tier: str = CompoundTier.SEED.value
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class MultiAccountCompoundingEngine:
    """
    Computes per-account trade sizes and broadcasts execution across every
    connected broker, compounding profits over time.

    Thread-safe; obtain the singleton via :func:`get_multi_account_compounding_engine`.
    """

    def __init__(
        self,
        min_trade_usd: float = _MIN_TRADE_USD,
    ) -> None:
        self._min_trade_usd = min_trade_usd
        self._lock = threading.Lock()

        # {account_id: AccountState}
        self._accounts: Dict[str, AccountState] = {}

        # Lazy-loaded subsystems
        self._multi_router = None       # MultiBrokerExecutionRouter
        self._cross_allocator = None    # CrossAccountCapitalAllocator

        logger.info(
            "💰 MultiAccountCompoundingEngine initialised (min_trade=$%.2f)",
            min_trade_usd,
        )

    # ------------------------------------------------------------------
    # Balance management
    # ------------------------------------------------------------------

    def register_account(
        self, account_id: str, exchange: str, balance_usd: float
    ) -> None:
        """Create or update the state entry for *account_id*."""
        with self._lock:
            if account_id not in self._accounts:
                self._accounts[account_id] = AccountState(
                    account_id=account_id,
                    exchange=exchange.upper(),
                    balance_usd=max(0.0, balance_usd),
                )
                logger.debug(
                    "[Compounding] registered account %s (%s) $%.2f",
                    account_id, exchange.upper(), balance_usd,
                )
            else:
                state = self._accounts[account_id]
                state.balance_usd = max(0.0, balance_usd)
                state.last_updated = time.time()

    def refresh(self, multi_account_manager) -> int:
        """
        Fetch live balances from all connected brokers via
        *multi_account_manager* and update internal account states.

        Returns the number of account/exchange combinations refreshed.
        """
        if multi_account_manager is None:
            return 0

        updated = 0

        # Platform brokers
        try:
            for broker_type, broker in multi_account_manager.platform_brokers.items():
                if not getattr(broker, "connected", False):
                    continue
                try:
                    bal = broker.get_account_balance()
                    account_id = f"platform_{broker_type.value.lower()}"
                    self.register_account(account_id, broker_type.value, bal)
                    # Mirror into CrossAccountCapitalAllocator if available
                    alloc = self._get_cross_allocator()
                    if alloc is not None:
                        alloc.register_platform_balance(broker_type.value, bal)
                    updated += 1
                except Exception as exc:
                    logger.debug(
                        "[Compounding] platform balance error (%s): %s",
                        broker_type.value, exc,
                    )
        except Exception as exc:
            logger.debug("[Compounding] platform_brokers error: %s", exc)

        # User brokers
        try:
            for user_id, user_brokers in multi_account_manager.user_brokers.items():
                for broker_type, broker in user_brokers.items():
                    if not getattr(broker, "connected", False):
                        continue
                    try:
                        bal = broker.get_account_balance()
                        account_id = f"user_{user_id}_{broker_type.value.lower()}"
                        self.register_account(account_id, broker_type.value, bal)
                        alloc = self._get_cross_allocator()
                        if alloc is not None:
                            alloc.register_user_balance(user_id, broker_type.value, bal)
                        updated += 1
                    except Exception as exc:
                        logger.debug(
                            "[Compounding] user balance error (%s/%s): %s",
                            user_id, broker_type.value, exc,
                        )
        except Exception as exc:
            logger.debug("[Compounding] user_brokers error: %s", exc)

        logger.debug("[Compounding] refreshed %d account(s)", updated)
        return updated

    # ------------------------------------------------------------------
    # Trade-size computation
    # ------------------------------------------------------------------

    def compute_size(
        self,
        account_id: str,
        platform_size_usd: float,
        platform_balance_usd: float,
    ) -> float:
        """
        Compute a proportional trade size for *account_id* relative to the
        platform account's intended *platform_size_usd*.

        The returned size is capped at the tier's ``risk_per_trade_pct`` of the
        user's balance so that every account stays within its own risk limits.

        Returns 0.0 when the computed size is below ``min_trade_usd``.
        """
        with self._lock:
            state = self._accounts.get(account_id)

        if state is None or state.balance_usd <= 0:
            return 0.0
        if platform_balance_usd <= 0:
            return 0.0

        scale = state.balance_usd / platform_balance_usd
        raw_size = platform_size_usd * scale

        # Cap at tier risk limit
        cfg = state.tier
        max_by_risk = state.balance_usd * cfg.risk_per_trade_pct
        final_size = min(raw_size, max_by_risk)

        if final_size < self._min_trade_usd:
            logger.debug(
                "[Compounding] %s: size $%.2f below min $%.2f — skipped",
                account_id, final_size, self._min_trade_usd,
            )
            return 0.0

        return round(final_size, 2)

    def get_all_account_sizes(
        self,
        platform_size_usd: float,
        platform_account_id: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Return a mapping of {account_id: trade_size_usd} for every registered
        account, proportionally scaled from *platform_size_usd*.

        If *platform_account_id* is supplied, that account's balance is used
        as the scale reference; otherwise the largest registered balance is used.
        """
        with self._lock:
            accounts = dict(self._accounts)

        if not accounts:
            return {}

        # Determine reference (platform) balance
        if platform_account_id and platform_account_id in accounts:
            platform_balance = accounts[platform_account_id].balance_usd
        else:
            # Fall back to the account with the highest balance
            platform_balance = max(s.balance_usd for s in accounts.values())

        if platform_balance <= 0:
            return {}

        sizes: Dict[str, float] = {}
        for acct_id, state in accounts.items():
            size = self.compute_size(acct_id, platform_size_usd, platform_balance)
            if size >= self._min_trade_usd:
                sizes[acct_id] = size

        return sizes

    # ------------------------------------------------------------------
    # Broadcast execution
    # ------------------------------------------------------------------

    def execute_all(
        self,
        symbol: str,
        side: str,
        strategy: str,
        platform_size_usd: float,
        platform_account_id: Optional[str] = None,
        order_type: str = "MARKET",
        asset_class: Optional[str] = None,
    ) -> List[CompoundExecResult]:
        """
        Compute per-account sizes and route each account's trade through the
        best available broker via :meth:`MultiBrokerExecutionRouter.route`.

        Each account is sized proportionally to its own balance (see
        :meth:`get_all_account_sizes`) and then routed independently.  This
        means a user with $150 gets a smaller position than a user with $2 500,
        each going through whatever broker scores best for that asset class.

        To broadcast a single fixed size to *all* brokers simultaneously (e.g.
        for a platform-level signal), call
        :meth:`MultiBrokerExecutionRouter.route_all` directly instead.

        Steps
        -----
        1. Call :meth:`get_all_account_sizes` to scale each account's size.
        2. For each account with an approved size, create a
           :class:`RouteRequest` and call ``router.route()``.
        3. Collect results.

        Returns a list of :class:`CompoundExecResult` — one per attempted account.
        """
        # Resolve RouteRequest once, before the loop
        RouteRequest = None
        for _mod_name in ("bot.multi_broker_execution_router", "multi_broker_execution_router"):
            try:
                _mod = __import__(_mod_name, fromlist=["RouteRequest"])
                RouteRequest = _mod.RouteRequest
                break
            except (ImportError, AttributeError):
                continue
        if RouteRequest is None:
            logger.error("[Compounding] RouteRequest unavailable — cannot execute")
            return []

        sizes = self.get_all_account_sizes(platform_size_usd, platform_account_id)
        if not sizes:
            logger.info("[Compounding] execute_all: no eligible accounts for %s %s", side, symbol)
            return []

        router = self._get_router()
        if router is None:
            logger.error("[Compounding] execute_all: MultiBrokerExecutionRouter unavailable")
            return []

        results: List[CompoundExecResult] = []
        for account_id, size_usd in sizes.items():
            with self._lock:
                state = self._accounts.get(account_id)
            if state is None:
                continue

            tier_name = state.tier.tier.value
            t0 = time.monotonic()

            try:
                req = RouteRequest(
                    strategy=strategy,
                    symbol=symbol,
                    side=side,
                    size_usd=size_usd,
                    order_type=order_type,
                    asset_class=asset_class or "",
                )
                route_result = router.route(req)
                latency_ms = (time.monotonic() - t0) * 1000

                results.append(CompoundExecResult(
                    account_id=account_id,
                    broker=route_result.broker,
                    symbol=symbol,
                    side=side,
                    size_usd=size_usd,
                    success=route_result.success,
                    fill_price=route_result.fill_price,
                    filled_usd=route_result.filled_size_usd,
                    error=route_result.error,
                    tier=tier_name,
                    latency_ms=latency_ms,
                ))
            except Exception as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                logger.error(
                    "[Compounding] execute_all error for %s: %s", account_id, exc
                )
                results.append(CompoundExecResult(
                    account_id=account_id,
                    broker="NONE",
                    symbol=symbol,
                    side=side,
                    size_usd=size_usd,
                    success=False,
                    error=str(exc),
                    tier=tier_name,
                    latency_ms=latency_ms,
                ))

        successes = sum(1 for r in results if r.success)
        logger.info(
            "[Compounding] execute_all: %d/%d accounts succeeded (%s %s $%.2f base)",
            successes, len(results), side.upper(), symbol, platform_size_usd,
        )
        return results

    # ------------------------------------------------------------------
    # Profit recording
    # ------------------------------------------------------------------

    def record_trade_outcome(
        self,
        account_id: str,
        pnl_usd: float,
    ) -> None:
        """
        Record a completed trade's P&L for *account_id*.

        Profits are compounded according to the account's current tier:
        ``reinvest_pct`` goes back into the trading pool; the remainder is
        locked as protected profit.
        """
        with self._lock:
            state = self._accounts.get(account_id)
        if state is None:
            logger.debug("[Compounding] record_trade_outcome: unknown account %s", account_id)
            return
        state.record_trade(pnl_usd)
        logger.info(
            "[Compounding] %s | pnl=%.2f | balance=$%.2f | tier=%s | locked=$%.2f",
            account_id, pnl_usd, state.balance_usd, state.tier.tier.value,
            state.locked_profits,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a human-readable summary of all account states."""
        with self._lock:
            accounts = list(self._accounts.values())

        if not accounts:
            return "MultiAccountCompoundingEngine: no accounts registered."

        lines = [
            "=" * 72,
            "  NIJA MULTI-ACCOUNT COMPOUNDING ENGINE — ACCOUNT SUMMARY",
            "=" * 72,
            f"  {'Account':<35} {'Balance':>10} {'Tier':<10} {'Trades':>7} {'W%':>6} {'PnL':>10}",
            "-" * 72,
        ]
        total_balance = 0.0
        total_pnl = 0.0
        for s in sorted(accounts, key=lambda x: -x.balance_usd):
            w = f"{s.win_rate * 100:.1f}%" if s.total_trades else "—"
            lines.append(
                f"  {s.account_id:<35} ${s.balance_usd:>9,.2f} "
                f"{s.tier.tier.value:<10} {s.total_trades:>7} {w:>6} "
                f"${s.total_pnl_usd:>9,.2f}"
            )
            total_balance += s.balance_usd
            total_pnl += s.total_pnl_usd
        lines += [
            "-" * 72,
            f"  {'TOTAL':<35} ${total_balance:>9,.2f} {'':10} {'':7} {'':6} ${total_pnl:>9,.2f}",
            "=" * 72,
        ]
        return "\n".join(lines)

    def get_account_state(self, account_id: str) -> Optional[AccountState]:
        """Return the raw state object for *account_id*, or ``None``."""
        with self._lock:
            return self._accounts.get(account_id)

    # ------------------------------------------------------------------
    # Lazy subsystem accessors
    # ------------------------------------------------------------------

    def _get_router(self):
        if self._multi_router is not None:
            return self._multi_router
        for mod_name in ("bot.multi_broker_execution_router", "multi_broker_execution_router"):
            try:
                mod = __import__(mod_name, fromlist=["get_multi_broker_router"])
                self._multi_router = mod.get_multi_broker_router()
                return self._multi_router
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("[Compounding] router load error: %s", exc)
                return None
        return None

    def _get_cross_allocator(self):
        if self._cross_allocator is not None:
            return self._cross_allocator
        for mod_name in ("bot.cross_account_capital_allocator", "cross_account_capital_allocator"):
            try:
                mod = __import__(mod_name, fromlist=["get_cross_account_allocator"])
                self._cross_allocator = mod.get_cross_account_allocator()
                return self._cross_allocator
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("[Compounding] allocator load error: %s", exc)
                return None
        return None


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_ENGINE: Optional[MultiAccountCompoundingEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_multi_account_compounding_engine(
    min_trade_usd: float = _MIN_TRADE_USD,
) -> MultiAccountCompoundingEngine:
    """Return the process-wide :class:`MultiAccountCompoundingEngine` singleton."""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = MultiAccountCompoundingEngine(min_trade_usd=min_trade_usd)
    return _ENGINE


__all__ = [
    "CompoundTier",
    "TierConfig",
    "AccountState",
    "CompoundExecResult",
    "MultiAccountCompoundingEngine",
    "get_multi_account_compounding_engine",
]
