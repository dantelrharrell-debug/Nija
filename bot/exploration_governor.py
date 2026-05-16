"""
NIJA Exploration Governor
=========================

Central control layer for frequency recovery and guarded exploration.

Responsibilities:
1. Combine confidence nudges from TradeFrequencyController and
   WinRateFrequencyTuner into one bounded control signal.
2. Apply asymmetric damping:
   - tightening responds quickly
   - loosening recovers slowly
3. Apply mode hysteresis/cooldowns to reduce gate oscillation.
4. Track regime-aware failure-cluster pressure with exponential decay.
5. Manage small hourly/daily exploration budgets for near-miss candidates.
6. Score candidates using regret, novelty, and lightweight Sharpe guardrails.
"""

from __future__ import annotations

import logging
import math
import os
import random
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger("nija.exploration_governor")


@dataclass
class ExplorationStateVector:
    """Compact control-theory state snapshot for observability."""

    frequency_gap: float
    win_rate_gap: float
    ev_per_hour: float
    drawdown_pressure: float
    regime_confidence: float
    cluster_pressure: float
    budget_utilization: float


@dataclass
class ExplorationCandidate:
    """Near-miss candidate considered for shadow/live exploration."""

    symbol: str
    regime: str
    side: str
    gate_score: float
    effective_threshold: float
    confidence: float
    volume_ratio: float
    spread_pct: float = 0.0
    entry_type: str = "swing"
    liquidity_bucket: str = ""
    regime_confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExplorationDecision:
    """Result of evaluating a near-miss candidate."""

    shadow_sampled: bool
    allow_live: bool
    probability: float
    size_multiplier: float
    reason: str
    near_miss_gap: float
    cluster_pressure: float
    regret_score: float
    novelty_score: float
    budget_remaining_hour: int
    budget_remaining_day: int


@dataclass
class _ClusterBucket:
    pressure: float = 0.0
    last_update_ts: float = field(default_factory=time.time)
    regime: str = "unknown"


@dataclass
class _ContextBucket:
    exposures: int = 0
    live_exposures: int = 0
    outcomes: int = 0
    ema_reward: float = 0.0
    ema_regret: float = 0.0
    last_update_ts: float = field(default_factory=time.time)


