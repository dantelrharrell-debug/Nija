"""
NIJA Signal Broadcaster
========================

Broadcasts a validated trade signal to **multiple accounts / brokers** while
applying proportional, risk-adjusted position sizing via the GlobalCapitalManager.

Each account receives a trade sized by:
    base_size = account.balance * risk_fraction
    final_size = base_size * capital_manager.get_allocation(account.id)

This means larger accounts naturally get larger positions while the
portfolio-wide risk budget is still respected.

Usage
-----
::

    from bot.signal_broadcaster import get_signal_broadcaster, BroadcastSignal

    broadcaster = get_signal_broadcaster()

    broadcaster.register_account("coinbase", coinbase_broker, balance=5000.0)
    broadcaster.register_account("kraken",   kraken_broker,   balance=3000.0)

    results = broadcaster.execute_across_accounts({
        "action": "enter_long",
        "symbol": "BTC-USD",
    })

    for r in results:
        print(r.account_id, "->", r.status, r.error or "")

Author: NIJA Trading Systems
Version: 2.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.signal_broadcaster")

DEFAULT_RISK_FRACTION = 0.02

# ---------------------------------------------------------------------------
# Optional dependency: GlobalCapitalManager
# ---------------------------------------------------------------------------
try:
    from global_capital_manager import get_global_capital_manager
    _GCM_AVAILABLE = True
except ImportError:
    try:
        from bot.global_capital_manager import get_global_capital_manager
        _GCM_AVAILABLE = True
    except ImportError:
        _GCM_AVAILABLE = False
        get_global_capital_manager = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data structures (non-default fields FIRST)
# ---------------------------------------------------------------------------

@dataclass
class BroadcastSignal:
    """Signal to broadcast across multiple accounts."""
    symbol: str
    side: str                     # "buy" / "sell" / "long" / "short"
    size_usd: float               # base position size in USD
    strategy: str = ""
    account_ids: List[str] = field(default_factory=list)
    order_type: Optional[str] = None
    asset_class: Optional[str] = None
    # Optional per-account size overrides (account_id -> fraction of size_usd)
    account_fractions: Dict[str, float] = field(default_factory=dict)


@dataclass
class AccountResult:
    """Execution result for one account."""
    account_id: str
    success: bool
    fill_price: float = 0.0
    filled_size_usd: float = 0.0
    broker: str = ""
    error: str = ""
    latency_ms: float = 0.0


@dataclass
class AccountRecord:
    """Broker account registered for signal broadcasting."""
    account_id: str
    broker: Any                      # BaseBroker instance
    balance: float = 0.0


@dataclass
class BroadcastResult:
    """Result of executing a broadcast signal on a single account."""
    account_id: str
    symbol: str
    side: str
    size_usd: float
    status: str                      # "filled" | "skipped" | "error"
    order_result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# SignalBroadcaster
# ---------------------------------------------------------------------------

class SignalBroadcaster:
    """
    Executes a master signal across all registered broker accounts
    with proportional, risk-adjusted position sizing.
    """

    def __init__(self, risk_fraction: float = DEFAULT_RISK_FRACTION) -> None:
        self._accounts: Dict[str, AccountRecord] = {}
        self._risk_fraction = risk_fraction
        self._lock = threading.Lock()

    # ── Account registry ─────────────────────────────────────────────────────

    def register_account(
        self,
        account_id: str,
        broker: Any,
        balance: float = 0.0,
    ) -> None:
        """Register (or update) a broker account for fan-out execution."""
        with self._lock:
            self._accounts[account_id] = AccountRecord(
                account_id=account_id,
                broker=broker,
                balance=max(0.0, balance),
            )
            # Keep GlobalCapitalManager in sync
            if _GCM_AVAILABLE and get_global_capital_manager:
                try:
                    get_global_capital_manager().register_account(account_id, balance)
                except Exception:
                    pass
        logger.debug("[Broadcaster] registered account %s balance=%.2f", account_id, balance)

    def update_balance(self, account_id: str, balance: float) -> None:
        """Update the cached balance for an account (call each trading cycle)."""
        with self._lock:
            if account_id in self._accounts:
                self._accounts[account_id].balance = max(0.0, balance)
                if _GCM_AVAILABLE and get_global_capital_manager:
                    try:
                        get_global_capital_manager().register_account(account_id, balance)
                    except Exception:
                        pass

    def account_ids(self) -> List[str]:
        """Return a snapshot of registered account IDs."""
        with self._lock:
            return list(self._accounts.keys())

    # ── Core fan-out ──────────────────────────────────────────────────────────

    def execute_across_accounts(
        self,
        signal: Dict[str, Any],
    ) -> List[BroadcastResult]:
        """
        Execute *signal* on every registered account.

        Sizing per account
        ------------------
        1. ``base_size = account.balance × risk_fraction``
        2. ``size *= capital_manager.get_allocation(account.id)``   ← weighted

        Args:
            signal: Dict with at minimum ``{'action': str, 'symbol': str}``.
                    Use the dict from ``ApexStrategy.analyze_market()`` or
                    ``MasterStrategyRouter.get_signal()``.

        Returns:
            List of BroadcastResult, one per account.
        """
        action = signal.get("action", "hold")
        symbol = signal.get("symbol", "")
        side = "buy" if action == "enter_long" else "sell" if action == "enter_short" else ""

        results: List[BroadcastResult] = []

        if not side or not symbol:
            logger.debug(
                "[Broadcaster] skipping fan-out — action=%s symbol=%s", action, symbol
            )
            return results

        with self._lock:
            accounts_snapshot = list(self._accounts.values())

        capital_manager = (
            get_global_capital_manager()
            if _GCM_AVAILABLE and get_global_capital_manager
            else None
        )

        for account in accounts_snapshot:
            result = self._execute_single(
                account=account,
                signal=signal,
                symbol=symbol,
                side=side,
                capital_manager=capital_manager,
            )
            results.append(result)

        filled = sum(1 for r in results if r.status == "filled")
        logger.info(
            "[Broadcaster] %s %s → %d/%d accounts filled",
            side.upper(), symbol, filled, len(results),
        )
        return results

    def _execute_single(
        self,
        account: AccountRecord,
        signal: Dict[str, Any],
        symbol: str,
        side: str,
        capital_manager: Any,
    ) -> BroadcastResult:
        """Execute signal for one account with proportional sizing."""
        try:
            broker = account.broker

            # 1. Base size: risk_fraction × balance
            size = account.balance * self._risk_fraction

            # 2. Weighted copy trading: scale by account's capital share
            if capital_manager is not None:
                allocation = capital_manager.get_allocation(account.account_id)
                size *= allocation

            size = round(size, 2)

            if size <= 0:
                return BroadcastResult(
                    account_id=account.account_id,
                    symbol=symbol,
                    side=side,
                    size_usd=size,
                    status="skipped",
                    error="size_zero",
                )

            logger.info(
                "[Broadcaster] → %s | %s %s $%.2f",
                account.account_id, side.upper(), symbol, size,
            )

            order = broker.execute_order(
                symbol=symbol,
                side=side,
                quantity=size,
                size_type="quote",
            )

            status = order.get("status", "error") if order else "error"
            if status in ("filled", "open", "pending"):
                status = "filled"

            return BroadcastResult(
                account_id=account.account_id,
                symbol=symbol,
                side=side,
                size_usd=size,
                status=status,
                order_result=order or {},
            )

        except Exception as exc:
            logger.warning(
                "[Broadcaster] %s error on %s: %s",
                account.account_id, symbol, exc,
            )
            return BroadcastResult(
                account_id=account.account_id,
                symbol=symbol,
                side=side,
                size_usd=0.0,
                status="error",
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_BROADCASTER: Optional[SignalBroadcaster] = None
_BROADCASTER_LOCK = threading.Lock()


def get_signal_broadcaster() -> SignalBroadcaster:
    """Return the process-wide SignalBroadcaster singleton."""
    global _BROADCASTER
    with _BROADCASTER_LOCK:
        if _BROADCASTER is None:
            _BROADCASTER = SignalBroadcaster()
            logger.info(
                "[Broadcaster] singleton created "
                "(risk_fraction=%.0f%% per account)",
                DEFAULT_RISK_FRACTION * 100,
            )
    return _BROADCASTER
