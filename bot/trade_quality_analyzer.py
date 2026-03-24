"""
NIJA Trade Quality Analyzer
=============================

Post-trade intelligence layer that records per-trade execution quality and
feeds the findings back into the bot's entry gates.

Tracked per trade
-----------------
* **Entry confidence**      — signal confidence score at entry
* **Market regime**         — regime at time of entry (e.g. BULL, CHOP)
* **Time held**             — duration from entry to exit in minutes
* **Slippage**              — execution slippage in basis points
* **Realised PnL**          — actual PnL in USD
* **Expected PnL**          — projected PnL based on TP/SL ratio at entry
* **Quality grade**         — A / B / C / D assigned post-exit

Quality grade rules
--------------------
::

  A — pnl ≥ expected AND win
  B — pnl > 0 AND pnl < expected  (partial winner)
  C — pnl < 0 AND pnl > –expected (controlled loss)
  D — pnl ≤ –expected              (full stop-out or worse)

Feedback hooks
--------------
* :meth:`get_confidence_gate_delta`  — delta (positive = tighten) to add to the
  minimum confidence threshold, derived from recent A/B vs C/D ratios.
* :meth:`get_regime_quality_map`     — which regimes produce the best trades.
* :meth:`get_symbol_quality`         — per-symbol quality breakdown.
* :meth:`get_optimal_hold_range`     — (min, max) hold-time in minutes where
  win rate is highest.

Singleton usage
---------------
::

    from bot.trade_quality_analyzer import get_trade_quality_analyzer

    analyzer = get_trade_quality_analyzer()

    # At entry — record context and receive a token:
    token = analyzer.record_entry(
        symbol="BTC-USD",
        confidence=0.78,
        regime="BULL",
        entry_price=65_000.0,
        expected_pnl_usd=45.0,
    )

    # At exit — complete the record:
    result = analyzer.record_exit(
        token=token,
        exit_price=65_450.0,
        fill_price=65_440.0,   # actual fill (for slippage calc)
        pnl_usd=43.5,
    )
    print(result.grade)          # "A"
    print(result.slippage_bps)   # 0.15

    # Before the next entry — get feedback:
    delta = analyzer.get_confidence_gate_delta()  # e.g. +0.03 → tighten gate

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.trade_quality_analyzer")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WINDOW: int = 100           # rolling window for global stats
GRADE_CONF_DELTA_STEP: float = 0.02  # step size for confidence gate adjustment
MAX_CONF_DELTA: float = 0.08         # max tightening applied to confidence gate
MIN_CONF_DELTA: float = -0.04        # max loosening applied to confidence gate


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeEntry:
    """In-flight trade record created at entry."""
    token: str
    symbol: str
    confidence: float
    regime: str
    entry_price: float
    expected_pnl_usd: float
    entry_time: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TradeQuality:
    """Complete post-exit quality record for one trade."""
    token: str
    symbol: str
    confidence: float
    regime: str
    entry_price: float
    exit_price: float
    fill_price: float
    expected_pnl_usd: float
    actual_pnl_usd: float
    slippage_bps: float         # execution slippage in basis points
    hold_minutes: float         # time held in minutes
    grade: str                  # A / B / C / D
    is_win: bool
    entry_time: datetime
    exit_time: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "symbol": self.symbol,
            "confidence": round(self.confidence, 4),
            "regime": self.regime,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "fill_price": self.fill_price,
            "expected_pnl_usd": round(self.expected_pnl_usd, 2),
            "actual_pnl_usd": round(self.actual_pnl_usd, 2),
            "slippage_bps": round(self.slippage_bps, 3),
            "hold_minutes": round(self.hold_minutes, 1),
            "grade": self.grade,
            "is_win": self.is_win,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
        }


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------

class TradeQualityAnalyzer:
    """
    Scores every closed trade and derives actionable feedback for the entry
    pipeline.

    Thread-safe; use :func:`get_trade_quality_analyzer` for the process-wide
    singleton.
    """

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        self._window = window
        self._lock = threading.Lock()

        # Pending (open) trades, keyed by token
        self._open: Dict[str, TradeEntry] = {}

        # Rolling window of closed TradeQuality records
        self._closed: Deque[TradeQuality] = deque(maxlen=window)

        # Per-symbol record window
        self._by_symbol: Dict[str, Deque[TradeQuality]] = {}

        logger.info(
            "TradeQualityAnalyzer initialised | window=%d", window
        )

    # ------------------------------------------------------------------
    # Entry / exit recording
    # ------------------------------------------------------------------

    def record_entry(
        self,
        symbol: str,
        confidence: float,
        regime: str,
        entry_price: float,
        expected_pnl_usd: float = 0.0,
    ) -> str:
        """
        Record trade entry context and return a tracking token.

        Call :meth:`record_exit` with the returned token when the trade closes.

        Parameters
        ----------
        symbol:
            Trading pair, e.g. ``"BTC-USD"``.
        confidence:
            Signal confidence at entry [0, 1].
        regime:
            Market regime at entry (e.g. ``"BULL"``).
        entry_price:
            Entry execution price.
        expected_pnl_usd:
            Expected PnL based on TP/SL targets at entry.  Used for grade
            calculation.  Pass 0.0 to skip grade comparison.

        Returns
        -------
        str
            Opaque token — pass it to :meth:`record_exit`.
        """
        token = str(uuid.uuid4())
        with self._lock:
            self._open[token] = TradeEntry(
                token=token,
                symbol=symbol,
                confidence=confidence,
                regime=regime,
                entry_price=entry_price,
                expected_pnl_usd=expected_pnl_usd,
            )
        logger.debug(
            "TradeQualityAnalyzer entry recorded | symbol=%s token=%s",
            symbol, token[:8],
        )
        return token

    def record_exit(
        self,
        token: str,
        exit_price: float,
        pnl_usd: float,
        fill_price: Optional[float] = None,
    ) -> Optional[TradeQuality]:
        """
        Complete a previously recorded trade entry.

        Parameters
        ----------
        token:
            Token returned by :meth:`record_entry`.
        exit_price:
            Theoretical exit price (e.g. mid-price at close).
        pnl_usd:
            Actual realised PnL in USD.
        fill_price:
            Actual fill price (used for slippage calculation).  Defaults to
            ``exit_price`` when ``None``.

        Returns
        -------
        TradeQuality or None
            ``None`` if the token was not found (entry was not recorded).
        """
        with self._lock:
            entry = self._open.pop(token, None)
            if entry is None:
                logger.debug(
                    "TradeQualityAnalyzer: token %s not found in open trades", token[:8]
                )
                return None

            fill = fill_price if fill_price is not None else exit_price
            slippage_bps = self._calc_slippage(
                entry.entry_price, exit_price, fill
            )

            now = datetime.utcnow()
            hold_minutes = (now - entry.entry_time).total_seconds() / 60.0
            is_win = pnl_usd > 0
            grade = self._assign_grade(pnl_usd, entry.expected_pnl_usd)

            record = TradeQuality(
                token=token,
                symbol=entry.symbol,
                confidence=entry.confidence,
                regime=entry.regime,
                entry_price=entry.entry_price,
                exit_price=exit_price,
                fill_price=fill,
                expected_pnl_usd=entry.expected_pnl_usd,
                actual_pnl_usd=pnl_usd,
                slippage_bps=slippage_bps,
                hold_minutes=hold_minutes,
                grade=grade,
                is_win=is_win,
                entry_time=entry.entry_time,
                exit_time=now,
            )

            self._closed.append(record)
            if entry.symbol not in self._by_symbol:
                self._by_symbol[entry.symbol] = deque(maxlen=self._window)
            self._by_symbol[entry.symbol].append(record)

            logger.debug(
                "TradeQualityAnalyzer exit | symbol=%s grade=%s pnl=$%.2f "
                "slip=%.2fbps hold=%.1fmin",
                entry.symbol, grade, pnl_usd, slippage_bps, hold_minutes,
            )
            return record

    # ------------------------------------------------------------------
    # Feedback API
    # ------------------------------------------------------------------

    def get_confidence_gate_delta(self) -> float:
        """
        Return a confidence-threshold adjustment derived from recent A/B/C/D ratios.

        Negative → loosen the entry gate.
        Positive → tighten the entry gate.

        The delta is capped at [``MIN_CONF_DELTA``, ``MAX_CONF_DELTA``].
        """
        with self._lock:
            if len(self._closed) < 10:
                return 0.0

            ab_count = sum(1 for r in self._closed if r.grade in ("A", "B"))
            cd_count = sum(1 for r in self._closed if r.grade in ("C", "D"))
            total = ab_count + cd_count
            if total == 0:
                return 0.0

            quality_ratio = ab_count / total   # 0.0 → all bad, 1.0 → all good

            # quality > 0.65 → loosen slightly (more Bs and As than Cs and Ds)
            # quality < 0.45 → tighten
            if quality_ratio >= 0.65:
                steps = int((quality_ratio - 0.65) / 0.10) + 1
                delta = -GRADE_CONF_DELTA_STEP * steps
            elif quality_ratio < 0.45:
                steps = int((0.45 - quality_ratio) / 0.10) + 1
                delta = GRADE_CONF_DELTA_STEP * steps
            else:
                delta = 0.0

            return max(MIN_CONF_DELTA, min(MAX_CONF_DELTA, delta))

    def get_regime_quality_map(self) -> Dict[str, Dict[str, Any]]:
        """
        Return per-regime quality statistics.

        Returns a dict keyed by regime name with keys:
        ``trade_count``, ``win_rate``, ``avg_grade_score``, ``avg_pnl``.
        """
        with self._lock:
            regimes: Dict[str, List[TradeQuality]] = {}
            for r in self._closed:
                regimes.setdefault(r.regime, []).append(r)

            result: Dict[str, Dict[str, Any]] = {}
            for regime, records in regimes.items():
                n = len(records)
                win_rate = sum(1 for r in records if r.is_win) / n
                avg_pnl = sum(r.actual_pnl_usd for r in records) / n
                avg_grade = sum(self._grade_score(r.grade) for r in records) / n
                result[regime] = {
                    "trade_count": n,
                    "win_rate_pct": round(win_rate * 100, 1),
                    "avg_grade_score": round(avg_grade, 2),
                    "avg_pnl_usd": round(avg_pnl, 2),
                }
            return result

    def get_symbol_quality(self, symbol: str) -> Dict[str, Any]:
        """Return quality statistics for a specific ``symbol``."""
        with self._lock:
            records = list(self._by_symbol.get(symbol, []))
            if not records:
                return {"symbol": symbol, "trade_count": 0}

            n = len(records)
            win_rate = sum(1 for r in records if r.is_win) / n
            avg_pnl = sum(r.actual_pnl_usd for r in records) / n
            avg_slip = sum(r.slippage_bps for r in records) / n
            avg_hold = sum(r.hold_minutes for r in records) / n
            grade_dist = {g: 0 for g in ("A", "B", "C", "D")}
            for r in records:
                grade_dist[r.grade] = grade_dist.get(r.grade, 0) + 1

            return {
                "symbol": symbol,
                "trade_count": n,
                "win_rate_pct": round(win_rate * 100, 1),
                "avg_pnl_usd": round(avg_pnl, 2),
                "avg_slippage_bps": round(avg_slip, 3),
                "avg_hold_minutes": round(avg_hold, 1),
                "grade_distribution": grade_dist,
            }

    def get_optimal_hold_range(self) -> Tuple[float, float]:
        """
        Return the (min, max) hold-time range in minutes where win rate is highest.

        Divides all closed trades into quartiles by hold time and picks the
        quartile with the highest win rate.  Returns (q_low, q_high) for that
        quartile, or (0, float('inf')) if insufficient data.
        """
        with self._lock:
            if len(self._closed) < 20:
                return (0.0, float("inf"))

            sorted_trades = sorted(self._closed, key=lambda r: r.hold_minutes)
            n = len(sorted_trades)
            quartile_size = n // 4
            if quartile_size < 3:
                return (0.0, float("inf"))

            best_wr = -1.0
            best_range = (0.0, float("inf"))
            for i in range(4):
                start = i * quartile_size
                end = start + quartile_size if i < 3 else n
                chunk = sorted_trades[start:end]
                wr = sum(1 for r in chunk if r.is_win) / len(chunk)
                if wr > best_wr:
                    best_wr = wr
                    best_range = (
                        chunk[0].hold_minutes,
                        chunk[-1].hold_minutes,
                    )
            return best_range

    def get_report(self) -> Dict[str, Any]:
        """Return a full summary of recent trade quality."""
        with self._lock:
            n = len(self._closed)
            if n == 0:
                return {"trade_count": 0}

            grade_dist = {g: 0 for g in ("A", "B", "C", "D")}
            for r in self._closed:
                grade_dist[r.grade] = grade_dist.get(r.grade, 0) + 1

            win_rate = sum(1 for r in self._closed if r.is_win) / n
            avg_pnl = sum(r.actual_pnl_usd for r in self._closed) / n
            avg_slip = sum(r.slippage_bps for r in self._closed) / n
            avg_hold = sum(r.hold_minutes for r in self._closed) / n

            return {
                "trade_count": n,
                "open_trades": len(self._open),
                "win_rate_pct": round(win_rate * 100, 1),
                "avg_pnl_usd": round(avg_pnl, 2),
                "avg_slippage_bps": round(avg_slip, 3),
                "avg_hold_minutes": round(avg_hold, 1),
                "grade_distribution": grade_dist,
                "confidence_gate_delta": self.get_confidence_gate_delta(),
                "regime_quality": self.get_regime_quality_map(),
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_grade(actual_pnl: float, expected_pnl: float) -> str:
        """
        Assign a quality grade based on actual vs expected PnL.

            A — actual ≥ expected AND win
            B — actual > 0 AND actual < expected
            C — actual < 0 AND actual > −|expected|
            D — actual ≤ −|expected|
        """
        if actual_pnl >= 0:
            if expected_pnl <= 0 or actual_pnl >= expected_pnl:
                return "A"
            return "B"
        else:
            if expected_pnl > 0 and actual_pnl > -abs(expected_pnl):
                return "C"
            return "D"

    @staticmethod
    def _grade_score(grade: str) -> float:
        return {"A": 1.0, "B": 0.67, "C": 0.33, "D": 0.0}.get(grade, 0.5)

    @staticmethod
    def _calc_slippage(entry_price: float, exit_price: float, fill_price: float) -> float:
        """Return slippage in basis points relative to the exit price."""
        if exit_price <= 0:
            return 0.0
        return abs(fill_price - exit_price) / exit_price * 10_000.0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_ANALYZER_INSTANCE: Optional[TradeQualityAnalyzer] = None
_ANALYZER_LOCK = threading.Lock()


def get_trade_quality_analyzer(window: int = DEFAULT_WINDOW) -> TradeQualityAnalyzer:
    """
    Return the process-wide :class:`TradeQualityAnalyzer` singleton.

    ``window`` is only applied on the first call; subsequent calls return the
    existing instance.
    """
    global _ANALYZER_INSTANCE
    with _ANALYZER_LOCK:
        if _ANALYZER_INSTANCE is None:
            _ANALYZER_INSTANCE = TradeQualityAnalyzer(window)
    return _ANALYZER_INSTANCE


__all__ = [
    "TradeEntry",
    "TradeQuality",
    "TradeQualityAnalyzer",
    "get_trade_quality_analyzer",
]