class ExplorationGovernor:
    """
    Guarded exploration and unified confidence controller.

    The control signal uses the same sign semantics as the legacy confidence
    deltas:
      negative -> loosen gate
      positive -> tighten gate
    """

    _MODE_EPSILON = 0.01

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._random = random.Random()

        self._tighten_alpha = float(os.getenv("NIJA_EXP_TIGHTEN_ALPHA", "0.70"))
        self._loosen_alpha = float(os.getenv("NIJA_EXP_LOOSEN_ALPHA", "0.18"))
        self._max_delta = float(os.getenv("NIJA_EXP_MAX_DELTA", "0.22"))
        self._mode_persistence = int(os.getenv("NIJA_EXP_MODE_PERSISTENCE", "2"))
        self._mode_cooldown = int(os.getenv("NIJA_EXP_MODE_COOLDOWN", "3"))
        self._near_miss_score_gap = float(os.getenv("NIJA_EXP_NEAR_MISS_SCORE_GAP", "1.0"))
        self._hourly_budget = int(os.getenv("NIJA_EXP_HOURLY_BUDGET", "2"))
        self._daily_budget = int(os.getenv("NIJA_EXP_DAILY_BUDGET", "6"))
        self._shadow_enabled = os.getenv("NIJA_EXP_SHADOW_MODE", "true").lower() in ("1", "true", "yes")
        self._live_enabled = os.getenv("NIJA_EXP_LIVE_MODE", "false").lower() in ("1", "true", "yes")
        self._size_multiplier = float(os.getenv("NIJA_EXP_SIZE_MULTIPLIER", "0.35"))
        self._min_win_rate = float(os.getenv("NIJA_EXP_MIN_WIN_RATE", "0.50"))
        self._min_sharpe = float(os.getenv("NIJA_EXP_MIN_SHARPE", "0.05"))
        self._max_drawdown = float(os.getenv("NIJA_EXP_MAX_DRAWDOWN_PCT", "8.0"))

        self._control_delta = 0.0
        self._current_mode = "neutral"
        self._pending_mode = "neutral"
        self._pending_count = 0
        self._cooldown_remaining = 0

        self._hour_timestamps: Deque[float] = deque()
        self._day_timestamps: Deque[float] = deque()

        self._cluster_buckets: Dict[str, _ClusterBucket] = {}
        self._context_buckets: Dict[str, _ContextBucket] = defaultdict(_ContextBucket)
        self._last_decision_by_symbol: Dict[str, ExplorationDecision] = {}

        logger.info(
            "🧭 ExplorationGovernor initialised | α_tighten=%.2f α_loosen=%.2f "
            "cap=±%.2f persistence=%d cooldown=%d budgets=%d/h %d/day shadow=%s live=%s",
            self._tighten_alpha,
            self._loosen_alpha,
            self._max_delta,
            self._mode_persistence,
            self._mode_cooldown,
            self._hourly_budget,
            self._daily_budget,
            self._shadow_enabled,
            self._live_enabled,
        )

    # ------------------------------------------------------------------
    # Unified control signal
    # ------------------------------------------------------------------

    def get_confidence_adjustment(
        self,
        *,
        win_rate_delta: float = 0.0,
        trade_frequency_delta: float = 0.0,
        regime: str = "unknown",
        ev_per_hour: float = 0.0,
        drawdown_pressure: float = 0.0,
        regime_confidence: float = 0.0,
        cluster_key: Optional[str] = None,
    ) -> float:
        """
        Return one bounded, smoothed confidence delta.

        Positive values tighten quickly for safety.
        Negative values loosen slowly for recovery.
        """
        with self._lock:
            key = cluster_key or self._cluster_key("*", regime)
            cluster_pressure = self._get_decayed_cluster_pressure_locked(key, regime)

            raw_target = (
                0.60 * float(win_rate_delta)
                + 0.40 * float(trade_frequency_delta)
                + min(0.10, max(0.0, cluster_pressure - 0.40) * 0.20)
                + min(0.06, max(0.0, float(drawdown_pressure)) * 0.06)
            )
            raw_target = max(-self._max_delta, min(self._max_delta, raw_target))

            stabilized_target = self._apply_mode_hysteresis_locked(raw_target)
            alpha = self._tighten_alpha if stabilized_target > self._control_delta else self._loosen_alpha
            self._control_delta += alpha * (stabilized_target - self._control_delta)
            self._control_delta = max(-self._max_delta, min(self._max_delta, self._control_delta))

            logger.debug(
                "ExplorationGovernor delta: wr=%+.3f tf=%+.3f cluster=%.3f dd=%.3f "
                "target=%+.3f stabilized=%+.3f out=%+.3f mode=%s",
                win_rate_delta,
                trade_frequency_delta,
                cluster_pressure,
                drawdown_pressure,
                raw_target,
                stabilized_target,
                self._control_delta,
                self._current_mode,
            )
            return self._control_delta

    def _apply_mode_hysteresis_locked(self, target: float) -> float:
        target_mode = self._delta_to_mode(target)

        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            if target_mode != self._current_mode:
                return self._mode_anchor(self._current_mode)

        if target_mode == self._current_mode:
            self._pending_mode = target_mode
            self._pending_count = 0
            return target

        if target_mode != self._pending_mode:
            self._pending_mode = target_mode
            self._pending_count = 1
            return self._mode_anchor(self._current_mode)

        self._pending_count += 1
        if self._pending_count < self._mode_persistence:
            return self._mode_anchor(self._current_mode)

        self._current_mode = target_mode
        self._pending_mode = target_mode
        self._pending_count = 0
        self._cooldown_remaining = self._mode_cooldown
        return target

    def _delta_to_mode(self, value: float) -> str:
        if value > self._MODE_EPSILON:
            return "tighten"
        if value < -self._MODE_EPSILON:
            return "loosen"
        return "neutral"

    def _mode_anchor(self, mode: str) -> float:
        if mode == "tighten":
            return max(self._MODE_EPSILON, self._control_delta)
        if mode == "loosen":
            return min(-self._MODE_EPSILON, self._control_delta)
        return 0.0

    # ------------------------------------------------------------------
    # Exploration candidates
    # ------------------------------------------------------------------

    def evaluate_candidate(self, candidate: ExplorationCandidate) -> ExplorationDecision:
        """Evaluate a near-miss candidate for shadow/live exploration."""
        with self._lock:
            self._purge_budgets_locked()

            gap = max(0.0, float(candidate.effective_threshold) - float(candidate.gate_score))
            near_miss = gap <= self._near_miss_score_gap
            regime = str(candidate.regime or "unknown")
            cluster_key = self._cluster_key(candidate.symbol, regime)
            cluster_pressure = self._get_decayed_cluster_pressure_locked(cluster_key, regime)
            regret_score = self._get_context_regret_locked(candidate)
            novelty_score = self._get_novelty_score_locked(candidate)

            hour_remaining = max(0, self._hourly_budget - len(self._hour_timestamps))
            day_remaining = max(0, self._daily_budget - len(self._day_timestamps))

            if not near_miss:
                decision = ExplorationDecision(
                    shadow_sampled=False,
                    allow_live=False,
                    probability=0.0,
                    size_multiplier=1.0,
                    reason=f"not near-miss (gap={gap:.2f})",
                    near_miss_gap=gap,
                    cluster_pressure=cluster_pressure,
                    regret_score=regret_score,
                    novelty_score=novelty_score,
                    budget_remaining_hour=hour_remaining,
                    budget_remaining_day=day_remaining,
                )
                self._last_decision_by_symbol[candidate.symbol] = decision
                return decision

            if self._regime_blocks_exploration(regime):
                decision = ExplorationDecision(
                    shadow_sampled=self._shadow_enabled,
                    allow_live=False,
                    probability=0.0,
                    size_multiplier=1.0,
                    reason=f"regime blocked ({regime})",
                    near_miss_gap=gap,
                    cluster_pressure=cluster_pressure,
                    regret_score=regret_score,
                    novelty_score=novelty_score,
                    budget_remaining_hour=hour_remaining,
                    budget_remaining_day=day_remaining,
                )
                self._track_context_exposure_locked(candidate, live=False)
                self._last_decision_by_symbol[candidate.symbol] = decision
                return decision

            metrics = self._collect_metrics_locked()
            if not self._passes_guardrails(metrics):
                decision = ExplorationDecision(
                    shadow_sampled=self._shadow_enabled,
                    allow_live=False,
                    probability=0.0,
                    size_multiplier=1.0,
                    reason="guardrails blocked",
                    near_miss_gap=gap,
                    cluster_pressure=cluster_pressure,
                    regret_score=regret_score,
                    novelty_score=novelty_score,
                    budget_remaining_hour=hour_remaining,
                    budget_remaining_day=day_remaining,
                )
                self._track_context_exposure_locked(candidate, live=False)
                self._last_decision_by_symbol[candidate.symbol] = decision
                return decision

            strat_key = self._strata_key(candidate)
            strat_bucket = self._context_buckets[strat_key]
            strat_penalty = min(0.25, strat_bucket.live_exposures * 0.05)

            probability = 0.12
            probability += min(0.18, novelty_score * 0.18)
            probability += min(0.08, max(0.0, metrics["win_rate"] - self._min_win_rate) * 0.40)
            probability += min(0.08, max(0.0, metrics["sharpe_ratio"] - self._min_sharpe) * 0.12)
            probability -= min(0.20, regret_score * 0.30)
            probability -= min(0.25, cluster_pressure * 0.35)
            probability -= strat_penalty

            if candidate.spread_pct > 0.0 and candidate.spread_pct > 0.15:
                probability *= 0.3
            if candidate.volume_ratio > 0.0 and candidate.volume_ratio < 0.5:
                probability *= 0.5

            probability = max(0.0, min(0.45, probability))
            shadow_sampled = self._shadow_enabled
            allow_live = (
                self._live_enabled
                and hour_remaining > 0
                and day_remaining > 0
                and probability > 0.0
                and self._random.random() < probability
            )

            if allow_live:
                now = time.time()
                self._hour_timestamps.append(now)
                self._day_timestamps.append(now)
                hour_remaining -= 1
                day_remaining -= 1

            self._track_context_exposure_locked(candidate, live=allow_live)
            decision = ExplorationDecision(
                shadow_sampled=shadow_sampled,
                allow_live=allow_live,
                probability=round(probability, 4),
                size_multiplier=self._size_multiplier if allow_live else 1.0,
                reason="approved" if allow_live else "shadow-only",
                near_miss_gap=round(gap, 4),
                cluster_pressure=round(cluster_pressure, 4),
                regret_score=round(regret_score, 4),
                novelty_score=round(novelty_score, 4),
                budget_remaining_hour=hour_remaining,
                budget_remaining_day=day_remaining,
            )
            self._last_decision_by_symbol[candidate.symbol] = decision
            return decision

    def get_live_size_multiplier(self, symbol: str) -> float:
        """Return live exploration size multiplier for the last symbol decision."""
        with self._lock:
            decision = self._last_decision_by_symbol.get(symbol)
            if decision is None or not decision.allow_live:
                return 1.0
            return decision.size_multiplier

    # ------------------------------------------------------------------
    # Post-trade feedback / cluster decay / regret
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        *,
        symbol: str,
        regime: str,
        pnl_usd: float,
        is_win: bool,
        entry_type: str = "swing",
        reward: Optional[float] = None,
    ) -> None:
        """Update failure-cluster and regret state after a trade closes."""
        with self._lock:
            cluster_key = self._cluster_key(symbol, regime)
            bucket = self._cluster_buckets.get(cluster_key)
            if bucket is None:
                bucket = _ClusterBucket(regime=regime)
                self._cluster_buckets[cluster_key] = bucket
            pressure = self._get_decayed_cluster_pressure_locked(cluster_key, regime)
            if is_win:
                pressure *= 0.55
            else:
                loss_mag = min(1.0, max(0.15, abs(float(pnl_usd)) / 100.0))
                pressure = min(1.0, pressure + loss_mag)
            bucket.pressure = pressure
            bucket.last_update_ts = time.time()
            bucket.regime = regime

            context_key = self._context_key(symbol, regime, entry_type)
            ctx = self._context_buckets[context_key]
            ctx.outcomes += 1
            base_reward = reward
            if base_reward is None:
                base_reward = 1.0 if is_win else -1.0
                if pnl_usd != 0.0:
                    base_reward = max(-1.0, min(1.0, pnl_usd / max(25.0, abs(pnl_usd))))
            alpha = 0.12
            ctx.ema_reward = (1.0 - alpha) * ctx.ema_reward + alpha * float(base_reward)
            ctx.ema_regret = (1.0 - alpha) * ctx.ema_regret + alpha * max(0.0, -float(base_reward))
            ctx.last_update_ts = time.time()

    def get_cluster_pressure(self, symbol: str, regime: str) -> float:
        """Return current decayed cluster pressure for a symbol/regime bucket."""
        with self._lock:
            return self._get_decayed_cluster_pressure_locked(self._cluster_key(symbol, regime), regime)

    def _get_decayed_cluster_pressure_locked(self, key: str, regime: str) -> float:
        bucket = self._cluster_buckets.get(key)
        if bucket is None:
            return 0.0
        now = time.time()
        elapsed = max(0.0, now - bucket.last_update_ts)
        half_life = self._cluster_half_life_seconds(regime)
        if half_life <= 0:
            return bucket.pressure
        decay = math.exp(-math.log(2.0) * elapsed / half_life)
        return max(0.0, min(1.0, bucket.pressure * decay))

    def _cluster_half_life_seconds(self, regime: str) -> float:
        """
        Regime-aware cluster half-life.

        High-volatility / crisis regimes decay faster.
        Calm / low-volatility regimes decay slower.
        """
        regime_key = str(regime or "unknown").lower()
        if any(k in regime_key for k in ("crisis", "volatile", "volatility", "explosion", "chaotic")):
            return 900.0
        if any(k in regime_key for k in ("ranging", "consolidation", "neutral", "sideways")):
            return 2700.0
        return 5400.0

    # ------------------------------------------------------------------
    # Metrics / state snapshot
    # ------------------------------------------------------------------

    def get_state_vector(self, regime: str = "unknown") -> ExplorationStateVector:
        """Return the current control state vector."""
        with self._lock:
            metrics = self._collect_metrics_locked()
            budget_util = 0.0
            if self._daily_budget > 0:
                budget_util = min(1.0, len(self._day_timestamps) / float(self._daily_budget))
            return ExplorationStateVector(
                frequency_gap=metrics["frequency_gap"],
                win_rate_gap=metrics["win_rate_gap"],
                ev_per_hour=metrics["ev_per_hour"],
                drawdown_pressure=metrics["drawdown_pressure"],
                regime_confidence=0.0,
                cluster_pressure=self._get_decayed_cluster_pressure_locked(self._cluster_key("*", regime), regime),
                budget_utilization=budget_util,
            )

    def _collect_metrics_locked(self) -> Dict[str, float]:
        win_rate = 0.0
        sharpe_ratio = 0.0
        current_drawdown_pct = 0.0
        ev_per_hour = 0.0
        frequency_gap = 0.0
        win_rate_gap = 0.0

        try:
            try:
                from bot.pnl_analytics_layer import get_pnl_analytics_layer
            except ImportError:
                from pnl_analytics_layer import get_pnl_analytics_layer  # type: ignore
            analytics = get_pnl_analytics_layer()
            report = analytics.get_report()
            overall = report.get("overall", {})
            win_rate = float(overall.get("win_rate", 0.0))
            sharpe_ratio = float(overall.get("sharpe_ratio", 0.0))
            current_drawdown_pct = max(0.0, float(overall.get("worst_loss_streak", 0.0)))
        except Exception:
            pass

        try:
            try:
                from bot.win_rate_frequency_tuner import get_win_rate_frequency_tuner
            except ImportError:
                from win_rate_frequency_tuner import get_win_rate_frequency_tuner  # type: ignore
            tuner = get_win_rate_frequency_tuner()
            params = tuner.get_params()
            ev_per_hour = float(getattr(params, "ev_per_hour", 0.0))
            win_rate = max(win_rate, float(getattr(params, "win_rate", 0.0)))
            frequency_gap = max(0.0, float(getattr(tuner, "_min_freq", 0.0)) - float(getattr(params, "trades_per_hour", 0.0)))
            win_rate_gap = max(0.0, self._min_win_rate - float(getattr(params, "win_rate", 0.0)))
        except Exception:
            pass

        return {
            "win_rate": win_rate,
            "sharpe_ratio": sharpe_ratio,
            "current_drawdown_pct": current_drawdown_pct,
            "drawdown_pressure": min(1.0, current_drawdown_pct / max(1.0, self._max_drawdown)),
            "ev_per_hour": ev_per_hour,
            "frequency_gap": frequency_gap,
            "win_rate_gap": win_rate_gap,
        }

    def _passes_guardrails(self, metrics: Dict[str, float]) -> bool:
        if metrics["current_drawdown_pct"] > self._max_drawdown:
            return False
        if metrics["win_rate"] < self._min_win_rate:
            return False
        if metrics["sharpe_ratio"] < self._min_sharpe:
            return False
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _regime_blocks_exploration(self, regime: str) -> bool:
        regime_key = str(regime or "unknown").lower()
        return any(
            token in regime_key
            for token in ("crisis", "unfavorable", "volatility_explosion", "chaotic")
        )

    def _purge_budgets_locked(self) -> None:
        now = time.time()
        hour_cutoff = now - 3600.0
        day_cutoff = now - 86400.0
        while self._hour_timestamps and self._hour_timestamps[0] < hour_cutoff:
            self._hour_timestamps.popleft()
        while self._day_timestamps and self._day_timestamps[0] < day_cutoff:
            self._day_timestamps.popleft()

    def _track_context_exposure_locked(self, candidate: ExplorationCandidate, *, live: bool) -> None:
        key = self._context_key(candidate.symbol, candidate.regime, candidate.entry_type)
        ctx = self._context_buckets[key]
        ctx.exposures += 1
        if live:
            ctx.live_exposures += 1
        ctx.last_update_ts = time.time()

    def _get_context_regret_locked(self, candidate: ExplorationCandidate) -> float:
        key = self._context_key(candidate.symbol, candidate.regime, candidate.entry_type)
        ctx = self._context_buckets[key]
        regret = ctx.ema_regret

        # Contextual penalty from historical RL store buckets when available.
        try:
            try:
                from bot.trade_outcome_rl_store import get_trade_outcome_rl_store
            except ImportError:
                from trade_outcome_rl_store import get_trade_outcome_rl_store  # type: ignore
            store = get_trade_outcome_rl_store()
            sym_stats = store.get_symbol_stats().get(candidate.symbol, {})
            reg_stats = store.get_regime_stats().get(str(candidate.regime), {})
            sym_penalty = max(0.0, -float(sym_stats.get("ema_reward", 0.0)))
            reg_penalty = max(0.0, -float(reg_stats.get("ema_reward", 0.0)))
            regret = max(regret, 0.50 * sym_penalty + 0.50 * reg_penalty)
        except Exception:
            pass

        return max(0.0, min(1.0, regret))

    def _get_novelty_score_locked(self, candidate: ExplorationCandidate) -> float:
        key = self._context_key(candidate.symbol, candidate.regime, candidate.entry_type)
        exposures = self._context_buckets[key].exposures
        return 1.0 / math.sqrt(1.0 + exposures)

    def _context_key(self, symbol: str, regime: str, entry_type: str) -> str:
        return f"{str(regime).lower()}|{str(symbol).upper()}|{str(entry_type).lower()}"

    def _strata_key(self, candidate: ExplorationCandidate) -> str:
        liquidity = candidate.liquidity_bucket or self._infer_liquidity_bucket(candidate.volume_ratio)
        return f"{str(candidate.regime).lower()}|{liquidity}"

    def _infer_liquidity_bucket(self, volume_ratio: float) -> str:
        if volume_ratio >= 1.5:
            return "high_liquidity"
        if volume_ratio >= 0.8:
            return "mid_liquidity"
        return "thin_liquidity"

    def _cluster_key(self, symbol: str, regime: str) -> str:
        return f"{str(regime).lower()}|{str(symbol).upper()}"


_governor_instance: Optional[ExplorationGovernor] = None
_governor_lock = threading.Lock()


def get_exploration_governor(reset: bool = False) -> ExplorationGovernor:
    """Return the process-wide ExplorationGovernor singleton."""
    global _governor_instance
    with _governor_lock:
        if reset or _governor_instance is None:
            _governor_instance = ExplorationGovernor()
    return _governor_instance
