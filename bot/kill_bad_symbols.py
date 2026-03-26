"""
NIJA Kill Bad Symbols Memory
==============================
Tracks per-symbol trade history and automatically reduces position-size
exposure on consistently losing coins.

Exposure multiplier ladder (applied after MIN_TRADES_GATE trades recorded):

    win_rate >= 50%  ->  1.00x  (full size — healthy symbol)
    win_rate >= 40%  ->  0.75x  (reduce by 25%)
    win_rate >= 30%  ->  0.50x  (halve the position)
    win_rate >= 20%  ->  0.25x  (quarter size — near-kill)
    win_rate <  20%  ->  0.00x  (skip entirely — symbol is "killed")

A symbol is automatically revived once its rolling win rate recovers above
the REVIVE_WIN_RATE threshold (default 50%).

Persistence
-----------
State is written to ``data/bad_symbols.json`` on every trade so symbol
memory survives restarts and redeployments.

Usage
-----
    from bot.kill_bad_symbols import get_kill_bad_symbols

    kbs = get_kill_bad_symbols()

    if kbs.should_skip(symbol):
        continue

    multiplier = kbs.get_exposure_multiplier(symbol)
    position_size *= multiplier

    # after trade closes:
    kbs.record_trade(symbol, is_win=is_win)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from typing import Deque, Dict, Optional

logger = logging.getLogger("nija.kill_bad_symbols")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROLLING_WINDOW:    int   = 20    # most recent N trades considered per symbol
MIN_TRADES_GATE:   int   = 5     # min trades before exposure is reduced
REVIVE_WIN_RATE:   float = 0.50  # win rate needed to restore full exposure

_WR_LADDER = [
    (0.50, 1.00),
    (0.40, 0.75),
    (0.30, 0.50),
    (0.20, 0.25),
    (0.00, 0.00),
]

_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "bad_symbols.json"
)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class KillBadSymbols:
    """Thread-safe per-symbol exposure manager."""

    def __init__(self, rolling_window: int = ROLLING_WINDOW) -> None:
        self._rolling_window = rolling_window
        self._lock = threading.Lock()
        self._history: Dict[str, Deque[int]] = {}   # symbol -> deque of 1/0
        self._load()
        logger.info(
            "✅ KillBadSymbols initialised — "
            "window=%d  min_gate=%d  revive_wr=%.0f%%",
            self._rolling_window, MIN_TRADES_GATE, REVIVE_WIN_RATE * 100,
        )

    # ── Persistence ─────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if not os.path.exists(_DATA_PATH):
                return
            with open(_DATA_PATH, encoding="utf-8") as f:
                raw: dict = json.load(f)
            for sym, results in raw.items():
                dq: Deque[int] = deque(
                    results[-self._rolling_window:],
                    maxlen=self._rolling_window,
                )
                self._history[sym] = dq
            logger.info(
                "   KillBadSymbols: loaded %d symbol records from disk",
                len(self._history),
            )
        except Exception as exc:
            logger.warning("KillBadSymbols: could not load state: %s", exc)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(_DATA_PATH)), exist_ok=True)
            data = {sym: list(dq) for sym, dq in self._history.items()}
            with open(_DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as exc:
            logger.warning("KillBadSymbols: could not save state: %s", exc)

    # ── Public API ───────────────────────────────────────────────────────────

    def record_trade(self, symbol: str, is_win: bool) -> None:
        """Record the outcome of a trade for *symbol* (1=win, 0=loss)."""
        with self._lock:
            if symbol not in self._history:
                self._history[symbol] = deque(maxlen=self._rolling_window)
            self._history[symbol].append(1 if is_win else 0)
            n  = len(self._history[symbol])
            wr = sum(self._history[symbol]) / n
            mult = self._wr_to_multiplier(wr, n)
            if mult < 1.0:
                logger.info(
                    "   KillBadSymbols [%s]: win_rate=%.0f%%  exposure=%.2fx  "
                    "trades_in_window=%d",
                    symbol, wr * 100, mult, n,
                )
            self._save()

    def get_win_rate(self, symbol: str) -> float:
        """Return the rolling win rate for *symbol* (0.0-1.0). 1.0 if unseen."""
        with self._lock:
            dq = self._history.get(symbol)
            if not dq:
                return 1.0
            return sum(dq) / len(dq)

    def get_exposure_multiplier(self, symbol: str) -> float:
        """
        Return the position-size multiplier for *symbol* (0.0-1.0).

        Only reduces below 1.0 after at least MIN_TRADES_GATE recorded trades.
        """
        with self._lock:
            dq = self._history.get(symbol)
            if not dq or len(dq) < MIN_TRADES_GATE:
                return 1.0
            wr = sum(dq) / len(dq)
            return self._wr_to_multiplier(wr, len(dq))

    def should_skip(self, symbol: str) -> bool:
        """Return True when the symbol's exposure multiplier has reached 0."""
        return self.get_exposure_multiplier(symbol) == 0.0

    def get_report(self, top_n: int = 15) -> dict:
        """Return a snapshot of the worst-performing symbols for logging."""
        with self._lock:
            rows = []
            for sym, dq in self._history.items():
                n = len(dq)
                if n < MIN_TRADES_GATE:
                    continue
                wr   = sum(dq) / n
                mult = self._wr_to_multiplier(wr, n)
                rows.append({
                    "symbol":       sym,
                    "win_rate":     round(wr, 3),
                    "total_trades": n,
                    "exposure":     mult,
                })
            rows.sort(key=lambda r: r["win_rate"])
            return {
                "bad_symbols":   rows[:top_n],
                "total_tracked": len(self._history),
            }

    # ── Private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _wr_to_multiplier(win_rate: float, n_trades: int) -> float:
        if n_trades < MIN_TRADES_GATE:
            return 1.0
        for wr_floor, mult in _WR_LADDER:
            if win_rate >= wr_floor:
                return mult
        return 0.0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[KillBadSymbols] = None
_lock = threading.Lock()


def get_kill_bad_symbols() -> KillBadSymbols:
    """Return the process-wide singleton KillBadSymbols."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = KillBadSymbols()
    return _instance
