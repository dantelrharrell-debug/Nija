"""
NIJA Self-Learning Weight Tuner
================================
Every trade leaves a data trail.  This module mines that trail to make Nija
smarter after every single close.

Architecture
------------
1. Trade Attribution Layer
   Records why every trade was taken (features, weights, score, confidence)
   and the outcome (PnL, win/loss).  Persisted to
   ``data/trade_attribution_log.jsonl`` (append-only).
   Without this, learning is impossible.

2. Weight Optimization Engine
   Runs every ``OPTIMIZE_EVERY_N_TRADES`` (default 50) trades using the user-
   specified incremental gradient update:
       for trade in history:
           pnl = trade["pnl"]
           for feature, value in trade["features"].items():
               gradient = value * pnl       # correlation to profit
               weights[feature] += lr * gradient
       weights = normalize(weights)

3. Safety Layer  (NON-NEGOTIABLE)
   MIN_WEIGHT = -3.0 / MAX_WEIGHT = 3.0  — hard clamp every update
   weight *= 0.995                        — decay prevents overfitting
   rollback if rolling_pnl < -threshold   — reverts to last checkpoint

4. Regime-Specific Weight Sets
   weights_trending / weights_ranging / weights_volatile / weights_default
   Switch automatically: family = regime_family_map[regime]

5. Multi-Armed Bandit  (UCB1)
   Arms: aggressive, conservative, scalp
   Allocates trades dynamically; reward = pnl; avoids regime overfitting.

6. Logistic Regression Confidence
   P(win) = sigmoid(w · features + bias)
   Online SGD training — replaces static confidence with a live estimate.

7. Portfolio Intelligence
   Per-symbol win-rate drives a size multiplier [0.60 – 1.40].
   Per-regime win-rate drives adaptive sniper confidence floor.

Public API
----------
    load_dynamic_weights(regime)  → {"trend", "volume", "rsi", "regime"}
    get_weight_tuner()            → SelfLearningWeightTuner singleton

    # On signal evaluation (nija_ai_engine / ai_trade_ranker):
    tuner.record_signal_entry(symbol, regime, trade_context)

    # On trade close (execution_engine):
    tuner.record_trade_outcome(symbol, is_win, pnl_pct)

    # Queries used by pipeline:
    tuner.get_blend_weights(regime)           → (w_enh, w_opt, w_gate)
    tuner.get_gate_weights(regime)            → {"gate1_score": …}
    tuner.get_sniper_confidence_floor(regime) → float
    tuner.get_portfolio_size_multiplier(symbol, regime) → float
    tuner.get_lr_confidence(symbol)           → float | None

Author: NIJA Trading Systems
Version: 2.0 — April 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.weight_tuner")

# ---------------------------------------------------------------------------
# ① SAFETY LAYER — NON-NEGOTIABLE
# ---------------------------------------------------------------------------

MIN_WEIGHT: float = -3.0   # Lower clamp on signal weights
MAX_WEIGHT: float = 3.0    # Upper clamp on signal weights
WEIGHT_DECAY: float = 0.995  # Multiplicative decay applied after every update

ROLLBACK_WINDOW: int = 10            # Trades in rolling PnL window
ROLLBACK_PNL_THRESHOLD: float = -0.05  # -5 % rolling PnL triggers revert
CHECKPOINT_INTERVAL: int = 5         # Save checkpoint every N trades per regime

# ---------------------------------------------------------------------------
# ② LEARNING RATES
# ---------------------------------------------------------------------------

LR_SIGNAL: float = 0.03   # Signal-weight incremental update (per trade)
LR_BLEND: float = 0.004   # AI-engine blend weights
LR_GATE: float = 0.04     # Entry-gate weights
LR_LR_MODEL: float = 0.01  # Logistic regression SGD
LR_L2: float = 0.001       # L2 regularisation for LR

OPTIMIZE_EVERY_N_TRADES: int = 50  # Batch optimiser cadence
GRADIENT_LR: float = 0.05          # Batch gradient learning rate
MAX_HISTORY: int = 500             # Max trade records in RAM

MIN_TRADES_BEFORE_LEARNING: int = 15  # Cold-start guard per regime

# ---------------------------------------------------------------------------
# ③ REGIME FAMILY MAPPING
# ---------------------------------------------------------------------------

_REGIME_FAMILY: Dict[str, str] = {
    "strong_trend": "trending", "weak_trend": "trending",
    "expansion":    "trending", "trending":   "trending",
    "ranging":        "ranging", "consolidation": "ranging",
    "mean_reversion": "ranging",
    "volatile":          "volatile",
    "volatility_explosion": "volatile",
}
_DEFAULT_FAMILY = "default"

# Maps trade-attribution feature keys → signal weight keys
_FEATURE_TO_WEIGHT_KEY: Dict[str, str] = {
    "trend_strength": "trend",
    "volume_ratio":   "volume",
    "rsi":            "rsi",
    "adx":            "regime",
    "mtf_alignment":  "regime",
    "regime_match":   "regime",
}

# ---------------------------------------------------------------------------
# ④ EXPERT-DESIGNED DEFAULTS
# ---------------------------------------------------------------------------

# Signal weights: applied as  score += w[k] * signal_value[k]
_DEFAULT_SIGNAL: Dict[str, Dict[str, float]] = {
    # trending — momentum drives entries; negative trend weight in ranging
    "trending": {"trend": 2.5, "volume": 1.5, "rsi": 1.5, "regime": 2.0},
    # ranging  — RSI mean-reversion leads; strong trend is a warning
    "ranging":  {"trend": -0.5, "volume": 1.0, "rsi": 2.5, "regime": 2.0},
    # volatile — volume confirmation critical; RSI noisy
    "volatile": {"trend": 1.0, "volume": 2.5, "rsi": 1.0, "regime": 2.0},
    # default  — balanced four-factor scoring
    "default":  {"trend": 1.5, "volume": 1.5, "rsi": 1.5, "regime": 1.5},
}

# Composite blend weights: (w_enhanced, w_optimizer, w_gate) — sum to 1.0
_DEFAULT_BLEND: Dict[str, Tuple[float, float, float]] = {
    "trending": (0.66, 0.24, 0.10),
    "ranging":  (0.58, 0.20, 0.22),
    "volatile": (0.72, 0.18, 0.10),
    "default":  (0.64, 0.24, 0.12),
}

# AIEntryGate weights: sum to 9.0
_DEFAULT_GATE: Dict[str, Dict[str, float]] = {
    "trending": {"gate1_score": 3.5, "gate2_volume": 2.0, "gate3_volatility": 0.5,
                 "gate4_spread": 1.0, "gate5_regime": 2.0},
    "ranging":  {"gate1_score": 2.5, "gate2_volume": 2.0, "gate3_volatility": 1.5,
                 "gate4_spread": 1.5, "gate5_regime": 1.5},
    "volatile": {"gate1_score": 4.0, "gate2_volume": 2.5, "gate3_volatility": 0.5,
                 "gate4_spread": 0.5, "gate5_regime": 1.5},
    "default":  {"gate1_score": 3.0, "gate2_volume": 2.0, "gate3_volatility": 1.0,
                 "gate4_spread": 1.0, "gate5_regime": 2.0},
}

# Sniper filter confidence floor per regime family
_DEFAULT_SNIPER_CONF: Dict[str, float] = {
    "trending": 0.30,   # reliable momentum → lower bar
    "ranging":  0.40,   # trickier environment → higher bar
    "volatile": 0.45,   # conviction required in chaos
    "default":  0.35,
}

# ---------------------------------------------------------------------------
# ⑤ MULTI-ARMED BANDIT — ARM CONFIGS
# ---------------------------------------------------------------------------

_ARM_CONFIGS: Dict[str, Dict] = {
    "aggressive": {
        "description": "Higher sizes, lower confidence bar — exploit hot streaks",
        "position_size_multiplier": 1.30,
        "min_confidence": 0.28,
        "sniper_score_floor": 2.5,
        "signal_bias": {"trend": 0.3, "volume": 0.2, "rsi": 0.0, "regime": 0.0},
    },
    "conservative": {
        "description": "Lower sizes, higher quality bar — protect capital",
        "position_size_multiplier": 0.75,
        "min_confidence": 0.50,
        "sniper_score_floor": 4.0,
        "signal_bias": {"trend": 0.0, "volume": 0.0, "rsi": 0.3, "regime": 0.3},
    },
    "scalp": {
        "description": "Smallest sizes, RSI-driven, high-frequency",
        "position_size_multiplier": 0.60,
        "min_confidence": 0.35,
        "sniper_score_floor": 3.0,
        "signal_bias": {"trend": -0.3, "volume": 0.3, "rsi": 0.3, "regime": 0.0},
    },
}

# ---------------------------------------------------------------------------
# SAFETY HELPERS
# ---------------------------------------------------------------------------

def clamp(weights: Dict[str, float]) -> Dict[str, float]:
    """Hard-clamp every weight to [MIN_WEIGHT, MAX_WEIGHT]. NON-NEGOTIABLE."""
    for k in weights:
        weights[k] = max(MIN_WEIGHT, min(MAX_WEIGHT, weights[k]))
    return weights


def _apply_decay(weights: Dict[str, float]) -> Dict[str, float]:
    """Multiplicative decay — prevents overfitting to recent trades."""
    for k in weights:
        weights[k] *= WEIGHT_DECAY
    return weights


def normalize(weights: Dict[str, float]) -> Dict[str, float]:
    """L1-normalise so avg absolute weight ≈ 1.0, then apply safety ops."""
    total = sum(abs(v) for v in weights.values())
    if total > 0:
        scale = len(weights) / total
        weights = {k: v * scale for k, v in weights.items()}
    return clamp(_apply_decay(weights))


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# DATA CLASSES
# ---------------------------------------------------------------------------

@dataclass
class BanditArm:
    """One strategy configuration for the Multi-Armed Bandit."""
    name: str
    description: str
    position_size_multiplier: float
    min_confidence: float
    sniper_score_floor: float
    signal_bias: Dict[str, float]
    total_trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    ema_reward: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades > 0 else 0.0

    def to_dict(self) -> Dict:
        return {
            "name": self.name, "description": self.description,
            "position_size_multiplier": self.position_size_multiplier,
            "min_confidence": self.min_confidence,
            "sniper_score_floor": self.sniper_score_floor,
            "signal_bias": self.signal_bias,
            "total_trades": self.total_trades, "wins": self.wins,
            "total_pnl": round(self.total_pnl, 6),
            "ema_reward": round(self.ema_reward, 6),
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "BanditArm":
        arm = cls(
            name=d["name"], description=d.get("description", ""),
            position_size_multiplier=d.get("position_size_multiplier", 1.0),
            min_confidence=d.get("min_confidence", 0.35),
            sniper_score_floor=d.get("sniper_score_floor", 3.0),
            signal_bias=d.get("signal_bias", {}),
        )
        arm.total_trades = d.get("total_trades", 0)
        arm.wins = d.get("wins", 0)
        arm.total_pnl = d.get("total_pnl", 0.0)
        arm.ema_reward = d.get("ema_reward", 0.0)
        return arm


@dataclass
class RegimeWeightSet:
    """All adaptive weights for one regime family, with checkpoint/rollback."""
    regime_family: str
    # ① Signal weights (used in load_dynamic_weights formula)
    signal_weights: Dict[str, float] = field(default_factory=dict)
    # ② AI-engine composite blend (sum to 1.0)
    w_enhanced: float = 0.64
    w_optimizer: float = 0.24
    w_gate: float = 0.12
    # ③ Entry-gate weights (sum to 9.0)
    gate_weights: Dict[str, float] = field(default_factory=dict)
    # Statistics
    total_trades: int = 0
    wins: int = 0
    last_updated: str = ""
    # Safety: rollback state
    recent_pnl: List[float] = field(default_factory=list)
    checkpoint_signal: Dict[str, float] = field(default_factory=dict)
    checkpoint_blend: List[float] = field(default_factory=lambda: [0.64, 0.24, 0.12])
    checkpoint_gate: Dict[str, float] = field(default_factory=dict)
    checkpoint_at: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def rolling_pnl(self) -> float:
        window = self.recent_pnl[-ROLLBACK_WINDOW:]
        return sum(window) if window else 0.0

    def push_pnl(self, pnl: float) -> None:
        self.recent_pnl.append(pnl)
        if len(self.recent_pnl) > ROLLBACK_WINDOW * 2:
            self.recent_pnl = self.recent_pnl[-ROLLBACK_WINDOW:]

    def save_checkpoint(self) -> None:
        self.checkpoint_signal = dict(self.signal_weights)
        self.checkpoint_blend = [self.w_enhanced, self.w_optimizer, self.w_gate]
        self.checkpoint_gate = dict(self.gate_weights)
        self.checkpoint_at = self.total_trades

    def revert_checkpoint(self) -> None:
        if self.checkpoint_signal:
            self.signal_weights = dict(self.checkpoint_signal)
        if len(self.checkpoint_blend) == 3:
            self.w_enhanced, self.w_optimizer, self.w_gate = self.checkpoint_blend
        if self.checkpoint_gate:
            self.gate_weights = dict(self.checkpoint_gate)
        self.recent_pnl.clear()
        logger.warning(
            "⚠️  WeightTuner [%s]: rolled back to checkpoint @ trade %d",
            self.regime_family, self.checkpoint_at,
        )

    def to_dict(self) -> Dict:
        return {
            "regime_family": self.regime_family,
            "signal_weights": {k: round(v, 6) for k, v in self.signal_weights.items()},
            "w_enhanced": round(self.w_enhanced, 6),
            "w_optimizer": round(self.w_optimizer, 6),
            "w_gate": round(self.w_gate, 6),
            "gate_weights": {k: round(v, 4) for k, v in self.gate_weights.items()},
            "total_trades": self.total_trades,
            "wins": self.wins,
            "win_rate": round(self.win_rate, 4),
            "last_updated": self.last_updated,
            "recent_pnl": self.recent_pnl[-ROLLBACK_WINDOW:],
            "checkpoint_signal": self.checkpoint_signal,
            "checkpoint_blend": self.checkpoint_blend,
            "checkpoint_gate": self.checkpoint_gate,
            "checkpoint_at": self.checkpoint_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "RegimeWeightSet":
        rws = cls(regime_family=d["regime_family"])
        rws.signal_weights = d.get("signal_weights", {})
        rws.w_enhanced = d.get("w_enhanced", 0.64)
        rws.w_optimizer = d.get("w_optimizer", 0.24)
        rws.w_gate = d.get("w_gate", 0.12)
        rws.gate_weights = d.get("gate_weights", {})
        rws.total_trades = d.get("total_trades", 0)
        rws.wins = d.get("wins", 0)
        rws.last_updated = d.get("last_updated", "")
        rws.recent_pnl = d.get("recent_pnl", [])
        rws.checkpoint_signal = d.get("checkpoint_signal", {})
        rws.checkpoint_blend = d.get("checkpoint_blend", [0.64, 0.24, 0.12])
        rws.checkpoint_gate = d.get("checkpoint_gate", {})
        rws.checkpoint_at = d.get("checkpoint_at", 0)
        return rws


@dataclass
class SymbolStats:
    """Portfolio intelligence: per-symbol performance tracking."""
    symbol: str
    total_trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    last_updated: str = ""

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades > 0 else 0.0


@dataclass
class _PendingEntry:
    """Entry context stored between signal evaluation and trade close."""
    symbol: str
    regime_family: str
    signal_components: Dict[str, float]   # {trend, volume, rsi, regime} ∈ [0,1]
    lr_features: List[float]              # LR feature vector
    enhanced_score: float = 50.0
    optimizer_delta: float = 0.0
    gate_penalty: float = 0.0
    gate_results: Dict[str, bool] = field(default_factory=dict)
    arm_name: str = "conservative"
    trade_context: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# LOGISTIC REGRESSION CONFIDENCE
# ---------------------------------------------------------------------------

class LogisticRegressionConfidence:
    """
    Online logistic regression: P(win) = sigmoid(w · x + bias).

    Trained via SGD on every closed trade.  No external ML dependencies.
    Before ``LR_MIN_SAMPLES`` (20) trades the model returns the enhanced_score
    as a proxy, so the pipeline is never starved.

    Feature vector (8 dimensions):
        [trend, volume, rsi, regime_quality,
         enhanced_score_norm, optimizer_delta_norm, gate_quality, composite_norm]
    """

    FEATURE_NAMES: List[str] = [
        "trend", "volume", "rsi", "regime_quality",
        "enhanced_score_norm", "optimizer_delta_norm",
        "gate_quality", "composite_norm",
    ]
    N_FEATURES: int = len(FEATURE_NAMES)
    LR_MIN_SAMPLES: int = 20

    def __init__(self, lr: float = LR_LR_MODEL, l2: float = LR_L2) -> None:
        self.lr = lr
        self.l2 = l2
        self._weights: List[float] = [0.0] * self.N_FEATURES
        self._bias: float = 0.0
        self._n_samples: int = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    @staticmethod
    def sigmoid(x: float) -> float:
        """Numerically stable sigmoid."""
        if x >= 0:
            return 1.0 / (1.0 + math.exp(-min(x, 500.0)))
        z = math.exp(max(x, -500.0))
        return z / (1.0 + z)

    def predict(self, features: List[float]) -> float:
        """Return P(win) ∈ [0, 1]."""
        with self._lock:
            if self._n_samples < self.LR_MIN_SAMPLES:
                return features[4] if len(features) > 4 else 0.5  # cold start
            z = sum(w * x for w, x in zip(self._weights, features)) + self._bias
            return self.sigmoid(z)

    def update(self, features: List[float], is_win: bool) -> None:
        """One SGD step."""
        with self._lock:
            y = 1.0 if is_win else 0.0
            p = self.sigmoid(
                sum(w * x for w, x in zip(self._weights, features)) + self._bias
            )
            error = y - p
            for i in range(len(self._weights)):
                self._weights[i] += self.lr * error * features[i]
                self._weights[i] *= (1.0 - self.l2)  # L2 regularisation
            self._bias += self.lr * error
            self._n_samples += 1

    def extract_features(
        self,
        signal_components: Dict[str, float],
        breakdown: Dict,
    ) -> List[float]:
        """Build the 8-dimensional feature vector."""
        t = float(signal_components.get("trend", 0.5))
        v = float(signal_components.get("volume", 0.5))
        r = float(signal_components.get("rsi", 0.5))
        rq = float(signal_components.get("regime", 0.5))
        enh = min(float(breakdown.get("enhanced_score", 50.0)) / 100.0, 1.0)
        opt = min(float(breakdown.get("optimizer_delta", 0.0)) / 2.0, 1.0)
        gq = 1.0 - min(float(breakdown.get("gate_penalty", 0.0)) / 15.0, 1.0)
        comp = min(float(breakdown.get("composite_score", 50.0)) / 100.0, 1.0)
        return [
            max(0.0, min(1.0, x))
            for x in [t, v, r, rq, enh, opt, gq, comp]
        ]

    def to_dict(self) -> Dict:
        return {
            "weights": [round(w, 6) for w in self._weights],
            "bias": round(self._bias, 6),
            "n_samples": self._n_samples,
        }

    @classmethod
    def from_dict(cls, d: Dict, lr: float = LR_LR_MODEL, l2: float = LR_L2) -> "LogisticRegressionConfidence":
        obj = cls(lr=lr, l2=l2)
        obj._weights = d.get("weights", [0.0] * cls.N_FEATURES)
        obj._bias = d.get("bias", 0.0)
        obj._n_samples = d.get("n_samples", 0)
        return obj


# ---------------------------------------------------------------------------
# MULTI-ARMED BANDIT  (UCB1)
# ---------------------------------------------------------------------------

class MultiArmedBandit:
    """
    UCB1 bandit — dynamically allocates trades between:
        aggressive   — exploits momentum, larger sizes
        conservative — protects capital, higher quality bar
        scalp        — high-frequency RSI-driven entries

    Selection: UCB1 = ema_reward + C * sqrt(ln(N) / n_i)
    Update:    EMA on per-arm reward after each close.
    """

    def __init__(
        self,
        exploration_c: float = 0.5,
        ema_decay: float = 0.9,
    ) -> None:
        self._arms: Dict[str, BanditArm] = {
            name: BanditArm(name=name, **cfg)
            for name, cfg in _ARM_CONFIGS.items()
        }
        self._assignments: Dict[str, str] = {}   # symbol → arm_name
        self._c = exploration_c
        self._ema_decay = ema_decay
        self._lock = threading.RLock()

    # ------------------------------------------------------------------

    def select_arm(self, symbol: str) -> str:
        """Choose an arm via UCB1 and record the assignment for symbol."""
        with self._lock:
            total = sum(a.total_trades for a in self._arms.values())
            # Cold start: try each arm once in alphabetical order
            untried = [n for n, a in sorted(self._arms.items()) if a.total_trades == 0]
            if untried:
                chosen = untried[0]
                self._assignments[symbol] = chosen
                return chosen
            # UCB1 scoring
            scores: Dict[str, float] = {}
            for name, arm in self._arms.items():
                ucb = arm.ema_reward + self._c * math.sqrt(
                    math.log(max(total, 1)) / arm.total_trades
                )
                scores[name] = ucb
            chosen = max(scores, key=scores.get)
            self._assignments[symbol] = chosen
            return chosen

    def record_outcome(self, symbol: str, is_win: bool, pnl: float) -> Optional[str]:
        """Update the arm that took this trade. Returns the arm name."""
        with self._lock:
            arm_name = self._assignments.pop(symbol, None)
            if arm_name is None:
                return None
            arm = self._arms.get(arm_name)
            if arm is None:
                return None
            arm.total_trades += 1
            arm.total_pnl += pnl
            if is_win:
                arm.wins += 1
            arm.ema_reward = (
                self._ema_decay * arm.ema_reward + (1 - self._ema_decay) * pnl
            )
            return arm_name

    def get_arm(self, arm_name: str) -> Optional[BanditArm]:
        return self._arms.get(arm_name)

    def get_active_arm(self, symbol: str) -> Optional[BanditArm]:
        with self._lock:
            name = self._assignments.get(symbol)
            return self._arms.get(name) if name else None

    def to_dict(self) -> Dict:
        return {name: arm.to_dict() for name, arm in self._arms.items()}

    def load_dict(self, d: Dict) -> None:
        for name, ad in d.items():
            if name in self._arms:
                restored = BanditArm.from_dict(ad)
                self._arms[name] = restored


# ---------------------------------------------------------------------------
# TRADE ATTRIBUTION LOG
# ---------------------------------------------------------------------------

class TradeAttributionLog:
    """
    ① Trade Attribution Layer (CRITICAL)

    Records every trade's entry context:
        trade_context = {
            "symbol": symbol,
            "side": side,
            "score": score,
            "confidence": confidence,
            "features": {
                "trend_strength": …, "volume_ratio": …, "rsi": …,
                "adx": …, "mtf_alignment": …, "regime_match": …,
            },
            "weights": current_weights.copy(),
        }
    Then after close:
        trade_context["pnl"] = realized_pnl
        trade_context["win"] = realized_pnl > 0

    Persisted to data/trade_attribution_log.jsonl (append-only).
    In-memory ring buffer holds the last MAX_HISTORY records for optimization.
    """

    def __init__(self, log_path: Path, max_memory: int = MAX_HISTORY) -> None:
        self._path = log_path
        self._records: Deque[Dict] = deque(maxlen=max_memory)
        self._lock = threading.Lock()
        self._load_recent()

    # ------------------------------------------------------------------

    def record_entry(self, trade_context: Dict) -> None:
        """Store the entry context at trade open."""
        record = {**trade_context, "status": "open",
                  "timestamp": datetime.utcnow().isoformat()}
        with self._lock:
            self._records.append(record)
        self._append_line(record)

    def record_close(self, symbol: str, pnl: float, win: bool) -> Optional[Dict]:
        """
        Update the most recent open record for symbol with outcome.
        Returns the completed record, or None if not found.
        """
        with self._lock:
            for rec in reversed(list(self._records)):
                if rec.get("symbol") == symbol and rec.get("status") == "open":
                    rec["status"] = "closed"
                    rec["pnl"] = round(pnl, 6)
                    rec["win"] = win
                    rec["closed_at"] = datetime.utcnow().isoformat()
                    self._append_line(rec)
                    return rec
        return None

    def get_closed_trades(self, last_n: int = MAX_HISTORY) -> List[Dict]:
        """Return the most recent closed trades for batch optimisation."""
        with self._lock:
            return [
                r for r in list(self._records)[-last_n:]
                if r.get("status") == "closed"
            ]

    # ------------------------------------------------------------------

    def _append_line(self, record: Dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.warning("TradeAttributionLog write error: %s", exc)

    def _load_recent(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as fh:
                lines = fh.readlines()
            for line in lines[-MAX_HISTORY:]:
                try:
                    self._records.append(json.loads(line.strip()))
                except Exception:
                    pass
            logger.debug("TradeAttributionLog: loaded %d records", len(self._records))
        except Exception as exc:
            logger.warning("TradeAttributionLog load error: %s", exc)


# ---------------------------------------------------------------------------
# WEIGHT OPTIMIZATION ENGINE
# ---------------------------------------------------------------------------

class WeightOptimizationEngine:
    """
    ② Batch Weight Optimizer — Method 1 (Recommended)

    Runs every OPTIMIZE_EVERY_N_TRADES using the incremental gradient update:

        def update_weights(weights, trade_history, lr=0.05):
            for trade in trade_history:
                pnl = trade["pnl"]
                for feature, value in trade["features"].items():
                    gradient = value * pnl      # correlation to profit
                    weights[feature] += lr * gradient
            return normalize(weights)
    """

    def __init__(
        self,
        optimize_every: int = OPTIMIZE_EVERY_N_TRADES,
        lr: float = GRADIENT_LR,
    ) -> None:
        self._every = optimize_every
        self._lr = lr
        self._trades_since_last: int = 0

    def tick(self) -> bool:
        """Call after each trade. Returns True when batch optimisation is due."""
        self._trades_since_last += 1
        if self._trades_since_last >= self._every:
            self._trades_since_last = 0
            return True
        return False

    def run(
        self,
        current_weights: Dict[str, float],
        trade_history: List[Dict],
    ) -> Dict[str, float]:
        """
        Incremental gradient update across all trades in history.
        Maps trade-attribution feature keys to weight keys via
        _FEATURE_TO_WEIGHT_KEY, then applies safety ops.
        """
        if not trade_history:
            return current_weights

        weights = dict(current_weights)

        for trade in trade_history:
            pnl = float(trade.get("pnl", 0.0))
            features: Dict = trade.get("features", {})
            for feat_key, raw_value in features.items():
                wt_key = _FEATURE_TO_WEIGHT_KEY.get(feat_key, feat_key)
                if wt_key not in weights:
                    continue
                gradient = float(raw_value) * pnl   # correlation to profit
                weights[wt_key] += self._lr * gradient

        # Safety: normalize → clamp → decay
        weights = normalize(weights)

        logger.info(
            "⚙️  WeightOptimizer ran on %d trades → %s",
            len(trade_history),
            {k: round(v, 3) for k, v in weights.items()},
        )
        return weights


# ---------------------------------------------------------------------------
# MAIN TUNER
# ---------------------------------------------------------------------------

class SelfLearningWeightTuner:
    """
    Orchestrates all learning components for Nija's adaptive intelligence.

    Thread-safe singleton.  Persists state to data/weight_tuner_state.json.
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "weight_tuner_state.json"
    ATTR_LOG_FILE = DATA_DIR / "trade_attribution_log.jsonl"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._weights: Dict[str, RegimeWeightSet] = {}
        self._pending: Dict[str, _PendingEntry] = {}
        self._lr_cache: Dict[str, float] = {}   # symbol → LR win probability

        self._lr = LogisticRegressionConfidence()
        self._bandit = MultiArmedBandit()
        self._optimizer = WeightOptimizationEngine()
        self._attr_log = TradeAttributionLog(self.ATTR_LOG_FILE)
        self._symbol_stats: Dict[str, SymbolStats] = {}

        if not self._load_state():
            self._init_defaults()
            self._save_state()

        logger.info("=" * 72)
        logger.info("⚖️  NIJA Self-Learning Weight Tuner — ACTIVE")
        for fam, ws in self._weights.items():
            logger.info(
                "   %-10s  signal=%s  blend=(%.2f/%.2f/%.2f)  trades=%-4d  wr=%.0f%%",
                fam,
                {k: round(v, 2) for k, v in ws.signal_weights.items()},
                ws.w_enhanced, ws.w_optimizer, ws.w_gate,
                ws.total_trades, ws.win_rate * 100,
            )
        logger.info("   LR model: %d samples trained", self._lr._n_samples)
        logger.info("=" * 72)

    # ------------------------------------------------------------------
    # PUBLIC: ENTRY RECORDING
    # ------------------------------------------------------------------

    def record_signal_entry(
        self,
        symbol: str,
        regime: str,
        trade_context: Optional[Dict] = None,
        breakdown: Optional[Dict] = None,
    ) -> None:
        """
        Called at signal evaluation time.

        Parameters
        ----------
        symbol:        Trading pair.
        regime:        Regime string at entry (e.g. "strong_trend").
        trade_context: Full attribution dict (see Trade Attribution Layer docs).
        breakdown:     _compute_composite() breakdown from NijaAIEngine.
        """
        family = _REGIME_FAMILY.get(str(regime).lower(), _DEFAULT_FAMILY)
        bd = breakdown or {}
        tc = trade_context or {}

        # Extract signal components from trade_context features (normalize to [0,1])
        features = tc.get("features", {})
        signal_components: Dict[str, float] = {
            "trend":  float(features.get("trend_strength", 0.5)),
            "volume": float(features.get("volume_ratio", 0.5)),
            "rsi":    float(features.get("rsi", 0.5)),
            "regime": float(features.get("regime_match", 0.5)),
        }

        # Build LR feature vector
        lr_feats = self._lr.extract_features(signal_components, bd)

        # Compute and cache LR win probability for sniper filter
        win_prob = self._lr.predict(lr_feats)
        with self._lock:
            self._lr_cache[symbol] = win_prob

        # Select bandit arm
        arm_name = self._bandit.select_arm(symbol)

        entry = _PendingEntry(
            symbol=symbol,
            regime_family=family,
            signal_components=signal_components,
            lr_features=lr_feats,
            enhanced_score=float(bd.get("enhanced_score", 50.0)),
            optimizer_delta=float(bd.get("optimizer_delta", 0.0)),
            gate_penalty=float(bd.get("gate_penalty", 0.0)),
            gate_results={k: bool(v) for k, v in bd.get("gate_results", {}).items()},
            arm_name=arm_name,
            trade_context=tc,
        )

        with self._lock:
            self._pending[symbol] = entry

        # Log trade attribution entry
        if tc:
            tc_log = {
                **tc,
                "regime": regime,
                "regime_family": family,
                "arm": arm_name,
                "lr_win_prob": round(win_prob, 4),
            }
            self._attr_log.record_entry(tc_log)

    # ------------------------------------------------------------------
    # PUBLIC: OUTCOME RECORDING
    # ------------------------------------------------------------------

    def record_trade_outcome(
        self,
        symbol: str,
        is_win: bool,
        pnl_pct: float = 0.0,
    ) -> None:
        """
        Called at trade close.  Drives all learning components.

        1. Updates trade attribution log
        2. Updates bandit arm reward
        3. Trains logistic regression model
        4. Applies incremental gradient update to signal weights
        5. Updates blend and gate weights
        6. Checks rollback condition  (safety layer)
        7. Runs batch optimiser if N trades elapsed
        8. Updates per-symbol portfolio stats
        """
        with self._lock:
            entry = self._pending.pop(symbol, None)

        # ① Attribution log — close the record
        self._attr_log.record_close(symbol, pnl_pct, is_win)

        # ② Bandit arm update
        self._bandit.record_outcome(symbol, is_win, pnl_pct)

        # ③ Symbol stats
        with self._lock:
            ss = self._symbol_stats.setdefault(symbol, SymbolStats(symbol=symbol))
            ss.total_trades += 1
            if is_win:
                ss.wins += 1
            ss.total_pnl += pnl_pct
            ss.last_updated = datetime.utcnow().isoformat()

        if entry is None:
            logger.debug("WeightTuner: no pending entry for %s — skipping weight update", symbol)
            self._save_state()
            return

        family = entry.regime_family

        with self._lock:
            ws = self._weights.get(family)
            if ws is None:
                self._save_state()
                return

            ws.total_trades += 1
            if is_win:
                ws.wins += 1
            ws.push_pnl(pnl_pct)

            # ③ Train LR model
            if entry.lr_features:
                self._lr.update(entry.lr_features, is_win)

            if ws.total_trades < MIN_TRADES_BEFORE_LEARNING:
                logger.debug(
                    "WeightTuner [%s]: %d/%d trades — warming up",
                    family, ws.total_trades, MIN_TRADES_BEFORE_LEARNING,
                )
                self._save_state()
                return

            # Save checkpoint every CHECKPOINT_INTERVAL trades
            if (ws.total_trades - ws.checkpoint_at) >= CHECKPOINT_INTERVAL:
                ws.save_checkpoint()

            # ④ Incremental signal-weight gradient update
            self._update_signal_weights(ws, entry, pnl_pct)

            # ⑤ Blend + gate weight updates
            self._update_blend_weights(ws, entry, is_win)
            self._update_gate_weights(ws, entry, is_win)

            # ⑥ Safety rollback check
            if ws.rolling_pnl < ROLLBACK_PNL_THRESHOLD:
                ws.revert_checkpoint()

            # ⑦ Batch optimiser
            if self._optimizer.tick():
                closed = self._attr_log.get_closed_trades(OPTIMIZE_EVERY_N_TRADES)
                if closed:
                    ws.signal_weights = self._optimizer.run(ws.signal_weights, closed)

            ws.last_updated = datetime.utcnow().isoformat()

            logger.info(
                "⚖️  WeightTuner [%-10s] %s | signal=%s | wr=%.0f%% (%d trades)",
                family,
                "✅ WIN " if is_win else "❌ LOSS",
                {k: round(v, 2) for k, v in ws.signal_weights.items()},
                ws.win_rate * 100,
                ws.total_trades,
            )

        self._save_state()

    # ------------------------------------------------------------------
    # PUBLIC: QUERIES USED BY PIPELINE
    # ------------------------------------------------------------------

    def get_blend_weights(self, regime: str) -> Tuple[float, float, float]:
        """Return (w_enhanced, w_optimizer, w_gate) for NijaAIEngine."""
        family = _REGIME_FAMILY.get(str(regime).lower(), _DEFAULT_FAMILY)
        with self._lock:
            ws = self._weights.get(family)
            if ws is None or ws.total_trades < MIN_TRADES_BEFORE_LEARNING:
                return _DEFAULT_BLEND.get(family, _DEFAULT_BLEND["default"])
            return (ws.w_enhanced, ws.w_optimizer, ws.w_gate)

    def get_gate_weights(self, regime: str) -> Dict[str, float]:
        """Return per-gate weight dict for AIEntryGate.check()."""
        family = _REGIME_FAMILY.get(str(regime).lower(), _DEFAULT_FAMILY)
        with self._lock:
            ws = self._weights.get(family)
            if ws is None or ws.total_trades < MIN_TRADES_BEFORE_LEARNING:
                return dict(_DEFAULT_GATE.get(family, _DEFAULT_GATE["default"]))
            return dict(ws.gate_weights)

    def get_signal_weights(self, regime: str) -> Dict[str, float]:
        """Return signal weights {trend, volume, rsi, regime} for scoring formula."""
        family = _REGIME_FAMILY.get(str(regime).lower(), _DEFAULT_FAMILY)
        with self._lock:
            ws = self._weights.get(family)
            if ws is None or ws.total_trades < MIN_TRADES_BEFORE_LEARNING:
                base = dict(_DEFAULT_SIGNAL.get(family, _DEFAULT_SIGNAL["default"]))
            else:
                base = dict(ws.signal_weights)

            # Apply the most-recently-selected bandit arm's signal bias.
            # The arm is tracked per-symbol in _pending; here we use the arm
            # with the highest EMA reward as the "current best arm" for the
            # regime-level weight query (no symbol context available here).
            best_arm_name = max(
                self._bandit._arms,
                key=lambda n: self._bandit._arms[n].ema_reward,
            )
            arm = self._bandit.get_arm(best_arm_name)
            if arm is not None:
                for key, bias in arm.signal_bias.items():
                    if key in base:
                        base[key] = _clip(base[key] + bias, MIN_WEIGHT, MAX_WEIGHT)
            return base

    def get_sniper_confidence_floor(self, regime: str) -> float:
        """Adaptive confidence floor for sniper_filter.check()."""
        family = _REGIME_FAMILY.get(str(regime).lower(), _DEFAULT_FAMILY)
        base = _DEFAULT_SNIPER_CONF.get(family, 0.35)
        with self._lock:
            ws = self._weights.get(family)
            if ws is None or ws.total_trades < MIN_TRADES_BEFORE_LEARNING:
                return base
            wr = ws.win_rate
            # High win-rate → relax floor (more entries); low → tighten
            if wr >= 0.65:
                return max(0.20, base - 0.08)
            elif wr >= 0.55:
                return max(0.22, base - 0.04)
            elif wr <= 0.35:
                return min(0.60, base + 0.10)
            elif wr <= 0.45:
                return min(0.55, base + 0.05)
            return base

    def get_portfolio_size_multiplier(self, symbol: str, regime: str) -> float:
        """
        Performance-derived position-size multiplier for symbol + regime.
        Combines per-symbol win-rate with per-regime win-rate.
        Also incorporates the active bandit arm's size multiplier.
        """
        with self._lock:
            # Symbol-level
            ss = self._symbol_stats.get(symbol)
            sym_mult = 1.0
            if ss and ss.total_trades >= 10:
                wr = ss.win_rate
                if wr >= 0.65:
                    sym_mult = 1.20
                elif wr >= 0.55:
                    sym_mult = 1.10
                elif wr <= 0.35:
                    sym_mult = 0.75
                elif wr <= 0.45:
                    sym_mult = 0.85

            # Regime-level
            family = _REGIME_FAMILY.get(str(regime).lower(), _DEFAULT_FAMILY)
            ws = self._weights.get(family)
            reg_mult = 1.0
            if ws and ws.total_trades >= MIN_TRADES_BEFORE_LEARNING:
                wr = ws.win_rate
                if wr >= 0.65:
                    reg_mult = 1.15
                elif wr >= 0.55:
                    reg_mult = 1.05
                elif wr <= 0.35:
                    reg_mult = 0.80
                elif wr <= 0.45:
                    reg_mult = 0.90

            # Bandit arm size multiplier
            arm = self._bandit.get_active_arm(symbol)
            arm_mult = arm.position_size_multiplier if arm else 1.0

        combined = sym_mult * reg_mult * arm_mult
        return max(0.50, min(1.50, combined))

    def get_lr_confidence(self, symbol: str) -> Optional[float]:
        """Return the LR-predicted win probability for symbol (one-shot peek)."""
        with self._lock:
            return self._lr_cache.get(symbol)

    def get_active_arm_config(self, symbol: str) -> Dict:
        """Return the active bandit arm config for symbol."""
        arm = self._bandit.get_active_arm(symbol)
        if arm:
            return {
                "arm": arm.name,
                "position_size_multiplier": arm.position_size_multiplier,
                "min_confidence": arm.min_confidence,
                "sniper_score_floor": arm.sniper_score_floor,
                "signal_bias": arm.signal_bias,
            }
        return {"arm": "conservative", "position_size_multiplier": 1.0,
                "min_confidence": 0.35, "sniper_score_floor": 3.0, "signal_bias": {}}

    # ------------------------------------------------------------------
    # PUBLIC: REPORTING
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        with self._lock:
            lines = [
                "",
                "=" * 80,
                "  NIJA SELF-LEARNING WEIGHT TUNER — STATUS REPORT",
                "=" * 80,
                "",
                "  SIGNAL WEIGHTS (trend / volume / rsi / regime):",
                f"  {'Regime':<12} {'trend':>7} {'volume':>7} {'rsi':>7} {'regime':>7} "
                f"{'Trades':>7} {'WR%':>5}",
                "-" * 56,
            ]
            for fam in ["trending", "ranging", "volatile", "default"]:
                ws = self._weights.get(fam)
                if ws is None:
                    continue
                sw = ws.signal_weights
                lines.append(
                    f"  {ws.regime_family:<12} "
                    f"{sw.get('trend', 0):>7.3f} "
                    f"{sw.get('volume', 0):>7.3f} "
                    f"{sw.get('rsi', 0):>7.3f} "
                    f"{sw.get('regime', 0):>7.3f} "
                    f"{ws.total_trades:>7} "
                    f"{ws.win_rate*100:>5.0f}%"
                )
            lines += [
                "",
                "  MULTI-ARMED BANDIT:",
                f"  {'Arm':<14} {'Trades':>7} {'WR%':>5} {'AvgPnL':>8} {'EMA':>8}",
                "-" * 44,
            ]
            for arm in self._bandit._arms.values():
                lines.append(
                    f"  {arm.name:<14} {arm.total_trades:>7} "
                    f"{arm.win_rate*100:>5.0f}% "
                    f"{arm.avg_pnl*100:>7.2f}% "
                    f"{arm.ema_reward*100:>7.2f}%"
                )
            lines += [
                "",
                f"  LOGISTIC REGRESSION: {self._lr._n_samples} samples trained"
                + (" (active)" if self._lr._n_samples >= self._lr.LR_MIN_SAMPLES else " (warming up)"),
                f"  LR weights: {[round(w, 3) for w in self._lr._weights]}",
                "=" * 80,
                "",
            ]
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # INTERNAL: GRADIENT UPDATES
    # ------------------------------------------------------------------

    def _update_signal_weights(
        self,
        ws: RegimeWeightSet,
        entry: _PendingEntry,
        pnl_pct: float,
    ) -> None:
        """
        Incremental gradient update (per-trade):
            gradient = feature_value * pnl
            weights[feature] += lr * gradient
        Then apply safety ops: clamp + decay.
        """
        sc = entry.signal_components
        for key in list(ws.signal_weights.keys()):
            value = sc.get(key, 0.5)
            gradient = value * pnl_pct
            ws.signal_weights[key] = ws.signal_weights.get(key, 1.0) + LR_SIGNAL * gradient

        ws.signal_weights = _apply_decay(clamp(ws.signal_weights))

    def _update_blend_weights(
        self,
        ws: RegimeWeightSet,
        entry: _PendingEntry,
        is_win: bool,
    ) -> None:
        """Gradient update for AI-engine composite blend weights."""
        O = 1.0 if is_win else -1.0
        c_enh = entry.enhanced_score / 100.0
        c_opt = min(entry.optimizer_delta, 2.0) / 2.0
        c_pen = min(entry.gate_penalty, 15.0) / 15.0

        ws.w_enhanced  = _clip(ws.w_enhanced  + LR_BLEND * O * c_enh,  0.30, 0.85)
        ws.w_optimizer = _clip(ws.w_optimizer + LR_BLEND * O * c_opt, 0.05, 0.50)
        ws.w_gate      = _clip(ws.w_gate      - LR_BLEND * O * c_pen,  0.05, 0.40)

        total = ws.w_enhanced + ws.w_optimizer + ws.w_gate
        if total > 0:
            ws.w_enhanced  /= total
            ws.w_optimizer /= total
            ws.w_gate      /= total

    def _update_gate_weights(
        self,
        ws: RegimeWeightSet,
        entry: _PendingEntry,
        is_win: bool,
    ) -> None:
        """Per-gate correctness update: reward gates whose verdict matched outcome."""
        if not entry.gate_results:
            return
        for gate_name, gate_passed in entry.gate_results.items():
            if gate_name not in ws.gate_weights:
                continue
            correct = gate_passed == is_win
            delta = LR_GATE * (1.0 if correct else -1.0)
            ws.gate_weights[gate_name] = _clip(
                ws.gate_weights.get(gate_name, 1.8) + delta, 0.50, 5.00
            )
        total_gw = sum(ws.gate_weights.values())
        if total_gw > 0:
            ws.gate_weights = {k: round(v * 9.0 / total_gw, 4) for k, v in ws.gate_weights.items()}

    # ------------------------------------------------------------------
    # PERSISTENCE
    # ------------------------------------------------------------------

    def _init_defaults(self) -> None:
        for fam in ["trending", "ranging", "volatile", "default"]:
            blend = _DEFAULT_BLEND[fam]
            ws = RegimeWeightSet(
                regime_family=fam,
                signal_weights=dict(_DEFAULT_SIGNAL[fam]),
                w_enhanced=blend[0],
                w_optimizer=blend[1],
                w_gate=blend[2],
                gate_weights=dict(_DEFAULT_GATE[fam]),
            )
            ws.save_checkpoint()
            self._weights[fam] = ws
        logger.info("WeightTuner: initialised with expert-designed defaults")

    def _save_state(self) -> None:
        try:
            data: Dict = {
                "weights": {fam: ws.to_dict() for fam, ws in self._weights.items()},
                "bandit":  self._bandit.to_dict(),
                "lr_model": self._lr.to_dict(),
                "symbol_stats": {
                    sym: {"total_trades": ss.total_trades, "wins": ss.wins,
                          "total_pnl": round(ss.total_pnl, 6),
                          "last_updated": ss.last_updated}
                    for sym, ss in self._symbol_stats.items()
                },
                "_meta": {
                    "version": "2.0",
                    "last_save": datetime.utcnow().isoformat(),
                },
            }
            tmp = self.STATE_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            tmp.replace(self.STATE_FILE)
        except Exception as exc:
            logger.warning("WeightTuner: save failed: %s", exc)

    def _load_state(self) -> bool:
        if not self.STATE_FILE.exists():
            return False
        try:
            with open(self.STATE_FILE, encoding="utf-8") as fh:
                data = json.load(fh)

            # Regime weights
            for fam, d in data.get("weights", {}).items():
                ws = RegimeWeightSet.from_dict(d)
                # Forward-compat: fill any new gate names
                for gn in _DEFAULT_GATE.get(fam, _DEFAULT_GATE["default"]):
                    ws.gate_weights.setdefault(gn, _DEFAULT_GATE["default"].get(gn, 1.8))
                self._weights[fam] = ws

            # Bandit
            self._bandit.load_dict(data.get("bandit", {}))

            # LR model
            if "lr_model" in data:
                self._lr = LogisticRegressionConfidence.from_dict(data["lr_model"])

            # Symbol stats
            for sym, sd in data.get("symbol_stats", {}).items():
                ss = SymbolStats(symbol=sym)
                ss.total_trades = sd.get("total_trades", 0)
                ss.wins = sd.get("wins", 0)
                ss.total_pnl = sd.get("total_pnl", 0.0)
                ss.last_updated = sd.get("last_updated", "")
                self._symbol_stats[sym] = ss

            logger.info(
                "WeightTuner: loaded state (%d regime families, LR %d samples)",
                len(self._weights), self._lr._n_samples,
            )
            return True
        except Exception as exc:
            logger.warning("WeightTuner: load failed (%s) — using defaults", exc)
            return False


