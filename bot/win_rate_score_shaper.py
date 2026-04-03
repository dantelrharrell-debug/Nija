"""
Win-Rate Score Shaper
=====================

Tracks closed-trade win-rate *per market regime* and applies a
multiplicative shaping factor to the AI composite score before any
symbol is submitted to ``rank_and_select()``.

Why this matters
----------------
The existing ``AdaptiveThresholdController`` adjusts the global score floor
based on overall win-rate.  It has no memory of *which market condition*
produced good or bad trades.  During a CHOP regime the bot may consistently
lose because momentum signals misfires; during a BULL regime momentum is
reliable and signals should be trusted more.

This module fills that gap:

* In a regime where the bot historically wins > 65 % → boost composite by
  up to +30 % (factor 1.30×).
* In a regime where the bot historically wins < 45 % → dampen composite by
  up to -30 % (factor 0.70×).
* Neutral zone (45–65 %) → factor stays at 1.00× (no shaping).
* < ``MIN_HISTORY`` trades in a regime → factor stays 1.00× (cold start).

The shaping factor is applied as a *multiplicative* adjustment to the
composite score inside ``NijaAIEngine._compute_composite()``, which means:

* Score of 60 in a trusted BULL regime → 60 × 1.20 = 72  (moves to GOOD tier)
* Score of 40 in a losing CHOP regime → 40 × 0.80 = 32  (drops to FLOOR tier)

This naturally steers the bot away from regime conditions it historically
struggles with, without hardcoding any specific regime rules.

Architecture
------------
::

    WinRateScoreShaper  (singleton via get_win_rate_score_shaper())
    ├── _history: Dict[str, Deque[bool]]   — per-regime outcome window
    ├── record_outcome(regime_key, won)     — feed after every trade close
    ├── get_score_multiplier(regime)        — call in _compute_composite()
    └── get_status()                        — human-readable summary table

Regime key normalisation
------------------------
The shaper normalises regime values from any of the three existing regime
systems (MarketRegimeEngine Regime, MarketRegime enum, string labels) to
a canonical lowercase key before storing or looking up:

    Regime.BULL       → "bull"
    Regime.CHOP       → "chop"
    Regime.CRASH      → "crash"
    MarketRegime.TRENDING   → "trending"
    MarketRegime.RANGING    → "ranging"
    MarketRegime.VOLATILE   → "volatile"
    "strong_trend"          → "strong_trend"   (kept as-is)
    None / "UNKNOWN"        → "unknown"  (neutral, no shaping applied)

Environment variables
---------------------
NIJA_WRSS_ENABLED        Set to "0" to disable shaping (default: enabled).
NIJA_WRSS_WINDOW         Rolling window per regime in trades (default: 25).
NIJA_WRSS_MIN_HISTORY    Min trades before shaping activates (default: 5).
NIJA_WRSS_MAX_BOOST      Maximum upward multiplier, e.g. "1.30" (default).
NIJA_WRSS_MAX_DAMPEN     Minimum downward multiplier, e.g. "0.70" (default).
NIJA_WRSS_TARGET_FLOOR   Win-rate floor for neutral zone (default: 0.45).
NIJA_WRSS_TARGET_CEIL    Win-rate ceiling for neutral zone (default: 0.65).

Persistence
-----------
Outcomes are written to ``data/win_rate_by_regime.json`` on every
``record_outcome`` call so the history survives bot restarts.  The file is
loaded lazily on first access.  JSON I/O errors are silently absorbed.

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger("nija.win_rate_score_shaper")

# ---------------------------------------------------------------------------
# Configuration — tunable via environment variables
# ---------------------------------------------------------------------------
_ENABLED: bool = os.getenv("NIJA_WRSS_ENABLED", "1") not in ("0", "false", "False", "no")
_WINDOW: int = max(5, int(os.getenv("NIJA_WRSS_WINDOW", "25")))
_MIN_HISTORY: int = max(1, int(os.getenv("NIJA_WRSS_MIN_HISTORY", "5")))

# ---------------------------------------------------------------------------
# 5-tier stepped factor table  (env-var overridable)
# ---------------------------------------------------------------------------
# Each tier maps a win-rate band to a named multiplier.  Tiers are evaluated
# top-down; the first matching threshold wins.
#
#   Win-rate ≥ 72 %  → DOMINATING  (1.30× default)  strong trust in the regime
#   Win-rate ≥ 60 %  → STRONG      (1.15× default)  above-neutral performance
#   Win-rate > 45 %  → NEUTRAL     (1.05× default)  slight upward bias baseline
#   Win-rate > 30 %  → STRUGGLING  (0.90× default)  below-par; small dampen
#   Win-rate ≤ 30 %  → BROKEN      (0.70× default)  consistently losing; damp hard
#
# Legacy env vars MAX_BOOST / MAX_DAMPEN / TARGET_FLOOR / TARGET_CEIL are no
# longer read; use the named-tier vars below instead.
_FACTOR_DOMINATING: float = float(os.getenv("NIJA_WRSS_WINRATE_DOMINATING_FACTOR", "1.30"))
_FACTOR_STRONG:     float = float(os.getenv("NIJA_WRSS_WINRATE_STRONG_FACTOR",     "1.15"))
_FACTOR_NEUTRAL:    float = float(os.getenv("NIJA_WRSS_WINRATE_NEUTRAL_FACTOR",    "1.05"))
_FACTOR_STRUGGLING: float = float(os.getenv("NIJA_WRSS_WINRATE_STRUGGLING_FACTOR", "0.90"))
_FACTOR_BROKEN:     float = float(os.getenv("NIJA_WRSS_WINRATE_BROKEN_FACTOR",     "0.70"))

# Win-rate thresholds separating the 5 tiers (descending)
_WR_DOMINATING_THR: float = 0.72   # ≥ this → DOMINATING
_WR_STRONG_THR:     float = 0.60   # ≥ this → STRONG
_WR_STRUGGLING_THR: float = 0.45   # > this → NEUTRAL (45 % < wr < 60 %)
_WR_BROKEN_THR:     float = 0.30   # > this → STRUGGLING (30 % < wr ≤ 45 %)

_PERSIST_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "win_rate_by_regime.json",
)

# Regimes where we deliberately never apply shaping (not enough information
# or by policy — treat them as neutral regardless of sample history).
_NEUTRAL_REGIMES = frozenset({"unknown", "none", ""})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_regime(regime: Any) -> str:
    """
    Convert any regime representation to a canonical lowercase string key.

    Handles enum values, strings, and None gracefully.
    """
    if regime is None:
        return "unknown"
    # Enum: use .value if available
    raw = getattr(regime, "value", regime)
    return str(raw).lower().strip()


def _compute_factor(win_rate: float) -> float:
    """
    Map a historical win-rate to a score multiplier using a 5-tier stepped table.

    Tiers (evaluated top-down):
      DOMINATING  win_rate ≥ 72 %  →  _FACTOR_DOMINATING  (default 1.30×)
      STRONG      win_rate ≥ 60 %  →  _FACTOR_STRONG      (default 1.15×)
      NEUTRAL     win_rate > 45 %  →  _FACTOR_NEUTRAL     (default 1.05×)
      STRUGGLING  win_rate > 30 %  →  _FACTOR_STRUGGLING  (default 0.90×)
      BROKEN      win_rate ≤ 30 %  →  _FACTOR_BROKEN      (default 0.70×)

    All five factors are individually tunable via
    ``NIJA_WRSS_WINRATE_*_FACTOR`` environment variables.
    """
    if win_rate >= _WR_DOMINATING_THR:
        return _FACTOR_DOMINATING
    if win_rate >= _WR_STRONG_THR:
        return _FACTOR_STRONG
    if win_rate > _WR_STRUGGLING_THR:
        return _FACTOR_NEUTRAL
    if win_rate > _WR_BROKEN_THR:
        return _FACTOR_STRUGGLING
    return _FACTOR_BROKEN


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class WinRateScoreShaper:
    """
    Per-regime win-rate tracker that produces a score multiplier for use in
    ``NijaAIEngine._compute_composite()``.

    Thread-safe singleton — use ``get_win_rate_score_shaper()`` to obtain the
    shared instance.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Per-regime rolling outcome window:  regime_key → Deque[bool]
        self._history: Dict[str, Deque[bool]] = {}
        self._load_persist()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(self, regime: Any, won: bool) -> None:
        """
        Record the outcome of a closed trade under ``regime``.

        Parameters
        ----------
        regime : Regime enum / MarketRegime enum / string / None
            The market regime active when the trade was *opened* (or closed —
            either is acceptable as a consistent policy).
        won    : True if the trade was profitable, False otherwise.
        """
        if not _ENABLED:
            return
        key = _normalise_regime(regime)
        if key in _NEUTRAL_REGIMES:
            return
        with self._lock:
            if key not in self._history:
                self._history[key] = deque(maxlen=_WINDOW)
            self._history[key].append(bool(won))
        self._save_persist()

    def get_score_multiplier(self, regime: Any) -> float:
        """
        Return the score shaping multiplier for ``regime``.

        Returns 1.0 (no shaping) when:
        * ``NIJA_WRSS_ENABLED=0``
        * regime is None / "UNKNOWN"
        * fewer than ``_MIN_HISTORY`` outcomes recorded for this regime

        Otherwise returns a value in ``[_MAX_DAMPEN, _MAX_BOOST]`` derived
        from the rolling win-rate for this regime.
        """
        if not _ENABLED:
            return 1.0
        key = _normalise_regime(regime)
        if key in _NEUTRAL_REGIMES:
            return 1.0
        with self._lock:
            history = self._history.get(key)
        if not history or len(history) < _MIN_HISTORY:
            return 1.0
        wr = sum(history) / len(history)
        factor = _compute_factor(wr)
        logger.debug(
            "[WRSS] %s  win_rate=%.1f%%  n=%d  multiplier=×%.3f",
            key.upper(), wr * 100, len(history), factor,
        )
        return factor

    def get_status(self) -> str:
        """
        Return a multi-line human-readable summary of all tracked regimes.

        Example output::

            ┌─────────────────────────────────────────────────────────────┐
            │  Win-Rate Score Shaper — per-regime summary                 │
            ├──────────────────┬────────┬────────┬────────┬──────────────┤
            │ Regime           │  Trades│  Win % │  Mult  │  Status      │
            ├──────────────────┼────────┼────────┼────────┼──────────────┤
            │ bull             │    18  │  72.2% │ ×1.21  │  ✅ boosting │
            │ chop             │    12  │  33.3% │ ×0.78  │  ⚠️ dampened │
            │ trending         │     4  │  75.0% │ ×1.00  │  🔶 warming  │
            └──────────────────┴────────┴────────┴────────┴──────────────┘
        """
        with self._lock:
            snapshot = {k: list(v) for k, v in self._history.items()}

        if not snapshot:
            return "Win-Rate Score Shaper: no trade history recorded yet"

        lines = ["Win-Rate Score Shaper — per-regime performance:"]
        header = f"  {'Regime':<18} {'Trades':>6}  {'Win%':>6}  {'Mult':>6}  Status"
        lines.append(header)
        lines.append("  " + "─" * (len(header) - 2))

        for key in sorted(snapshot):
            outcomes = snapshot[key]
            n = len(outcomes)
            if n == 0:
                continue
            wr = sum(outcomes) / n
            factor = _compute_factor(wr) if n >= _MIN_HISTORY else 1.0
            if n < _MIN_HISTORY:
                status = "🔶 warming up"
            elif factor >= _FACTOR_DOMINATING:
                status = f"🚀 dominating ×{factor:.2f}"
            elif factor >= _FACTOR_STRONG:
                status = f"✅ strong ×{factor:.2f}"
            elif factor > 1.0:
                status = f"📈 neutral+ ×{factor:.2f}"
            elif factor >= _FACTOR_STRUGGLING:
                status = f"⚠️  struggling ×{factor:.2f}"
            else:
                status = f"🔴 broken ×{factor:.2f}"
            lines.append(
                f"  {key:<18} {n:>6}  {wr*100:>5.1f}%  ×{factor:.3f}  {status}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_persist(self) -> None:
        """Atomically persist the current outcome history to JSON."""
        try:
            os.makedirs(os.path.dirname(_PERSIST_PATH), exist_ok=True)
            with self._lock:
                data = {k: list(v) for k, v in self._history.items()}
            tmp = _PERSIST_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, _PERSIST_PATH)
        except Exception as exc:
            logger.debug("[WRSS] persist save failed: %s", exc)

    def _load_persist(self) -> None:
        """Load persisted outcome history if the file exists."""
        try:
            if not os.path.exists(_PERSIST_PATH):
                return
            with open(_PERSIST_PATH, "r", encoding="utf-8") as fh:
                data: Dict[str, Any] = json.load(fh)
            loaded = 0
            for key, outcomes in data.items():
                if isinstance(outcomes, list):
                    dq: Deque[bool] = deque(
                        (bool(v) for v in outcomes[-_WINDOW:]),
                        maxlen=_WINDOW,
                    )
                    self._history[key] = dq
                    loaded += len(dq)
            if loaded:
                logger.info(
                    "[WRSS] Loaded %d outcomes across %d regimes from %s",
                    loaded, len(self._history), _PERSIST_PATH,
                )
        except Exception as exc:
            logger.debug("[WRSS] persist load failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------
_shaper: Optional[WinRateScoreShaper] = None
_shaper_lock = threading.Lock()


def get_win_rate_score_shaper() -> Optional[WinRateScoreShaper]:
    """
    Return the module-level singleton :class:`WinRateScoreShaper`.

    Returns ``None`` when ``NIJA_WRSS_ENABLED=0``.
    """
    if not _ENABLED:
        return None
    global _shaper
    if _shaper is None:
        with _shaper_lock:
            if _shaper is None:
                _shaper = WinRateScoreShaper()
                logger.info(
                    "[WRSS] WinRateScoreShaper initialised "
                    "(window=%d, min_history=%d, "
                    "factors: dominating=×%.2f strong=×%.2f neutral=×%.2f "
                    "struggling=×%.2f broken=×%.2f, "
                    "thresholds: ≥%.0f%%=dom ≥%.0f%%=strong >%.0f%%=neutral >%.0f%%=struggling)",
                    _WINDOW, _MIN_HISTORY,
                    _FACTOR_DOMINATING, _FACTOR_STRONG, _FACTOR_NEUTRAL,
                    _FACTOR_STRUGGLING, _FACTOR_BROKEN,
                    _WR_DOMINATING_THR * 100, _WR_STRONG_THR * 100,
                    _WR_STRUGGLING_THR * 100, _WR_BROKEN_THR * 100,
                )
    return _shaper
