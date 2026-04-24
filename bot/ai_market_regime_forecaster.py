"""
NIJA AI Market Regime Forecaster
==================================

Predicts **upcoming** market regime changes **before** they occur, giving the
trading strategy time to adjust positions, tighten stops, or pause new entries.

Unlike a regime *classifier* (which labels the current regime), this module is
a regime *forecaster*: it analyses leading indicators and historical transition
patterns to estimate the probability of shifting into each regime within the
next N candles.

Core Methodology
----------------
1. **Feature Extraction** – derives 20+ leading indicators from price/volume:
   - Volatility acceleration (rate-of-change of ATR ratio)
   - Trend exhaustion score (ADX slope, RSI divergence)
   - Volume-weighted momentum shift
   - Bollinger Band squeeze / expansion phase
   - Candle pattern entropy (chaos metric)

2. **Markov Transition Model** – a self-updating transition probability matrix
   ``P[regime_i → regime_j]`` that learns from observed regime sequences in
   real time using an exponential moving average (EMA) update rule.

3. **Early-Warning Signals** – combinatorial rules that fire an alert when two
   or more leading indicators simultaneously suggest an imminent change, even
   before the classifier would detect it.

4. **Forecast Output** – probability distribution over next-regime labels plus:
   - A ``transition_risk`` score (0-100) indicating how likely the current
     regime is to change soon.
   - An ``expected_bars_to_transition`` estimate.
   - A list of triggered early-warning flags.

Architecture
------------
::

  ┌───────────────────────────────────────────────────────────────┐
  │              AIMarketRegimeForecaster                          │
  │                                                               │
  │  LeadingIndicatorEngine                                        │
  │  ├─ volatility_acceleration()                                  │
  │  ├─ trend_exhaustion_score()                                   │
  │  ├─ momentum_shift_score()                                     │
  │  ├─ bb_phase_score()                                           │
  │  └─ candle_entropy()                                           │
  │                                                               │
  │  MarkovTransitionModel                                         │
  │  ├─ update(current_regime, next_regime)                        │
  │  ├─ transition_probs(current_regime) → Dict[regime, float]     │
  │  └─ persist / load                                             │
  │                                                               │
  │  EarlyWarningSystem                                            │
  │  └─ check_warnings(features) → List[str]                       │
  │                                                               │
  │  forecast(df, indicators, current_regime) → ForecastResult     │
  └───────────────────────────────────────────────────────────────┘

Integration
-----------
    from bot.ai_market_regime_forecaster import get_ai_market_regime_forecaster

    forecaster = get_ai_market_regime_forecaster()

    result = forecaster.forecast(
        df=price_df,               # pandas DataFrame with OHLCV columns
        indicators=indicator_dict, # dict from indicators.py
        current_regime="RANGING",  # current regime string
    )

    if result.transition_risk > 70:
        logger.warning(f"Regime change imminent: {result.top_next_regime} "
                       f"({result.transition_probability:.0%})")

    if result.early_warnings:
        logger.warning(f"Early warnings: {result.early_warnings}")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.regime_forecaster")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Supported regime labels (superset – unknown regimes are treated as OTHER)
KNOWN_REGIMES: Tuple[str, ...] = (
    "STRONG_TREND",
    "WEAK_TREND",
    "RANGING",
    "EXPANSION",
    "MEAN_REVERSION",
    "VOLATILITY_EXPLOSION",
    "CONSOLIDATION",
    "BULL_TRENDING",
    "BEAR_TRENDING",
    "SIDEWAYS",
    "OTHER",
)

# EMA decay for Markov matrix update (higher = faster learning)
MARKOV_EMA_ALPHA: float = 0.05

# How many regime-observation bars we keep for entropy / short-cycle analysis
REGIME_HISTORY_MAXLEN: int = 200

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SoftFailMetrics:
    """
    Observability counters for soft-fail events inside the forecaster.

    A *soft fail* is any exception that is caught internally so that the
    forecaster can return a degraded-but-valid result rather than propagating
    the error to the caller.  Tracking these counters makes silent degradation
    visible in dashboards, logs, and alerting systems.

    Fields
    ------
    feature_extraction_failures : int
        LeadingIndicatorEngine.compute() raised an exception; forecaster fell
        back to an empty feature dict ``{}``.
    early_warning_rule_failures : int
        At least one rule lambda inside EarlyWarningSystem.check() raised an
        exception and was silently skipped.
    state_load_failures : int
        _load_state() failed to restore persisted Markov / history state;
        forecaster started fresh.
    state_save_failures : int
        _save_state() failed to persist state; in-memory state is unaffected.
    total_soft_fails : int
        Running total across all categories (convenient for a single threshold
        alert).
    """

    feature_extraction_failures: int = 0
    early_warning_rule_failures: int = 0
    state_load_failures: int = 0
    state_save_failures: int = 0
    total_soft_fails: int = 0

    def increment(self, counter: str) -> None:
        """Increment *counter* by 1 and update the running total."""
        if not hasattr(self, counter):
            raise ValueError(f"Unknown soft-fail counter: {counter!r}")
        setattr(self, counter, getattr(self, counter) + 1)
        self.total_soft_fails += 1

    def increment_by(self, counter: str, amount: int) -> None:
        """Increment *counter* by *amount* and update the running total."""
        if not hasattr(self, counter):
            raise ValueError(f"Unknown soft-fail counter: {counter!r}")
        setattr(self, counter, getattr(self, counter) + amount)
        self.total_soft_fails += amount

    def to_dict(self) -> Dict[str, int]:
        """Serialise to a plain dict suitable for JSON / logging."""
        return {
            "feature_extraction_failures": self.feature_extraction_failures,
            "early_warning_rule_failures": self.early_warning_rule_failures,
            "state_load_failures": self.state_load_failures,
            "state_save_failures": self.state_save_failures,
            "total_soft_fails": self.total_soft_fails,
        }


@dataclass
class ForecastResult:
    """Output of ``AIMarketRegimeForecaster.forecast()``."""

    current_regime: str
    # Probability distribution over next regimes
    next_regime_probs: Dict[str, float]
    # Convenience: highest-probability next regime
    top_next_regime: str
    transition_probability: float           # P(regime changes at all)
    # 0 = stable, 100 = imminent change
    transition_risk: float
    # Estimated bars until next regime change (NaN if unknown)
    expected_bars_to_transition: float
    # Human-readable early-warning flags
    early_warnings: List[str]
    # Raw leading-indicator features (for logging / debugging)
    leading_features: Dict[str, float]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "current_regime": self.current_regime,
            "next_regime_probs": {k: round(v, 4) for k, v in self.next_regime_probs.items()},
            "top_next_regime": self.top_next_regime,
            "transition_probability": round(self.transition_probability, 4),
            "transition_risk": round(self.transition_risk, 1),
            "expected_bars_to_transition": (
                round(self.expected_bars_to_transition, 1)
                if not math.isnan(self.expected_bars_to_transition)
                else None
            ),
            "early_warnings": self.early_warnings,
            "leading_features": {k: round(v, 4) for k, v in self.leading_features.items()},
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Leading Indicator Engine
# ---------------------------------------------------------------------------

class LeadingIndicatorEngine:
    """
    Extracts forward-looking features that tend to *precede* regime changes
    rather than confirm existing ones.
    """

    def compute(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        lookback: int = 20,
    ) -> Dict[str, float]:
        """
        Compute all leading indicators.

        Parameters
        ----------
        df : DataFrame with columns ``open``, ``high``, ``low``, ``close``, ``volume``
        indicators : dict from the bot's indicator module (RSI, ATR, ADX, BB …)
        lookback : number of bars to use for rolling calculations

        Returns
        -------
        dict of feature_name → float
        """
        features: Dict[str, float] = {}

        close = df["close"].values if "close" in df.columns else np.array([])
        high  = df["high"].values  if "high"  in df.columns else np.array([])
        low   = df["low"].values   if "low"   in df.columns else np.array([])
        vol   = df["volume"].values if "volume" in df.columns else np.array([])

        n = len(close)

        # -- 1. Volatility Acceleration -----------------------------------
        # ATR ratio (current ATR / N-bar average ATR) and its rate of change
        atr_val = float(indicators.get("atr", 0.0) or 0.0)
        atr_hist = self._rolling_atr(high, low, close, window=lookback)
        if len(atr_hist) > 1 and atr_hist[-1] > 0:
            atr_ratio = atr_val / atr_hist[-1]
            atr_accel = atr_ratio - (atr_val / atr_hist[-2] if atr_hist[-2] > 0 else atr_ratio)
        else:
            atr_ratio = 1.0
            atr_accel = 0.0
        features["atr_ratio"]        = atr_ratio
        features["atr_acceleration"] = atr_accel

        # -- 2. Trend Exhaustion Score ------------------------------------
        adx    = float(indicators.get("adx", 25.0) or 25.0)
        rsi_9  = float(indicators.get("rsi_9", 50.0) or 50.0)
        rsi_14 = float(indicators.get("rsi", 50.0) or indicators.get("rsi_14", 50.0) or 50.0)

        # ADX slope (rising ADX = trend strengthening; falling = exhaustion)
        adx_hist = self._rolling_adx_proxy(close, window=lookback)
        if len(adx_hist) >= 3:
            adx_slope = (adx_hist[-1] - adx_hist[-3]) / 2.0
        else:
            adx_slope = 0.0
        features["adx_slope"] = adx_slope

        # RSI divergence: price making higher highs but RSI making lower highs
        # (simplified: RSI distance from extreme)
        rsi_extreme_dist = min(abs(rsi_9 - 70), abs(rsi_9 - 30))
        features["rsi_extreme_distance"] = rsi_extreme_dist

        # Trend exhaustion composite (higher = more exhausted)
        exhaustion = 0.0
        if adx > 30 and adx_slope < -1.0:
            exhaustion += 0.4   # strong trend losing momentum
        if rsi_9 > 70 or rsi_9 < 30:
            exhaustion += 0.3   # RSI at extreme
        if rsi_9 > 75 or rsi_9 < 25:
            exhaustion += 0.2   # deeper extreme
        features["trend_exhaustion"] = min(1.0, exhaustion)

        # -- 3. Momentum Shift Score --------------------------------------
        if n >= lookback:
            momentum_fast = (close[-1] / close[-5] - 1.0) if n >= 5 else 0.0
            momentum_slow = (close[-1] / close[-lookback] - 1.0)
            momentum_divergence = abs(momentum_fast - momentum_slow * (5.0 / lookback))
        else:
            momentum_fast = momentum_slow = momentum_divergence = 0.0

        features["momentum_fast"]        = momentum_fast
        features["momentum_slow"]        = momentum_slow
        features["momentum_divergence"]  = momentum_divergence

        # -- 4. Bollinger Band Phase Score --------------------------------
        bb_upper = float(indicators.get("bb_upper", 0.0) or 0.0)
        bb_lower = float(indicators.get("bb_lower", 0.0) or 0.0)
        bb_mid   = float(indicators.get("bb_middle", 0.0) or
                        indicators.get("bb_mid", 0.0) or 0.0)

        current_price = close[-1] if n > 0 else 0.0
        bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0.02
        bb_pct_b = ((current_price - bb_lower) / (bb_upper - bb_lower)
                    if (bb_upper - bb_lower) > 0 else 0.5)
        features["bb_width"] = bb_width
        features["bb_pct_b"] = bb_pct_b

        # BB squeeze: width narrowing over last N bars → often precedes expansion
        if n >= lookback:
            bb_width_hist = self._rolling_bb_width(close, window=lookback)
            if len(bb_width_hist) >= 5:
                recent_mean_width = float(np.mean(bb_width_hist[-5:]))
                older_mean_width  = float(np.mean(bb_width_hist[:-5])) if len(bb_width_hist) > 5 else recent_mean_width
                bb_squeeze_score  = max(0.0, (older_mean_width - recent_mean_width) / max(older_mean_width, 1e-9))
            else:
                bb_squeeze_score = 0.0
        else:
            bb_squeeze_score = 0.0
        features["bb_squeeze_score"] = bb_squeeze_score

        # -- 5. Candle Pattern Entropy ------------------------------------
        if n >= 10:
            body_sizes = np.abs(close[-10:] - (df["open"].values[-10:] if "open" in df.columns else close[-10:]))
            # Normalise body sizes
            max_body = body_sizes.max()
            if max_body > 0:
                normalised = body_sizes / max_body
                # Shannon entropy as chaos metric (high = erratic candles)
                # Quantise into 5 bins
                hist, _ = np.histogram(normalised, bins=5, range=(0.0, 1.0))
                probs = hist / hist.sum()
                entropy = float(-np.sum(p * math.log2(p + 1e-9) for p in probs))
            else:
                entropy = 0.0
        else:
            entropy = 0.0
        features["candle_entropy"] = entropy

        # -- 6. Volume Surge Ratio ----------------------------------------
        if len(vol) >= lookback:
            vol_ma = float(np.mean(vol[-lookback:]))
            vol_ratio = float(vol[-1]) / vol_ma if vol_ma > 0 else 1.0
        else:
            vol_ratio = 1.0
        features["volume_surge_ratio"] = vol_ratio

        return features

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------

    @staticmethod
    def _rolling_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                     window: int = 14) -> np.ndarray:
        n = len(close)
        if n < 2:
            return np.array([0.0])
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:]  - close[:-1]),
            ),
        )
        if len(tr) < window:
            return np.array([tr.mean()]) if len(tr) > 0 else np.array([0.0])
        result = []
        for i in range(window - 1, len(tr)):
            result.append(tr[i - window + 1: i + 1].mean())
        return np.array(result)

    @staticmethod
    def _rolling_adx_proxy(close: np.ndarray, window: int = 14) -> np.ndarray:
        """Simplified proxy for ADX using absolute returns smoothed by EMA."""
        if len(close) < 2:
            return np.array([25.0])
        returns = np.abs(np.diff(np.log(close + 1e-9)))
        if len(returns) < window:
            return np.array([returns.mean() * 100.0])
        result = []
        for i in range(window - 1, len(returns)):
            result.append(returns[i - window + 1: i + 1].mean() * 1000.0)
        return np.array(result)

    @staticmethod
    def _rolling_bb_width(close: np.ndarray, window: int = 20) -> np.ndarray:
        """Rolling Bollinger Band width (std / mean)."""
        if len(close) < window:
            return np.array([np.std(close) / (np.mean(close) + 1e-9)])
        result = []
        for i in range(window - 1, len(close)):
            seg = close[i - window + 1: i + 1]
            result.append(np.std(seg) / (np.mean(seg) + 1e-9))
        return np.array(result)


# ---------------------------------------------------------------------------
# Markov Transition Model
# ---------------------------------------------------------------------------

class MarkovTransitionModel:
    """
    Self-updating first-order Markov model of regime transitions.

    The transition matrix ``P[from_regime][to_regime]`` is updated
    via EMA each time a regime change is observed, allowing the model
    to adapt to shifting market dynamics.
    """

    def __init__(self, alpha: float = MARKOV_EMA_ALPHA) -> None:
        self.alpha = alpha
        # P[from][to] = probability(next = to | current = from)
        self._matrix: Dict[str, Dict[str, float]] = defaultdict(
            lambda: defaultdict(lambda: 1.0 / len(KNOWN_REGIMES))
        )
        self._observation_counts: Dict[str, int] = defaultdict(int)

    def update(self, from_regime: str, to_regime: str) -> None:
        """Record a regime transition and update the EMA matrix."""
        from_r = self._normalise(from_regime)
        to_r   = self._normalise(to_regime)

        self._observation_counts[from_r] += 1
        row = self._matrix[from_r]

        # EMA-based update: increase probability of observed transition
        for r in KNOWN_REGIMES:
            current = row[r]
            target  = 1.0 if r == to_r else 0.0
            row[r]  = (1 - self.alpha) * current + self.alpha * target

        # Re-normalise row to ensure it sums to 1
        total = sum(row[r] for r in KNOWN_REGIMES)
        if total > 0:
            for r in KNOWN_REGIMES:
                row[r] /= total

    def transition_probs(self, from_regime: str) -> Dict[str, float]:
        """Return the probability distribution over next regimes."""
        from_r = self._normalise(from_regime)
        row = self._matrix[from_r]
        return {r: row[r] for r in KNOWN_REGIMES}

    def persistence_prob(self, regime: str) -> float:
        """P(regime stays the same) = P(to = regime | from = regime)."""
        probs = self.transition_probs(regime)
        normed = self._normalise(regime)
        return probs.get(normed, 1.0 / len(KNOWN_REGIMES))

    def to_dict(self) -> Dict:
        return {
            "alpha": self.alpha,
            "matrix": {k: dict(v) for k, v in self._matrix.items()},
            "observation_counts": dict(self._observation_counts),
        }

    def from_dict(self, data: Dict) -> None:
        self.alpha = float(data.get("alpha", self.alpha))
        for from_r, row in data.get("matrix", {}).items():
            for to_r, prob in row.items():
                self._matrix[from_r][to_r] = float(prob)
        for r, cnt in data.get("observation_counts", {}).items():
            self._observation_counts[r] = int(cnt)

    @staticmethod
    def _normalise(regime: str) -> str:
        r = regime.upper().replace(" ", "_")
        return r if r in KNOWN_REGIMES else "OTHER"


# ---------------------------------------------------------------------------
# Early Warning System
# ---------------------------------------------------------------------------

class EarlyWarningSystem:
    """
    Combinatorial rule engine that fires human-readable warnings when
    leading indicators suggest an imminent regime change.
    """

    # Each rule is (description, test_fn)
    # test_fn receives the features dict and returns True if warning fires
    RULES = [
        (
            "Volatility acceleration spike",
            lambda f: f.get("atr_acceleration", 0) > 0.15,
        ),
        (
            "Trend exhaustion (ADX declining from high + RSI extreme)",
            lambda f: f.get("trend_exhaustion", 0) > 0.6,
        ),
        (
            "Bollinger Band squeeze → expansion risk",
            lambda f: f.get("bb_squeeze_score", 0) > 0.25,
        ),
        (
            "Momentum divergence (fast vs slow momentum misalign)",
            lambda f: f.get("momentum_divergence", 0) > 0.02,
        ),
        (
            "Volume surge (>2× average)",
            lambda f: f.get("volume_surge_ratio", 1.0) > 2.0,
        ),
        (
            "High candle entropy (erratic price action)",
            lambda f: f.get("candle_entropy", 0) > 1.8,
        ),
        (
            "RSI at extreme — reversal risk",
            lambda f: f.get("rsi_extreme_distance", 25) < 5,
        ),
        (
            "ATR ratio elevated (>1.5× average volatility)",
            lambda f: f.get("atr_ratio", 1.0) > 1.5,
        ),
    ]

    def __init__(self) -> None:
        #: Number of rule-lambda exceptions caught since instantiation.
        #: Exposed so the parent forecaster can roll this into SoftFailMetrics.
        self.rule_fail_count: int = 0

    def check(self, features: Dict[str, float]) -> List[str]:
        """Return list of triggered warning strings."""
        warnings: List[str] = []
        for description, test_fn in self.RULES:
            try:
                if test_fn(features):
                    warnings.append(description)
            except Exception:
                self.rule_fail_count += 1
        return warnings


# ---------------------------------------------------------------------------
# Main Forecaster
# ---------------------------------------------------------------------------

class AIMarketRegimeForecaster:
    """
    AI-powered regime change forecaster.

    Combines leading-indicator analysis with a self-learning Markov model
    and an early-warning rule engine to predict regime transitions before
    they are detectable by a standard classifier.

    Thread-safe singleton — use ``get_ai_market_regime_forecaster()``.
    """

    STATE_FILE = DATA_DIR / "ai_regime_forecaster.json"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._indicator_engine = LeadingIndicatorEngine()
        self._markov = MarkovTransitionModel()
        self._ew_system = EarlyWarningSystem()

        # Regime observation history for self-updating Markov model
        self._regime_history: Deque[str] = deque(maxlen=REGIME_HISTORY_MAXLEN)
        self._last_regime: Optional[str] = None

        # Soft-fail observability counters
        self._soft_fail_metrics = SoftFailMetrics()

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info("✅ AIMarketRegimeForecaster ready")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forecast(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        current_regime: str,
        lookback: int = 20,
    ) -> ForecastResult:
        """
        Produce a regime transition forecast.

        Parameters
        ----------
        df : OHLCV DataFrame (most recent bar last)
        indicators : dict of pre-computed indicator values
        current_regime : current regime label (string)
        lookback : bars to use for rolling feature calculations

        Returns
        -------
        ForecastResult
        """
        with self._lock:
            # Update Markov model with new regime observation
            self._observe_regime(current_regime)

            # Extract leading-indicator features
            try:
                features = self._indicator_engine.compute(df, indicators, lookback)
            except Exception as exc:
                logger.warning("LeadingIndicatorEngine error: %s", exc)
                features = {}
                self._soft_fail_metrics.increment("feature_extraction_failures")

            # Get Markov transition probabilities
            transition_probs = self._markov.transition_probs(current_regime)
            persistence_p    = self._markov.persistence_prob(current_regime)
            change_p         = 1.0 - persistence_p

            # Adjust change probability with leading indicators
            adjusted_change_p = self._adjust_with_features(change_p, features)

            # Determine top next regime (excluding staying in same)
            normed_current = MarkovTransitionModel._normalise(current_regime)
            next_probs_excl_self = {
                r: p for r, p in transition_probs.items() if r != normed_current
            }
            if next_probs_excl_self:
                top_next = max(next_probs_excl_self, key=lambda r: next_probs_excl_self[r])
                top_prob = transition_probs.get(top_next, 0.0)
            else:
                top_next = normed_current
                top_prob = persistence_p

            # Transition risk score (0-100)
            transition_risk = self._compute_transition_risk(
                adjusted_change_p, features
            )

            # Estimate bars to transition
            expected_bars = self._estimate_bars_to_transition(
                persistence_p, features
            )

            # Early warnings — sync any rule-lambda failures into metrics
            ew_fails_before = self._ew_system.rule_fail_count
            warnings = self._ew_system.check(features)
            new_ew_fails = self._ew_system.rule_fail_count - ew_fails_before
            if new_ew_fails > 0:
                self._soft_fail_metrics.increment_by("early_warning_rule_failures", new_ew_fails)

            result = ForecastResult(
                current_regime=current_regime,
                next_regime_probs=transition_probs,
                top_next_regime=top_next,
                transition_probability=adjusted_change_p,
                transition_risk=transition_risk,
                expected_bars_to_transition=expected_bars,
                early_warnings=warnings,
                leading_features=features,
            )

            self._save_state()

            if warnings:
                logger.info(
                    "⚡ RegimeForecaster [%s] risk=%.0f transition_p=%.0f%% next=%s warnings=%s",
                    current_regime, transition_risk, adjusted_change_p * 100,
                    top_next, warnings,
                )

            return result

    def record_regime_transition(
        self, from_regime: str, to_regime: str
    ) -> None:
        """
        Explicitly record an observed regime transition to update the Markov model.

        Call this whenever the regime classifier confirms a change.
        """
        with self._lock:
            self._markov.update(from_regime, to_regime)
            self._save_state()
            logger.debug(
                "RegimeForecaster: recorded transition %s → %s", from_regime, to_regime
            )

    def get_status(self) -> Dict:
        """Return a status snapshot for monitoring / logging."""
        with self._lock:
            return {
                "regime_history_length": len(self._regime_history),
                "last_regime": self._last_regime,
                "markov_observations": dict(self._markov._observation_counts),
                "markov_matrix": {
                    k: {r: round(p, 4) for r, p in v.items()}
                    for k, v in self._markov._matrix.items()
                },
                "soft_fail_metrics": self._soft_fail_metrics.to_dict(),
            }

    def get_soft_fail_metrics(self) -> SoftFailMetrics:
        """
        Return a snapshot of soft-fail observability counters.

        Callers can poll this periodically to detect silent degradation::

            metrics = forecaster.get_soft_fail_metrics()
            if metrics.total_soft_fails > threshold:
                alert(...)
        """
        with self._lock:
            # Return a defensive copy so callers cannot mutate internal state
            return replace(self._soft_fail_metrics)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _observe_regime(self, current_regime: str) -> None:
        """Track regime history and auto-update Markov model on detected change."""
        normalised = MarkovTransitionModel._normalise(current_regime)
        if (
            self._last_regime is not None
            and self._last_regime != normalised
        ):
            # Detected a regime change → update Markov transition probabilities
            self._markov.update(self._last_regime, normalised)

        self._regime_history.append(normalised)
        self._last_regime = normalised

    def _adjust_with_features(
        self, base_change_p: float, features: Dict[str, float]
    ) -> float:
        """
        Boost or suppress the Markov-derived change probability using
        leading-indicator features.
        """
        boost = 0.0

        # Volatility acceleration boosts change probability
        atr_accel = features.get("atr_acceleration", 0.0)
        if atr_accel > 0.1:
            boost += 0.10
        elif atr_accel > 0.05:
            boost += 0.05

        # Trend exhaustion
        exhaustion = features.get("trend_exhaustion", 0.0)
        boost += exhaustion * 0.15

        # BB squeeze (compression → impending breakout)
        squeeze = features.get("bb_squeeze_score", 0.0)
        boost += squeeze * 0.10

        # Volume surge
        vol_ratio = features.get("volume_surge_ratio", 1.0)
        if vol_ratio > 2.0:
            boost += 0.08
        elif vol_ratio > 1.5:
            boost += 0.04

        # Momentum divergence
        mom_div = features.get("momentum_divergence", 0.0)
        boost += min(0.10, mom_div * 5.0)

        # Candle entropy
        entropy = features.get("candle_entropy", 0.0)
        if entropy > 2.0:
            boost += 0.05

        adjusted = min(0.99, base_change_p + boost)
        return round(adjusted, 4)

    def _compute_transition_risk(
        self, adjusted_change_p: float, features: Dict[str, float]
    ) -> float:
        """
        Produce a 0-100 risk score from the adjusted change probability
        and leading features.
        """
        # Base from change probability
        score = adjusted_change_p * 60.0

        # Add points from individual features
        score += features.get("trend_exhaustion", 0.0) * 15.0
        score += min(10.0, features.get("atr_ratio", 1.0) * 3.0 - 3.0)
        squeeze = features.get("bb_squeeze_score", 0.0)
        score += squeeze * 10.0

        # Early warnings bonus
        n_warnings = len(self._ew_system.check(features))
        score += n_warnings * 3.0

        return round(min(100.0, max(0.0, score)), 1)

    def _estimate_bars_to_transition(
        self, persistence_p: float, features: Dict[str, float]
    ) -> float:
        """
        Rough estimate of bars until the next regime change.

        Uses geometric distribution: E[T] = 1 / (1 - persistence_p)
        adjusted downward by leading-indicator urgency.
        """
        stay_p = max(0.01, min(0.99, persistence_p))
        urgency = (
            features.get("trend_exhaustion", 0.0) * 0.3
            + features.get("bb_squeeze_score", 0.0) * 0.2
            + (features.get("atr_ratio", 1.0) - 1.0) * 0.1
        )
        # Boost by urgency: scale down expected bars
        effective_stay_p = stay_p * max(0.5, 1.0 - urgency)
        expected = 1.0 / max(0.001, 1.0 - effective_stay_p)
        return round(min(500.0, expected), 1)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            state = {
                "last_regime": self._last_regime,
                "regime_history": list(self._regime_history),
                "markov": self._markov.to_dict(),
            }
            self.STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception as exc:
            logger.debug("RegimeForecasterState save failed: %s", exc)
            self._soft_fail_metrics.increment("state_save_failures")

    def _load_state(self) -> None:
        try:
            if not self.STATE_FILE.exists():
                return
            state = json.loads(self.STATE_FILE.read_text())
            self._last_regime = state.get("last_regime")
            for r in state.get("regime_history", []):
                self._regime_history.append(str(r))
            markov_data = state.get("markov")
            if markov_data:
                self._markov.from_dict(markov_data)
            logger.info("RegimeForecasterState loaded from %s", self.STATE_FILE)
        except Exception as exc:
            logger.warning("RegimeForecasterState load failed (%s) — starting fresh", exc)
            self._soft_fail_metrics.increment("state_load_failures")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_forecaster_instance: Optional[AIMarketRegimeForecaster] = None
_forecaster_lock = threading.Lock()


def get_ai_market_regime_forecaster() -> AIMarketRegimeForecaster:
    """
    Return the process-wide AIMarketRegimeForecaster singleton.

    Thread-safe.
    """
    global _forecaster_instance
    if _forecaster_instance is None:
        with _forecaster_lock:
            if _forecaster_instance is None:
                _forecaster_instance = AIMarketRegimeForecaster()
    return _forecaster_instance