# ---------------------------------------------------------------------------
# SINGLETON + PUBLIC FUNCTIONS
# ---------------------------------------------------------------------------

_tuner_instance: Optional[SelfLearningWeightTuner] = None
_tuner_lock = threading.Lock()


def get_weight_tuner() -> SelfLearningWeightTuner:
    """Return (or lazily create) the process-wide SelfLearningWeightTuner."""
    global _tuner_instance
    if _tuner_instance is None:
        with _tuner_lock:
            if _tuner_instance is None:
                _tuner_instance = SelfLearningWeightTuner()
    return _tuner_instance


def load_dynamic_weights(regime: str = "default") -> Dict[str, float]:
    """
    Return regime-specific signal weights in [-3.0, 3.0].

    Usage (exact user-specified formula):
        weights = load_dynamic_weights(regime)
        score += weights["trend"]  * trend_strength   # 0-1
        score += weights["volume"] * volume_ratio     # 0-1
        score += weights["rsi"]    * rsi_signal       # 0-1
        score += weights["regime"] * regime_score     # 0-1

    Safety: weights are always clamped to [MIN_WEIGHT, MAX_WEIGHT] = [-3.0, 3.0].
    """
    try:
        return get_weight_tuner().get_signal_weights(regime)
    except Exception:
        return dict(_DEFAULT_SIGNAL.get(
            _REGIME_FAMILY.get(str(regime).lower(), _DEFAULT_FAMILY),
            _DEFAULT_SIGNAL["default"],
        ))
