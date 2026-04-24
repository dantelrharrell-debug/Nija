"""
NIJA Copy Trading Engine
=========================

Replicates platform-account (master) trades into every connected user account
with proportional position sizing.

Architecture
------------
::

    CopyTradeEngine
        │
        ├── PlatformAccountLayer      — verify platform account presence
        ├── CrossAccountCapitalAllocator — compute per-user trade sizes
        ├── MultiAccountBrokerManager — iterate user brokers + execute orders
        └── TradeLedgerDB             — audit trail for every copy event

Signal flow
-----------
    Platform account executes a trade →
        trade_signal_emitter.emit() / broker.execute_order() →
            copy_engine.broadcast(signal) →
                for each connected user:
                    size = allocator.compute_user_size(user_id, platform_size_usd)
                    user_broker.execute_order(symbol, side, size, size_type="quote")
                    ledger.record_copy_trade(...)

Usage
-----
::

    from bot.copy_trade_engine import get_copy_engine, CopySignal

    engine = get_copy_engine()
    engine.attach(multi_account_manager)

    # Called by the platform account after every filled order:
    results = engine.broadcast(CopySignal(
        platform_trade_id="tid_001",
        symbol="BTC/USD",
        side="buy",
        platform_size_usd=300.0,
        exchange="KRAKEN",
        order_id="kraken_oid_xyz",
    ))

    for r in results:
        if r.success:
            print(f"  ✅ {r.user_id}: filled ${r.filled_usd:.2f}")
        else:
            print(f"  ❌ {r.user_id}: {r.error}")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.copy_trade_engine")

#: Maximum characters stored for error messages in audit records.
_MAX_ERROR_LENGTH = 120


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CopySignal:
    """Encapsulates a platform trade to be replicated into user accounts."""

    platform_trade_id: str
    """Unique identifier for the platform-side trade."""

    symbol: str
    """Trading symbol, e.g. ``"BTC/USD"``."""

    side: str
    """``"buy"`` or ``"sell"``."""

    platform_size_usd: float
    """Platform account trade size in USD (used as the scaling reference)."""

    exchange: str = "KRAKEN"
    """Exchange to replicate on (case-insensitive)."""

    order_id: str = ""
    """Platform broker order ID (for audit trail)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Extra data (RSI values, regime, confidence, etc.) for the ledger."""

    def __post_init__(self) -> None:
        self.side = self.side.lower()
        self.exchange = self.exchange.upper()
        if not self.platform_trade_id:
            self.platform_trade_id = str(uuid.uuid4())


@dataclass
class CopyResult:
    """Outcome of a single user-account copy execution."""

    user_id: str
    exchange: str
    success: bool
    filled_usd: float = 0.0
    order_id: str = ""
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: str = ""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CopyTradeEngine:
    """
    Replicates platform account trades into all connected user accounts.

    Attach the ``MultiAccountBrokerManager`` once at startup via
    ``attach()``.  The engine automatically refreshes user balances and
    computes proportional sizes on each ``broadcast()`` call.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._multi_manager = None          # set via attach()
        self._allocator = None              # CrossAccountCapitalAllocator
        self._ledger = None                 # TradeLedgerDB
        self._pal = None                    # PlatformAccountLayer

        self._load_dependencies()

        logger.info(
            "CopyTradeEngine initialised | allocator=%s | ledger=%s | pal=%s",
            self._allocator is not None,
            self._ledger is not None,
            self._pal is not None,
        )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def attach(self, multi_account_manager) -> None:
        """
        Attach the live ``MultiAccountBrokerManager`` so the engine can
        iterate user brokers and execute orders.

        Args:
            multi_account_manager: ``MultiAccountBrokerManager`` instance.
        """
        with self._lock:
            self._multi_manager = multi_account_manager
        logger.info(
            "[CopyEngine] attached MultiAccountBrokerManager — %d user(s) registered",
            len(getattr(multi_account_manager, "user_brokers", {})),
        )

    # ------------------------------------------------------------------
    # Core broadcast
    # ------------------------------------------------------------------

    def broadcast(self, signal: CopySignal) -> List[CopyResult]:
        """
        Replicate *signal* into every connected user account on the target
        exchange.

        Steps
        -----
        1. Verify that a NIJA platform account exists for ``signal.exchange``.
        2. Refresh live balances via the allocator.
        3. For every connected user broker on the target exchange:
           a. Compute proportional size via ``CrossAccountCapitalAllocator``.
           b. Skip if size is below minimum or allocation is not approved.
           c. Execute ``broker.execute_order(symbol, side, size, size_type="quote")``.
           d. Record the result to ``TradeLedgerDB``.
        4. Return a list of :class:`CopyResult` objects.

        Args:
            signal: The :class:`CopySignal` to replicate.

        Returns:
            List of :class:`CopyResult` — one entry per user account attempted.
        """
        results: List[CopyResult] = []

        # -- 1. Platform-presence gate -----------------------------------
        if self._pal is not None:
            try:
                if not self._pal.has_platform_account(signal.exchange):
                    logger.warning(
                        "[CopyEngine] broadcast blocked — no platform account for %s",
                        signal.exchange,
                    )
                    return results
            except Exception:
                pass

        with self._lock:
            multi_mgr = self._multi_manager

        if multi_mgr is None:
            logger.warning(
                "[CopyEngine] broadcast called before attach() — no manager attached"
            )
            return results

        # -- 2. Refresh balances -----------------------------------------
        if self._allocator is not None:
            try:
                self._allocator.refresh_balances(multi_mgr)
            except Exception as exc:
                logger.debug("[CopyEngine] balance refresh error: %s", exc)

        # -- 3. Iterate user brokers -------------------------------------
        try:
            user_brokers = multi_mgr.user_brokers
        except Exception as exc:
            logger.error("[CopyEngine] cannot access user_brokers: %s", exc)
            return results

        logger.info(
            "[CopyEngine] broadcasting %s %s $%.2f → %d user(s) on %s",
            signal.side.upper(), signal.symbol,
            signal.platform_size_usd,
            len(user_brokers),
            signal.exchange,
        )

        for user_id, brokers in user_brokers.items():
            for broker_type, broker in brokers.items():
                # Only replicate on the same exchange as the platform trade
                if broker_type.value.upper() != signal.exchange:
                    continue

                if not broker.connected:
                    results.append(CopyResult(
                        user_id=user_id,
                        exchange=signal.exchange,
                        success=False,
                        skipped=True,
                        skip_reason="broker not connected",
                    ))
                    continue

                # -- a. Compute proportional size -------------------------
                alloc = None
                if self._allocator is not None:
                    try:
                        alloc = self._allocator.compute_user_size(
                            user_id=user_id,
                            platform_size_usd=signal.platform_size_usd,
                            exchange=signal.exchange,
                        )
                    except Exception as exc:
                        logger.debug("[CopyEngine] allocator error for %s: %s", user_id, exc)

                if alloc is not None and not alloc.approved:
                    logger.info(
                        "[CopyEngine] %s/%s skipped — %s",
                        user_id, signal.exchange, alloc.reason,
                    )
                    results.append(CopyResult(
                        user_id=user_id,
                        exchange=signal.exchange,
                        success=False,
                        skipped=True,
                        skip_reason=alloc.reason,
                    ))
                    self._record(signal, user_id, "skipped", error=alloc.reason)
                    continue

                size_usd = alloc.allocated_size_usd if alloc is not None else signal.platform_size_usd

                # -- b. Execute order ------------------------------------
                try:
                    order_result = broker.execute_order(
                        symbol=signal.symbol,
                        side=signal.side,
                        quantity=size_usd,
                        size_type="quote",
                    )
                    is_dict = isinstance(order_result, dict)
                    status = order_result.get("status", "unknown") if is_dict else "unknown"
                    user_order_id = order_result.get("order_id", "") if is_dict else ""

                    success = status not in ("error", "failed", "skipped")
                    filled = size_usd if success else 0.0

                    result = CopyResult(
                        user_id=user_id,
                        exchange=signal.exchange,
                        success=success,
                        filled_usd=filled,
                        order_id=user_order_id,
                        error=order_result.get("error") if (is_dict and not success) else None,
                    )

                    if success:
                        logger.info(
                            "[CopyEngine] ✅ %s/%s filled $%.2f (order_id=%s)",
                            user_id, signal.exchange, filled, user_order_id,
                        )
                    else:
                        logger.warning(
                            "[CopyEngine] ❌ %s/%s failed — %s",
                            user_id, signal.exchange, status,
                        )

                    self._record(
                        signal, user_id,
                        "filled" if success else "failed",
                        user_order_id=user_order_id,
                        user_size=size_usd,
                        error=result.error,
                    )

                except Exception as exc:
                    logger.error(
                        "[CopyEngine] order execution exception for %s: %s",
                        user_id, exc,
                    )
                    err_msg = str(exc)[:_MAX_ERROR_LENGTH]
                    result = CopyResult(
                        user_id=user_id,
                        exchange=signal.exchange,
                        success=False,
                        error=err_msg,
                    )
                    self._record(signal, user_id, "failed", error=err_msg)

                results.append(result)

        # -- 4. Log summary ----------------------------------------------
        filled = sum(1 for r in results if r.success)
        skipped = sum(1 for r in results if r.skipped)
        failed = sum(1 for r in results if not r.success and not r.skipped)

        logger.info(
            "[CopyEngine] broadcast complete: filled=%d skipped=%d failed=%d",
            filled, skipped, failed,
        )
        return results

    # ------------------------------------------------------------------
    # Convenience: broadcast from a plain dict (legacy compatibility)
    # ------------------------------------------------------------------

    def broadcast_dict(self, signal_dict: Dict[str, Any]) -> List[CopyResult]:
        """
        Convenience wrapper that converts a plain dict to a :class:`CopySignal`
        and calls ``broadcast()``.

        Expected keys: ``symbol``, ``side``, ``platform_size_usd``,
        ``exchange`` (optional), ``platform_trade_id`` (optional),
        ``order_id`` (optional).
        """
        sig = CopySignal(
            platform_trade_id=signal_dict.get("platform_trade_id", str(uuid.uuid4())),
            symbol=signal_dict.get("symbol", ""),
            side=signal_dict.get("side", "buy"),
            platform_size_usd=float(signal_dict.get("platform_size_usd", 0.0)),
            exchange=signal_dict.get("exchange", "KRAKEN"),
            order_id=signal_dict.get("order_id", ""),
            metadata={k: v for k, v in signal_dict.items()
                      if k not in ("symbol", "side", "platform_size_usd",
                                   "exchange", "platform_trade_id", "order_id")},
        )
        return self.broadcast(sig)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(
        self,
        signal: CopySignal,
        user_id: str,
        status: str,
        user_order_id: str = "",
        user_size: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """Write a copy-trade audit record to the TradeLedgerDB."""
        if self._ledger is None:
            return
        try:
            self._ledger.record_copy_trade(
                platform_trade_id=signal.platform_trade_id,
                master_symbol=signal.symbol,
                master_side=signal.side,
                master_order_id=signal.order_id or None,
                platform_user_id="platform",
                user_id=user_id,
                user_status=status,
                user_order_id=user_order_id or None,
                user_error=error,
                user_size=user_size,
            )
        except Exception as exc:
            logger.debug("[CopyEngine] ledger record error: %s", exc)

    def _load_dependencies(self) -> None:
        """Best-effort load of all collaborator singletons."""
        # PlatformAccountLayer
        for mod_name in ("bot.platform_account_layer", "platform_account_layer"):
            try:
                mod = __import__(mod_name, fromlist=["get_platform_account_layer"])
                self._pal = mod.get_platform_account_layer()
                break
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("[CopyEngine] PAL load error: %s", exc)

        # CrossAccountCapitalAllocator
        for mod_name in ("bot.cross_account_capital_allocator", "cross_account_capital_allocator"):
            try:
                mod = __import__(mod_name, fromlist=["get_cross_account_allocator"])
                self._allocator = mod.get_cross_account_allocator()
                break
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("[CopyEngine] allocator load error: %s", exc)

        # TradeLedgerDB
        for mod_name in ("bot.trade_ledger_db", "trade_ledger_db"):
            try:
                mod = __import__(mod_name, fromlist=["get_trade_ledger_db"])
                self._ledger = mod.get_trade_ledger_db()
                break
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("[CopyEngine] ledger load error: %s", exc)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_ENGINE: Optional[CopyTradeEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_copy_engine() -> CopyTradeEngine:
    """Return the process-wide :class:`CopyTradeEngine` singleton."""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = CopyTradeEngine()
                logger.info("[CopyEngine] singleton created — ready to broadcast")
    return _ENGINE
