"""
NIJA Adaptive Aggression Engine
================================

Automatically scales every trading parameter to match account size so the bot
behaves appropriately at each stage of growth:

  MICRO  ($15  – $200)  →  "Trade Loose"   — wide filters, high concentration
  SMART  ($200 – $2000) →  "Trade Smart"   — balanced risk, moderate conviction
  ELITE  ($2000+)       →  "Trade Elite"   — strict filters, highest conviction

Why three tiers?
-----------------
A $50 account *must* trade more often with fewer conditions — the opportunity
cost of sitting out is too high and tight filters will produce zero trades.
A $5 000 account can afford patience and selectivity — tighter thresholds
protect larger capital while still generating quality signals.

Parameters tuned per tier
--------------------------
  min_signal_confidence   AI gate threshold (0–1 float).  Lower → more trades.
  min_quality_score       Entry quality score (0–100).    Lower → more trades.
  min_adx                 ADX trend-strength floor.       Lower → more markets pass.
  min_risk_reward         Minimum R:R ratio required.
  position_size_pct       Base position size as % of balance.
  max_positions           Max concurrent open positions.
  stop_loss_pct           Default stop-loss distance (%).
  take_profit_multiplier  Scales the strategy profit-target (1.0 = unchanged).
  mtf_required            Whether MTF confirmation must pass before entry.
  regime_strict           If True, block entries in CHOP or CRASH regimes.
  ai_skip_score_floor     AI confidence engine skip boundary (0–100).

Architecture
------------
::

    ┌───────────────────────────────────────────────────────────────┐
    │                   AdaptiveAggressionEngine                    │
    │                                                               │
    │  get_profile(balance_usd)   → AggressionProfile              │
    │  get_tier(balance_usd)      → AggressionTier                 │
    │  get_report()               → Dict                           │
    └───────────────────────────────────────────────────────────────┘

Usage
------
::

    from bot.adaptive_aggression_engine import (
        get_adaptive_aggression_engine,
        AggressionProfile,
    )

    engine = get_adaptive_aggression_engine()
    profile = engine.get_profile(account_balance)

    # ── skip_reasons pattern (trade entry gate) ──────────────────
    skip_reasons = []

    if ai_score < profile.min_signal_confidence:
        skip_reasons.append("AI")

    if profile.mtf_required and not mtf_confirmed:
        skip_reasons.append("MTF")

    if profile.regime_strict and regime_blocked:
        skip_reasons.append("REGIME")

    if skip_reasons:
        logger.info(
            f"🚫 TRADE SKIPPED → {symbol} | reasons={skip_reasons} "
            f"[tier={profile.tier.value}]"
        )
        continue

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger("nija.adaptive_aggression")

# ---------------------------------------------------------------------------
# Tier enum
# ---------------------------------------------------------------------------

class AggressionTier(str, Enum):
    MICRO = "MICRO"   # $15  – $199   → Trade Loose
    SMART = "SMART"   # $200 – $1999  → Trade Smart
    ELITE = "ELITE"   # $2000+        → Trade Elite


# ---------------------------------------------------------------------------
# Balance boundaries (USD)
# ---------------------------------------------------------------------------

MICRO_MAX_BALANCE: float = 200.0    # Below this → MICRO tier
SMART_MAX_BALANCE: float = 2_000.0  # Below this → SMART tier  (≥ this → ELITE)


# ---------------------------------------------------------------------------
# Per-tier parameter tables
# ---------------------------------------------------------------------------

# Each row maps AggressionTier → parameter value.
# These are the *default* values; callers may pass a custom AggressionConfig
# to the factory to override them.

_TIER_DEFAULTS: Dict[AggressionTier, Dict] = {
    # ────────────────────────────────────────────────────────────────
    # MICRO  ·  $15 – $200  ·  "Trade Loose"
    # Goal: maximise trade frequency.  Capital growth is the priority.
    # Wide filters, high concentration, accept lower-confidence signals.
    # ────────────────────────────────────────────────────────────────
    AggressionTier.MICRO: dict(
        label="Trade Loose 🔓",
        min_signal_confidence=0.30,   # AI gate: accept 30%+ signals (lowered from 55% to allow more entries)
        min_quality_score=40.0,       # Entry quality floor (lowered from 50 to match 60→40 target)
        min_adx=5.0,                  # Accept very weak trends (lowered from 8 to 5)
        min_risk_reward=1.5,          # Lower R:R bar
        position_size_pct=20.0,       # 20 % of balance per trade
        max_positions=2,              # Concentrated — 2 simultaneous trades
        stop_loss_pct=2.0,            # 2 % stop (wider room to breathe)
        take_profit_multiplier=1.2,   # Push take-profit 20 % higher for bigger wins
        mtf_required=False,           # MTF confirmation optional — don't block
        regime_strict=False,          # Trade even in CHOP; regime is advisory only
        ai_skip_score_floor=40.0,     # AI confidence engine: skip only below 40 /100 (lowered from 45)
    ),

    # ────────────────────────────────────────────────────────────────
    # SMART  ·  $200 – $2 000  ·  "Trade Smart"
    # Goal: balanced risk / reward.  Quality over quantity begins here.
    # ────────────────────────────────────────────────────────────────
    AggressionTier.SMART: dict(
        label="Trade Smart 🎯",
        min_signal_confidence=0.68,   # AI gate: 68 %+ (default system value)
        min_quality_score=65.0,       # Standard quality floor
        min_adx=15.0,                 # Require moderate trend strength
        min_risk_reward=1.8,          # Standard R:R
        position_size_pct=12.0,       # 12 % of balance per trade
        max_positions=3,              # Moderate diversification
        stop_loss_pct=1.5,            # 1.5 % stop
        take_profit_multiplier=1.0,   # No adjustment — use strategy default
        mtf_required=True,            # Enforce MTF confirmation when available
        regime_strict=False,          # Still trade CHOP but respect CRASH blocks
        ai_skip_score_floor=55.0,     # AI skip boundary: 55 /100
    ),

    # ────────────────────────────────────────────────────────────────
    # ELITE  ·  $2 000+  ·  "Trade Elite"
    # Goal: protect larger capital with strict discipline.
    # Only the highest-conviction setups with full confirmation.
    # ────────────────────────────────────────────────────────────────
    AggressionTier.ELITE: dict(
        label="Trade Elite 👑",
        min_signal_confidence=0.78,   # AI gate: 78 %+ — high conviction only
        min_quality_score=72.0,       # High quality floor
        min_adx=22.0,                 # Require strong trend (ADX 22+)
        min_risk_reward=2.2,          # High R:R standard
        position_size_pct=7.0,        # 7 % of balance per trade (protect capital)
        max_positions=5,              # Diversify across more positions
        stop_loss_pct=1.0,            # 1 % stop (tight; size is smaller)
        take_profit_multiplier=0.9,   # Slightly tighter target — lock wins quickly
        mtf_required=True,            # MTF confirmation required
        regime_strict=True,           # Block entries in CHOP and CRASH regimes
        ai_skip_score_floor=65.0,     # AI skip boundary: 65 /100 (default)
    ),
}


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class AggressionConfig:
    """Boundary and override configuration for the engine.

    All threshold fields default to ``None`` which means "use the built-in
    per-tier table".  Set a field to a concrete value to override that
    parameter across all tiers uniformly.
    """
    # Balance tier boundaries (USD)
    micro_max_balance: float = MICRO_MAX_BALANCE
    smart_max_balance: float = SMART_MAX_BALANCE

    # Optional uniform overrides (None = use per-tier defaults)
    min_signal_confidence: Optional[float] = None
    min_quality_score: Optional[float] = None
    min_adx: Optional[float] = None
    min_risk_reward: Optional[float] = None
    position_size_pct: Optional[float] = None
    max_positions: Optional[int] = None
    stop_loss_pct: Optional[float] = None
    take_profit_multiplier: Optional[float] = None
    mtf_required: Optional[bool] = None
    regime_strict: Optional[bool] = None
    ai_skip_score_floor: Optional[float] = None


# ---------------------------------------------------------------------------
# Profile dataclass  (result returned to callers)
# ---------------------------------------------------------------------------

@dataclass
class AggressionProfile:
    """Resolved trading parameters for the current balance tier.

    All fields are ready to use directly in entry-decision logic.
    """
    tier: AggressionTier
    label: str
    balance_usd: float

    # Signal & quality filters
    min_signal_confidence: float   # 0–1 float; AI score must be ≥ this
    min_quality_score: float       # 0–100; entry quality must be ≥ this
    min_adx: float                 # ADX must be ≥ this
    min_risk_reward: float         # R:R must be ≥ this

    # Position sizing
    position_size_pct: float       # % of balance per trade
    max_positions: int             # Max concurrent open positions

    # Risk / reward
    stop_loss_pct: float           # Default stop-loss (%)
    take_profit_multiplier: float  # Multiplier applied to strategy take-profit

    # Gate flags
    mtf_required: bool             # True → entry blocked when MTF not confirmed
    regime_strict: bool            # True → entry blocked in CHOP / CRASH regime

    # AI confidence engine
    ai_skip_score_floor: float     # AI confidence score below which entry is skipped

    # Metadata
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def should_skip_entry(
        self,
        *,
        ai_score: float,
        mtf_confirmed: bool,
        regime_blocked: bool,
        symbol: str = "",
    ) -> list[str]:
        """
        Evaluate the three primary skip conditions and return a list of
        reason labels for any that fail.

        Parameters
        ----------
        ai_score:
            Normalised AI/signal confidence (0–1 float) or raw score (0–100).
            Values > 1.0 are assumed to be on the 0–100 scale and are divided
            by 100 for comparison.
        mtf_confirmed:
            True when the multi-timeframe confirmation check passed.
        regime_blocked:
            True when the regime controller/engine has blocked entries.
        symbol:
            Optional symbol string for log context.

        Returns
        -------
        list[str]
            Empty list → proceed with entry.
            Non-empty → log the reasons and skip.
        """
        # Normalise ai_score to 0-1 range
        score = ai_score / 100.0 if ai_score > 1.0 else ai_score

        skip_reasons: list[str] = []

        if score < self.min_signal_confidence:
            skip_reasons.append("AI")

        if self.mtf_required and not mtf_confirmed:
            skip_reasons.append("MTF")

        if self.regime_strict and regime_blocked:
            skip_reasons.append("REGIME")

        if skip_reasons and symbol:
            logger.info(
                "🚫 TRADE SKIPPED → %s | reasons=%s [tier=%s balance=$%.0f]",
                symbol,
                skip_reasons,
                self.tier.value,
                self.balance_usd,
            )

        return skip_reasons


# ---------------------------------------------------------------------------
# Core engine class
# ---------------------------------------------------------------------------

class AdaptiveAggressionEngine:
    """
    Resolves trading parameters for any account balance.

    Thread-safe: all public methods acquire ``_lock``.

    Parameters
    ----------
    config:
        Optional :class:`AggressionConfig` to override defaults.
    """

    def __init__(self, config: Optional[AggressionConfig] = None) -> None:
        self._config = config or AggressionConfig()
        self._lock = threading.Lock()
        self._last_profile: Optional[AggressionProfile] = None
        logger.info(
            "✅ AdaptiveAggressionEngine initialised "
            "(MICRO<$%.0f | SMART<$%.0f | ELITE≥$%.0f)",
            self._config.micro_max_balance,
            self._config.smart_max_balance,
            self._config.smart_max_balance,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tier(self, balance_usd: float) -> AggressionTier:
        """Return the :class:`AggressionTier` that applies at *balance_usd*."""
        if balance_usd < self._config.micro_max_balance:
            return AggressionTier.MICRO
        if balance_usd < self._config.smart_max_balance:
            return AggressionTier.SMART
        return AggressionTier.ELITE

    def get_profile(self, balance_usd: float) -> AggressionProfile:
        """
        Resolve and return the full :class:`AggressionProfile` for the given
        account balance.

        Results are cached; repeated calls with the same balance return
        instantly from cache.

        Parameters
        ----------
        balance_usd:
            Current account balance in USD (≥ 0).
        """
        with self._lock:
            tier = self.get_tier(balance_usd)
            defaults = dict(_TIER_DEFAULTS[tier])
            cfg = self._config

            def _pick(key: str, cast=None):
                """Return config override if set, otherwise tier default."""
                override = getattr(cfg, key, None)
                if override is not None:
                    return cast(override) if cast else override
                return defaults[key]

            profile = AggressionProfile(
                tier=tier,
                label=defaults["label"],
                balance_usd=balance_usd,
                min_signal_confidence=_pick("min_signal_confidence", float),
                min_quality_score=_pick("min_quality_score", float),
                min_adx=_pick("min_adx", float),
                min_risk_reward=_pick("min_risk_reward", float),
                position_size_pct=_pick("position_size_pct", float),
                max_positions=_pick("max_positions", int),
                stop_loss_pct=_pick("stop_loss_pct", float),
                take_profit_multiplier=_pick("take_profit_multiplier", float),
                mtf_required=_pick("mtf_required", bool),
                regime_strict=_pick("regime_strict", bool),
                ai_skip_score_floor=_pick("ai_skip_score_floor", float),
            )

            # Log tier transitions
            if (
                self._last_profile is None
                or self._last_profile.tier != profile.tier
            ):
                logger.info(
                    "📊 AdaptiveAggression tier → %s (%s) "
                    "| balance=$%.2f | conf≥%.0f%% | adx≥%.0f "
                    "| size=%.0f%% | mtf=%s | regime_strict=%s",
                    profile.tier.value,
                    profile.label,
                    balance_usd,
                    profile.min_signal_confidence * 100,
                    profile.min_adx,
                    profile.position_size_pct,
                    "✅" if profile.mtf_required else "⬜",
                    "✅" if profile.regime_strict else "⬜",
                )

            self._last_profile = profile
            return profile

    def get_report(self) -> Dict:
        """Return a snapshot dict suitable for dashboards / JSON logging."""
        with self._lock:
            if self._last_profile is None:
                return {"status": "no_profile_yet"}
            p = self._last_profile
            return {
                "tier": p.tier.value,
                "label": p.label,
                "balance_usd": p.balance_usd,
                "min_signal_confidence": p.min_signal_confidence,
                "min_quality_score": p.min_quality_score,
                "min_adx": p.min_adx,
                "min_risk_reward": p.min_risk_reward,
                "position_size_pct": p.position_size_pct,
                "max_positions": p.max_positions,
                "stop_loss_pct": p.stop_loss_pct,
                "take_profit_multiplier": p.take_profit_multiplier,
                "mtf_required": p.mtf_required,
                "regime_strict": p.regime_strict,
                "ai_skip_score_floor": p.ai_skip_score_floor,
                "timestamp": p.timestamp,
            }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_engine_instance: Optional[AdaptiveAggressionEngine] = None
_engine_lock = threading.Lock()


def get_adaptive_aggression_engine(
    config: Optional[AggressionConfig] = None,
) -> AdaptiveAggressionEngine:
    """Return the singleton :class:`AdaptiveAggressionEngine`."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = AdaptiveAggressionEngine(config=config)
    return _engine_instance
