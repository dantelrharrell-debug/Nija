"""
NIJA Signal Broadcaster
========================

Broadcasts a validated trade signal to **multiple accounts / brokers** while
enforcing the **VolatilityGuard** (Priority-1) gate *before* any order is
dispatched.

This is the canonical multi-account entry point.  The existing global capital
scaling, cross-account risk management, and copy-trading machinery is
preserved: the VolatilityGuard is inserted as an outer gate so that a
portfolio-wide volatility shock stops ALL account broadcasts immediately.

Priority gate wired here
-------------------------
::

    VolatilityGuard.check(symbol)       <-- Priority-1: blowup prevention
        |
        EXTREME shock  --> block entire broadcast (zero accounts receive order)
        SEVERE shock   --> scale size_usd on all accounts, then broadcast
        NONE/MINOR/MOD --> broadcast normally (with per-account size scaling)
        |
        PASS --> execute_across_accounts(...)

Architecture
------------
::

    SignalBroadcaster.broadcast(signal)
        |
        +-- VolatilityGuard.check(symbol)   [Priority-1 gate]
        |         blocked? --> return BroadcastResult(success=False)
        |         scaled?  --> apply size_scale to all account sizes
        |
        +-- For each (account_id, broker_client):
        |       +-- ExecutionPipeline.execute(PipelineRequest)
        |               |-- TradeThrottler.check()  [Priority-2 gate]
        |               +-- ExecutionRouter / MultiBrokerRouter
        |
        +-- Record results per account
        +-- Return BroadcastResult

Usage
-----
::

    from bot.signal_broadcaster import get_signal_broadcaster, BroadcastSignal

    broadcaster = get_signal_broadcaster()

    result = broadcaster.broadcast(BroadcastSignal(
        symbol="BTC-USD",
        side="buy",
        size_usd=1_000.0,
        strategy="ApexTrend",
        account_ids=["main", "follower_1", "follower_2"],
    ))

    for ar in result.account_results:
        print(ar.account_id, "->", "OK" if ar.success else ar.error)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("nija.signal_broadcaster")


# ---------------------------------------------------------------------------
# Public types
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
class BroadcastResult:
    """Aggregated result for a full multi-account broadcast."""

    success: bool              # True if at least one account succeeded
    symbol: str
    side: str
    size_usd: float
    volatility_blocked: bool = False
    volatility_severity: str = "NONE"
    size_scale_applied: float = 1.0
    account_results: List[AccountResult] = field(default_factory=list)
    error: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def accounts_succeeded(self) -> int:
        return sum(1 for r in self.account_results if r.success)

    @property
    def accounts_failed(self) -> int:
        return sum(1 for r in self.account_results if not r.success)


# ---------------------------------------------------------------------------
# Broadcaster
# ---------------------------------------------------------------------------


class SignalBroadcaster:
    """Multi-account signal broadcaster with VolatilityGuard (Priority-1) gate.

    Thread-safe singleton via ``get_signal_broadcaster()``.

    Existing global capital scaling, cross-account risk, and copy-trading
    logic is preserved.  The VolatilityGuard is inserted as the outermost
    gate before any account receives an order.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._guard = self._load_guard()
        self._pipeline = self._load_pipeline()

        logger.info(
            "SignalBroadcaster initialised | vol_guard=%s | pipeline=%s",
            self._guard is not None,
            self._pipeline is not None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_across_accounts(
        self,
        signal: BroadcastSignal,
    ) -> BroadcastResult:
        """Broadcast a signal to all specified accounts.

        **VolatilityGuard (Priority-1) is checked first.**  If the market is
        in an EXTREME shock state the entire broadcast is blocked immediately.
        SEVERE / MODERATE / MINOR shocks reduce the ``size_usd`` for every
        account proportionally.

        Parameters
        ----------
        signal:
            The trade signal to broadcast.

        Returns
        -------
        BroadcastResult
            Per-account results plus aggregate metadata.
        """
        t_start = time.monotonic()

        # ── Priority-1: Volatility Guard ─────────────────────────────────
        guard_result = self._run_volatility_guard(signal.symbol)

        if not guard_result.allowed:
            logger.warning(
                "SignalBroadcaster BLOCKED (VolatilityGuard) | %s | severity=%s | %s",
                signal.symbol, guard_result.severity, guard_result.reason,
            )
            return BroadcastResult(
                success=False,
                symbol=signal.symbol,
                side=signal.side,
                size_usd=signal.size_usd,
                volatility_blocked=True,
                volatility_severity=guard_result.severity,
                size_scale_applied=0.0,
                error=guard_result.reason,
            )

        # Apply size scaling from volatility guard
        effective_size = signal.size_usd * guard_result.size_scale
        if guard_result.size_scale < 1.0:
            logger.info(
                "SignalBroadcaster: size scaled %.0f%% due to volatility %s | "
                "$%.2f -> $%.2f",
                guard_result.size_scale * 100, guard_result.severity,
                signal.size_usd, effective_size,
            )

        # ── Broadcast to each account ─────────────────────────────────────
        account_ids = signal.account_ids or ["default"]
        account_results: List[AccountResult] = []

        for account_id in account_ids:
            fraction = signal.account_fractions.get(account_id, 1.0)
            account_size = effective_size * fraction

            ar = self._execute_for_account(
                account_id=account_id,
                signal=signal,
                size_usd=account_size,
            )
            account_results.append(ar)

        any_success = any(r.success for r in account_results)
        total_ms = (time.monotonic() - t_start) * 1000

        logger.info(
            "SignalBroadcaster: broadcast complete | %s %s | accounts=%d "
            "succeeded=%d failed=%d | %.0f ms",
            signal.side.upper(), signal.symbol,
            len(account_ids),
            sum(1 for r in account_results if r.success),
            sum(1 for r in account_results if not r.success),
            total_ms,
        )

        return BroadcastResult(
            success=any_success,
            symbol=signal.symbol,
            side=signal.side,
            size_usd=signal.size_usd,
            volatility_severity=guard_result.severity,
            size_scale_applied=guard_result.size_scale,
            account_results=account_results,
        )

    # Alias for backward compatibility / direct callers
    broadcast = execute_across_accounts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_volatility_guard(self, symbol: str):
        """Run VolatilityGuard and return a result (fail-open on error)."""
        if self._guard is None:
            from types import SimpleNamespace
            return SimpleNamespace(
                allowed=True, size_scale=1.0, severity="NONE",
                reason="guard unavailable -- passing through",
            )
        try:
            return self._guard.check(symbol=symbol)
        except Exception as exc:
            logger.warning("SignalBroadcaster: VolatilityGuard.check error: %s", exc)
            from types import SimpleNamespace
            return SimpleNamespace(
                allowed=True, size_scale=1.0, severity="NONE",
                reason=f"guard error: {exc}",
            )

    def _execute_for_account(
        self,
        account_id: str,
        signal: BroadcastSignal,
        size_usd: float,
    ) -> AccountResult:
        """Execute a trade for a single account via the ExecutionPipeline."""
        t0 = time.monotonic()

        if self._pipeline is None:
            return AccountResult(
                account_id=account_id,
                success=False,
                error="ExecutionPipeline unavailable",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        try:
            from bot.execution_pipeline import PipelineRequest  # type: ignore
        except ImportError:
            try:
                from execution_pipeline import PipelineRequest  # type: ignore
            except ImportError:
                return AccountResult(
                    account_id=account_id,
                    success=False,
                    error="PipelineRequest type not importable",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

        try:
            req = PipelineRequest(
                symbol=signal.symbol,
                side=signal.side,
                size_usd=size_usd,
                strategy=signal.strategy,
                order_type=signal.order_type,
                asset_class=signal.asset_class,
            )
            result = self._pipeline.execute(req)
            latency = (time.monotonic() - t0) * 1000
            return AccountResult(
                account_id=account_id,
                success=result.success,
                fill_price=result.fill_price,
                filled_size_usd=result.filled_size_usd,
                broker=result.broker,
                error=result.error or "",
                latency_ms=latency,
            )
        except Exception as exc:
            logger.error(
                "SignalBroadcaster: account %s execution error: %s",
                account_id, exc,
            )
            return AccountResult(
                account_id=account_id,
                success=False,
                error=str(exc),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

    @staticmethod
    def _load_guard():
        """Load the VolatilityGuard (Priority-1 gate)."""
        for mod_name in ("bot.volatility_guard", "volatility_guard"):
            try:
                mod = __import__(mod_name, fromlist=["get_volatility_guard"])
                g = mod.get_volatility_guard()
                logger.info("SignalBroadcaster: VolatilityGuard loaded from %s", mod_name)
                return g
            except Exception as exc:
                logger.debug("SignalBroadcaster: could not load guard %s: %s", mod_name, exc)
        logger.warning(
            "SignalBroadcaster: VolatilityGuard unavailable -- Priority-1 gate disabled"
        )
        return None

    @staticmethod
    def _load_pipeline():
        """Load the ExecutionPipeline."""
        for mod_name in ("bot.execution_pipeline", "execution_pipeline"):
            try:
                mod = __import__(mod_name, fromlist=["get_execution_pipeline"])
                p = mod.get_execution_pipeline()
                logger.info("SignalBroadcaster: ExecutionPipeline loaded from %s", mod_name)
                return p
            except Exception as exc:
                logger.debug("SignalBroadcaster: could not load pipeline %s: %s", mod_name, exc)
        logger.warning("SignalBroadcaster: ExecutionPipeline unavailable")
        return None


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[SignalBroadcaster] = None
_instance_lock = threading.Lock()


def get_signal_broadcaster() -> SignalBroadcaster:
    """Return the process-wide :class:`SignalBroadcaster` singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SignalBroadcaster()
    return _instance
