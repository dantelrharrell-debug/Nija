"""
NIJA First-Trade Observer
=========================

Provides end-to-end signal → execution chain observability for the **first
confirmed trade** after bot startup.  This answers the most common deployment
question: "Is the signal-to-fill pipeline actually working?"

Checkpoints (in order)
-----------------------
1. SIGNAL_GENERATED  — a raw RSI / strategy signal was emitted for a symbol.
2. GATES_PASSED      — the signal cleared all entry gates (regime, risk,
                       robustness, confidence score, etc.).
3. SIZE_COMPUTED     — a non-zero USD position size was determined.
4. ORDER_SUBMITTED   — the order was sent to the exchange.
5. ORDER_FILLED      — the exchange confirmed the order as filled / open.
6. POSITION_CONFIRMED — the open-position register was updated.

Usage
-----
::

    from bot.first_trade_observer import get_first_trade_observer

    obs = get_first_trade_observer()

    # Inside the strategy loop — call at each checkpoint:
    obs.record(obs.SIGNAL_GENERATED, symbol="BTC-USD", detail="RSI crossover")
    obs.record(obs.GATES_PASSED,     symbol="BTC-USD")
    obs.record(obs.SIZE_COMPUTED,    symbol="BTC-USD", size_usd=33.12)
    obs.record(obs.ORDER_SUBMITTED,  symbol="BTC-USD", order_id="abc123")
    obs.record(obs.ORDER_FILLED,     symbol="BTC-USD", fill_price=105_000.0)
    obs.record(obs.POSITION_CONFIRMED, symbol="BTC-USD")

    # At any time — retrieve the report:
    print(obs.get_report())

    # Check whether the chain is complete:
    if obs.is_complete:
        logger.info("✅ First-trade chain fully confirmed")

Thread safety
-------------
All public methods are thread-safe.

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("nija.first_trade_observer")

# ---------------------------------------------------------------------------
# Checkpoint constants
# ---------------------------------------------------------------------------

SIGNAL_GENERATED   = "SIGNAL_GENERATED"
GATES_PASSED       = "GATES_PASSED"
SIZE_COMPUTED      = "SIZE_COMPUTED"
ORDER_SUBMITTED    = "ORDER_SUBMITTED"
ORDER_FILLED       = "ORDER_FILLED"
POSITION_CONFIRMED = "POSITION_CONFIRMED"

_ORDERED_CHECKPOINTS: List[str] = [
    SIGNAL_GENERATED,
    GATES_PASSED,
    SIZE_COMPUTED,
    ORDER_SUBMITTED,
    ORDER_FILLED,
    POSITION_CONFIRMED,
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CheckpointRecord:
    """A single checkpoint event in the execution chain."""
    checkpoint: str
    symbol: str
    timestamp: float = field(default_factory=time.time)
    detail: str = ""

    @property
    def ts_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S.%f")[:-3]


# ---------------------------------------------------------------------------
# Observer class
# ---------------------------------------------------------------------------

class FirstTradeObserver:
    """
    Tracks the first trade's signal → execution chain and emits a
    structured log report once the chain is complete (or on demand).

    After ``POSITION_CONFIRMED`` is reached the observer marks itself
    complete and no longer records new events (the first-trade story is done).
    """

    # Re-export checkpoint names as class attributes for ergonomic access.
    SIGNAL_GENERATED   = SIGNAL_GENERATED
    GATES_PASSED       = GATES_PASSED
    SIZE_COMPUTED      = SIZE_COMPUTED
    ORDER_SUBMITTED    = ORDER_SUBMITTED
    ORDER_FILLED       = ORDER_FILLED
    POSITION_CONFIRMED = POSITION_CONFIRMED

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Ordered list of recorded checkpoints (first symbol wins all slots)
        self._records: List[CheckpointRecord] = []
        # Which checkpoints we have seen (first-win per checkpoint name)
        self._seen: Dict[str, CheckpointRecord] = {}
        # The symbol that "owns" the first-trade chain
        self._symbol: Optional[str] = None
        self._complete: bool = False
        self._start_ts: float = time.time()

        logger.info(
            "🔭 FirstTradeObserver initialized — "
            "monitoring signal → fill chain for first trade"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        """True once POSITION_CONFIRMED has been recorded."""
        return self._complete

    @property
    def symbol(self) -> Optional[str]:
        """The symbol locked in as the first-trade candidate."""
        return self._symbol

    def record(
        self,
        checkpoint: str,
        symbol: str = "",
        detail: str = "",
        size_usd: float = 0.0,
        order_id: str = "",
        fill_price: float = 0.0,
    ) -> None:
        """
        Record progress at *checkpoint* for *symbol*.

        On the first call the symbol is locked in; subsequent calls for a
        different symbol are silently ignored (one first-trade at a time).

        Parameters
        ----------
        checkpoint : str
            One of the module-level checkpoint constants.
        symbol : str
            Trading pair (e.g. ``"BTC-USD"``).
        detail : str
            Optional freeform note attached to this checkpoint.
        size_usd : float
            USD position size (meaningful at SIZE_COMPUTED checkpoint).
        order_id : str
            Exchange order ID (meaningful at ORDER_SUBMITTED / ORDER_FILLED).
        fill_price : float
            Fill price (meaningful at ORDER_FILLED checkpoint).
        """
        with self._lock:
            if self._complete:
                return

            if checkpoint not in _ORDERED_CHECKPOINTS:
                logger.debug("FirstTradeObserver: unknown checkpoint %r — ignored", checkpoint)
                return

            # Lock in the symbol on first SIGNAL_GENERATED
            if self._symbol is None:
                if checkpoint == SIGNAL_GENERATED:
                    self._symbol = symbol
                else:
                    # Haven't seen SIGNAL_GENERATED yet — accept anyway
                    self._symbol = symbol

            # Ignore events for different symbols once a symbol is locked in
            if symbol and symbol != self._symbol:
                return

            # Skip duplicate checkpoints (first-win per checkpoint)
            if checkpoint in self._seen:
                return

            # Build detail string
            parts: List[str] = []
            if detail:
                parts.append(detail)
            if size_usd > 0:
                parts.append(f"size=${size_usd:.2f}")
            if order_id:
                parts.append(f"order_id={order_id}")
            if fill_price > 0:
                parts.append(f"fill=${fill_price:.4f}")
            full_detail = " | ".join(parts)

            rec = CheckpointRecord(
                checkpoint=checkpoint,
                symbol=self._symbol or symbol,
                detail=full_detail,
            )
            self._records.append(rec)
            self._seen[checkpoint] = rec

            logger.info(
                "🔭 [FirstTrade] %s ✅  symbol=%s  %s",
                checkpoint, rec.symbol, f"({full_detail})" if full_detail else "",
            )

            # Mark complete when the final checkpoint is reached
            if checkpoint == POSITION_CONFIRMED:
                self._complete = True
                elapsed = time.time() - self._start_ts
                logger.info(
                    "🎯 FIRST TRADE CHAIN COMPLETE — "
                    "signal → fill confirmed in %.1fs  [%s]",
                    elapsed, rec.symbol,
                )
                self._emit_full_report()

    def get_report(self) -> str:
        """
        Return a human-readable report of the current chain state.
        Safe to call at any time.
        """
        with self._lock:
            return self._build_report()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _emit_full_report(self) -> None:
        """Called internally (under lock) when the chain is complete."""
        report = self._build_report()
        for line in report.splitlines():
            logger.info(line)

    def _build_report(self) -> str:
        """Build the chain report string (caller must hold lock or not care)."""
        lines = [
            "",
            "═" * 70,
            "🔭  NIJA FIRST-TRADE EXECUTION CHAIN REPORT",
            "═" * 70,
        ]

        if self._symbol:
            lines.append(f"  Symbol: {self._symbol}")

        if not self._records:
            lines.append("  No checkpoints recorded yet.")
            lines.append("═" * 70)
            return "\n".join(lines)

        first_ts = self._records[0].timestamp
        prev_ts  = first_ts

        for cp in _ORDERED_CHECKPOINTS:
            if cp in self._seen:
                rec = self._seen[cp]
                elapsed_total = rec.timestamp - first_ts
                delta = rec.timestamp - prev_ts
                prev_ts = rec.timestamp
                detail_str = f"  ({rec.detail})" if rec.detail else ""
                lines.append(
                    f"  ✅ {cp:<22}  {rec.ts_str}  "
                    f"+{elapsed_total:>5.1f}s  Δ{delta:>5.2f}s{detail_str}"
                )
            else:
                lines.append(f"  ⏳ {cp:<22}  — not reached yet")

        status = "COMPLETE ✅" if self._complete else "IN PROGRESS ⏳"
        lines += [
            "",
            f"  Status: {status}",
            f"  Checkpoints: {len(self._seen)}/{len(_ORDERED_CHECKPOINTS)}",
            "═" * 70,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[FirstTradeObserver] = None
_instance_lock = threading.Lock()


def get_first_trade_observer() -> FirstTradeObserver:
    """Return the process-wide FirstTradeObserver singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = FirstTradeObserver()
    return _instance


def reset_first_trade_observer() -> None:
    """Reset the singleton (useful in tests or after manual override)."""
    global _instance
    with _instance_lock:
        _instance = None
