"""
NIJA High-Frequency Flip Mode
==============================
One-switch bundle that wires together every speed-optimisation layer for
maximum daily trade throughput and fast profit realisation.

What it does
------------
• R:R minimum dropped to 1.3 (from 2.0)        → more valid signals qualify
• AI confidence gate lowered to 0.33 (from 0.55) → filter stays smart but loose
• Sniper filter confidence relaxed to 0.35 (from 0.50) → more entries pass
• Sniper ADX minimum relaxed to 8 (from 12)     → choppy pairs not over-blocked
• Aggression mode forced to AGGRESSIVE           → lower thresholds, more trades
• Trade frequency targets raised (6/hr, 80/day) → capital deployed faster
• Scan cycle shortened to 20 s (from 150 s)     → micro/small-cap focus
• Minimum net-profit gate dropped to 0.4 %      → tight HF scalps allowed
• Profit gate safety multiple lowered to 1.3×   → realistic for HF scalps
• HF Scalping Mode auto-enabled                 → fast re-deployment of capital
• TradeCluster re-enabled                       → stack wins in strong trends
• CrossBrokerArb re-enabled                     → capture cross-venue spreads

Activation
----------
Set the environment variable before starting the bot::

    HF_FLIP_MODE=1

All individual parameters can be fine-tuned via their own env vars (see
``FlipModeConfig`` docstring).

Architecture
------------
``HFFlipMode`` is a singleton — call ``get_hf_flip_mode()`` from any module.
The constructor calls ``_apply_env_overrides()`` so all downstream singletons
(HFScalpingMode, AggressionModeController, AITradeQualityFilter, …) pick up
the correct thresholds when they are first created.

For subsystems whose settings are not env-var-driven, call the matching
``apply_to_*()`` helper immediately after creating the subsystem instance in
``trading_strategy.py``.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("nija.hf_flip_mode")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "")
    if raw.lower() in ("1", "true", "yes", "on"):
        return True
    if raw.lower() in ("0", "false", "no", "off"):
        return False
    return default


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FlipModeConfig:
    """
    All tunable parameters for HF Flip Mode.

    Every field can be overridden at startup via a matching environment
    variable (shown in the comment next to each field).
    """

    # ── Master switch ──────────────────────────────────────────────────────────
    enabled: bool = field(
        default_factory=lambda: _env_bool("HF_FLIP_MODE", False)
    )
    # env: HF_FLIP_MODE (1/true/yes to enable; disabled by default)

    # ── Risk / Reward ─────────────────────────────────────────────────────────
    min_rr_ratio: float = field(
        default_factory=lambda: _env_float("FLIP_MIN_RR", 1.3)
    )
    # env: FLIP_MIN_RR  (minimum acceptable R:R, default 1.3)

    # ── Net profit gate ───────────────────────────────────────────────────────
    min_net_profit_pct: float = field(
        default_factory=lambda: _env_float("FLIP_MIN_NET_PROFIT_PCT", 0.4)
    )
    # env: FLIP_MIN_NET_PROFIT_PCT  (minimum net profit %, default 0.4)

    profit_gate_safety_multiple: float = field(
        default_factory=lambda: _env_float("FLIP_PROFIT_GATE_MULTIPLE", 1.3)
    )
    # env: FLIP_PROFIT_GATE_MULTIPLE  (cost×multiple = required target, default 1.3)

    # ── AI confidence ─────────────────────────────────────────────────────────
    ai_min_win_probability: float = field(
        default_factory=lambda: _env_float("FLIP_AI_MIN_WIN_PROB", 0.33)
    )
    # env: FLIP_AI_MIN_WIN_PROB  (AI win-prob gate, default 0.33)

    # ── Sniper filter ─────────────────────────────────────────────────────────
    sniper_min_confidence: float = field(
        default_factory=lambda: _env_float("FLIP_SNIPER_MIN_CONFIDENCE", 0.35)
    )
    # env: FLIP_SNIPER_MIN_CONFIDENCE  (relaxed pillar-4 gate, default 0.35)

    sniper_min_adx: float = field(
        default_factory=lambda: _env_float("FLIP_SNIPER_MIN_ADX", 8.0)
    )
    # env: FLIP_SNIPER_MIN_ADX  (relaxed chop filter, default 8.0)

    # ── Aggression mode ───────────────────────────────────────────────────────
    aggression_mode: str = field(
        default_factory=lambda: os.environ.get("FLIP_AGGRESSION_MODE", "AGGRESSIVE")
    )
    # env: FLIP_AGGRESSION_MODE  (SAFE | BALANCED | AGGRESSIVE, default AGGRESSIVE)

    # ── Trade frequency targets ───────────────────────────────────────────────
    min_trades_per_hour: float = field(
        default_factory=lambda: _env_float("FLIP_MIN_TRADES_PER_HOUR", 6.0)
    )
    # env: FLIP_MIN_TRADES_PER_HOUR  (default 6)

    min_trades_per_day: float = field(
        default_factory=lambda: _env_float("FLIP_MIN_TRADES_PER_DAY", 80.0)
    )
    # env: FLIP_MIN_TRADES_PER_DAY  (default 80)

    # ── Scan cycle ────────────────────────────────────────────────────────────
    cycle_interval_seconds: int = field(
        default_factory=lambda: _env_int("FLIP_CYCLE_SECONDS", 20)
    )
    # env: FLIP_CYCLE_SECONDS  (20 s vs normal 150 s)

    # ── Layer enablement ─────────────────────────────────────────────────────
    enable_trade_cluster: bool = field(
        default_factory=lambda: _env_bool("FLIP_ENABLE_TRADE_CLUSTER", True)
    )
    # env: FLIP_ENABLE_TRADE_CLUSTER  (re-enables TradeCluster for trend stacking)

    enable_cross_broker_arb: bool = field(
        default_factory=lambda: _env_bool("FLIP_ENABLE_CROSS_BROKER_ARB", True)
    )
    # env: FLIP_ENABLE_CROSS_BROKER_ARB  (re-enables CrossBrokerArb for spread capture)


# ──────────────────────────────────────────────────────────────────────────────
# Core class
# ──────────────────────────────────────────────────────────────────────────────

class HFFlipMode:
    """
    High-frequency flip mode coordinator.

    Singleton — obtain via ``get_hf_flip_mode()``.
    """

    def __init__(self, config: Optional[FlipModeConfig] = None) -> None:
        self.config = config or FlipModeConfig()

        if self.config.enabled:
            self._apply_env_overrides()
            self._log_activation()
        else:
            logger.info(
                "ℹ️  HF Flip Mode INACTIVE — set HF_FLIP_MODE=1 to enable "
                "fast daily profit mode"
            )

    # ── Env override ───────────────────────────────────────────────────────────

    def _apply_env_overrides(self) -> None:
        """
        Set environment variables so all downstream singletons (HFScalpingMode,
        AggressionModeController, AITradeQualityFilter, NetProfitGate, …) pick
        up the correct thresholds when they are first created.

        Uses ``setdefault`` so explicit env vars from the operator always win.
        """
        # AI win-probability gate
        os.environ.setdefault("AI_MIN_WIN_PROB", str(self.config.ai_min_win_probability))

        # Aggression mode
        os.environ.setdefault("AGGRESSION_MODE", self.config.aggression_mode)

        # HF Scalping Mode — auto-enable + align its thresholds with flip config
        os.environ.setdefault("HF_SCALP_MODE", "1")
        os.environ.setdefault(
            "HF_SCALP_CYCLE_SECONDS", str(self.config.cycle_interval_seconds)
        )
        os.environ.setdefault(
            "HF_SCALP_MIN_CONFIDENCE", str(self.config.sniper_min_confidence)
        )
        os.environ.setdefault(
            "HF_SCALP_MIN_ADX", str(int(self.config.sniper_min_adx))
        )
        os.environ.setdefault(
            "HF_SCALP_PROFIT_TARGET_PCT", str(self.config.min_net_profit_pct)
        )

        # Net profit gate:
        #   min_net_profit_pct is stored as a human-readable percentage (0.4 = 0.4%).
        #   NET_PROFIT_MIN_TARGET_PCT is read as a machine fraction (0.004 = 0.4%),
        #   so we divide by 100 when setting the env var.
        os.environ.setdefault(
            "NET_PROFIT_MIN_TARGET_PCT",
            str(self.config.min_net_profit_pct / 100.0),
        )
        os.environ.setdefault(
            "NET_PROFIT_SAFETY_MULTIPLE",
            str(self.config.profit_gate_safety_multiple),
        )

        # Sniper filter thresholds
        os.environ.setdefault(
            "SNIPER_MIN_CONFIDENCE", str(self.config.sniper_min_confidence)
        )
        os.environ.setdefault(
            "SNIPER_MIN_ADX", str(self.config.sniper_min_adx)
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Return True when HF Flip Mode is active."""
        return self.config.enabled

    @property
    def trade_cluster_enabled(self) -> bool:
        """True when flip mode should re-enable the Trade Cluster Engine."""
        return self.config.enabled and self.config.enable_trade_cluster

    @property
    def cross_broker_arb_enabled(self) -> bool:
        """True when flip mode should re-enable the Cross-Broker Arb Monitor."""
        return self.config.enabled and self.config.enable_cross_broker_arb

    # ── Subsystem patch helpers ────────────────────────────────────────────────

    def apply_to_sniper_filter(self, sniper_filter) -> None:
        """
        Patch a live ``SniperFilter`` instance with relaxed flip mode gates.

        Call this immediately after ``get_sniper_filter()`` in
        ``TradingStrategy.__init__``.

        Note: this accesses the ``_cfg`` private attribute of ``SniperFilter``
        because the class exposes no public configuration-update method.  This
        is intentional — the singleton filter shares one ``SniperConfig``
        instance for the lifetime of the process, so mutating it in-place is
        safe and avoids re-creating the singleton.
        """
        if not self.config.enabled or sniper_filter is None:
            return
        cfg = getattr(sniper_filter, "_cfg", None)
        if cfg is None:
            return
        cfg.min_confidence = self.config.sniper_min_confidence
        cfg.min_adx = self.config.sniper_min_adx
        logger.info(
            "🔓 HF Flip: Sniper Filter relaxed — "
            "min_confidence=%.2f  min_adx=%.1f",
            self.config.sniper_min_confidence,
            self.config.sniper_min_adx,
        )

    def apply_to_ai_filter(self, ai_filter) -> None:
        """
        Patch a live ``AITradeQualityFilter`` instance with the flip mode
        win-probability threshold.

        Call this immediately after ``get_ai_trade_quality_filter()`` in
        ``TradingStrategy.__init__``.
        """
        if not self.config.enabled or ai_filter is None:
            return
        ai_filter.min_win_probability = self.config.ai_min_win_probability
        logger.info(
            "🧠 HF Flip: AI Filter relaxed — min_win_probability=%.2f",
            self.config.ai_min_win_probability,
        )

    def apply_to_net_profit_gate(self, gate) -> None:
        """
        Patch a live ``NetProfitGate`` instance with the flip mode safety
        multiple (1.3× vs default 2×).

        Call this immediately after ``get_net_profit_gate()`` in
        ``TradingStrategy.__init__``.
        """
        if not self.config.enabled or gate is None:
            return
        gate.safety_multiple = self.config.profit_gate_safety_multiple
        logger.info(
            "💰 HF Flip: Net Profit Gate relaxed — safety_multiple=%.1f×",
            self.config.profit_gate_safety_multiple,
        )

    # ── Status ─────────────────────────────────────────────────────────────────

    def status_dict(self) -> dict:
        """Return a JSON-serialisable status snapshot for dashboards."""
        return {
            "enabled": self.config.enabled,
            "min_rr_ratio": self.config.min_rr_ratio,
            "min_net_profit_pct": self.config.min_net_profit_pct,
            "profit_gate_safety_multiple": self.config.profit_gate_safety_multiple,
            "ai_min_win_probability": self.config.ai_min_win_probability,
            "sniper_min_confidence": self.config.sniper_min_confidence,
            "sniper_min_adx": self.config.sniper_min_adx,
            "aggression_mode": self.config.aggression_mode,
            "min_trades_per_hour": self.config.min_trades_per_hour,
            "min_trades_per_day": self.config.min_trades_per_day,
            "cycle_interval_seconds": self.config.cycle_interval_seconds,
            "trade_cluster_enabled": self.trade_cluster_enabled,
            "cross_broker_arb_enabled": self.cross_broker_arb_enabled,
        }

    # ── Logging ────────────────────────────────────────────────────────────────

    def _log_activation(self) -> None:
        cfg = self.config
        logger.info(
            "🔥🔥 HF FLIP MODE ACTIVE — fast daily profit mode engaged 🔥🔥"
        )
        logger.info(
            "   R:R≥%.1f | AI_win_prob≥%.2f | sniper_conf≥%.2f | ADX≥%.0f",
            cfg.min_rr_ratio,
            cfg.ai_min_win_probability,
            cfg.sniper_min_confidence,
            cfg.sniper_min_adx,
        )
        logger.info(
            "   net_profit≥%.1f%% | profit_gate×%.1f | aggression=%s | cycle=%ds",
            cfg.min_net_profit_pct,
            cfg.profit_gate_safety_multiple,
            cfg.aggression_mode,
            cfg.cycle_interval_seconds,
        )
        logger.info(
            "   freq≥%.0f/hr %.0f/day | TradeCluster=%s | CrossBrokerArb=%s",
            cfg.min_trades_per_hour,
            cfg.min_trades_per_day,
            "✅" if self.trade_cluster_enabled else "❌",
            "✅" if self.cross_broker_arb_enabled else "❌",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Singleton factory
# ──────────────────────────────────────────────────────────────────────────────

_flip_mode_instance: Optional[HFFlipMode] = None
_flip_mode_lock = threading.Lock()


def get_hf_flip_mode(config: Optional[FlipModeConfig] = None) -> HFFlipMode:
    """
    Return the thread-safe singleton ``HFFlipMode`` instance.

    Supply *config* only on the very first call to override defaults; it is
    ignored on subsequent calls.

    The singleton is intentionally created at import time in
    ``trading_strategy.py`` (before any other subsystem singleton is created)
    so that ``_apply_env_overrides()`` runs first and all env vars are in
    place before HFScalpingMode, AggressionModeController, etc. read them.
    """
    global _flip_mode_instance
    if _flip_mode_instance is None:
        with _flip_mode_lock:
            if _flip_mode_instance is None:
                _flip_mode_instance = HFFlipMode(config)
    return _flip_mode_instance


__all__ = [
    "HFFlipMode",
    "FlipModeConfig",
    "get_hf_flip_mode",
]
