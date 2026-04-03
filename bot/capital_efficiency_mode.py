"""
NIJA Capital Efficiency Mode
=============================
Adjusts trading aggressiveness based on account size, idle state, and
optimizer feedback so every dollar works at the right intensity level.

Mode tiers (by account balance):
  AGGRESSIVE_SMALL  (<$500)   -- min_score 1.5, top-80% ranking, max 4 positions
  BALANCED          (<$2000)  -- min_score 3.0, top-50% ranking, max 5 positions
  STANDARD          ($2000+)  -- min_score 3.0, top-40% ranking, max 7 positions

Extra features
--------------
* **Force-trade-after-idle** (Step 3): after IDLE_CYCLES_THRESHOLD consecutive
  cycles with no executed trade, thresholds are temporarily loosened.
* **Min trade-size enforcement** (Step 4): $10 hard floor regardless of mode.
* **Mid-tier boost** (Step 5): score >= 2.5 AND optimizer_bonus >= 1.0 ->
  treat setup as high priority (bypass percentile gate).

Usage
-----
    from bot.capital_efficiency_mode import get_capital_efficiency_mode

    cem = get_capital_efficiency_mode()
    cem.update(balance_usd)           # call once per cycle
    cfg = cem.get_config()            # read effective config (idle-adjusted)

    if not cem.is_valid_trade_size(position_size):
        skip_trade()                  # Step 4 enforcement

    if cem.is_mid_tier_boost(score, optimizer_bonus):
        bypass_ranker()               # Step 5
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("nija.capital_efficiency_mode")

# ---------------------------------------------------------------------------
# Thresholds (all overridable via subclass or direct attribute assignment)
# ---------------------------------------------------------------------------

IDLE_CYCLES_THRESHOLD: int   = 3     # cycles without a trade -> loosen (was 5)
IDLE_SCORE_DELTA: float      = 0.7   # subtract from min_score when idle (was 0.5)
IDLE_PERCENTILE_DELTA: float = 0.20  # subtract from pass_percentile when idle
IDLE_CONFIDENCE_DELTA: float = 0.18  # add to confidence_delta when idle (raised 0.08→0.18: force opportunity after 100+ dead cycles)

MIN_TRADE_SIZE_USD: float = 10.0     # Step 4: absolute hard floor

MID_TIER_SCORE_FLOOR: float = 2.5   # Step 5: score threshold
MID_TIER_BONUS_FLOOR: float = 1.0   # Step 5: optimizer_bonus threshold


# ---------------------------------------------------------------------------
# Mode config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapitalModeConfig:
    """Resolved parameters for a single capital efficiency tier."""
    mode: str
    min_score: float          # minimum signal score to enter
    pass_percentile: float    # ranker percentile gate (lower = more permissive)
    max_positions: int        # soft cap on concurrent open positions
    min_size_usd: float       # minimum position size in USD
    confidence_delta: float   # additive nudge to sniper confidence
    description: str


# Default mode configs
_AGGRESSIVE_SMALL = CapitalModeConfig(
    mode="AGGRESSIVE_SMALL",
    min_score=1.5,            # lowered 2.0→1.5 so more setups qualify on small accounts
    pass_percentile=0.20,     # top 80% pass (lowered 0.25→0.20 for small-cap mode)
    max_positions=4,
    min_size_usd=MIN_TRADE_SIZE_USD,
    confidence_delta=+0.05,   # loosen gate for small accounts
    description="Small account (<$500): concentrated high-conviction entries",
)

_BALANCED = CapitalModeConfig(
    mode="BALANCED",
    min_score=3.0,
    pass_percentile=0.50,     # top 50% pass
    max_positions=5,
    min_size_usd=MIN_TRADE_SIZE_USD,
    confidence_delta=0.0,
    description="Mid-size account (<$2000): balanced quality vs frequency",
)

_STANDARD = CapitalModeConfig(
    mode="STANDARD",
    min_score=3.0,
    pass_percentile=0.60,     # top 40% pass (default)
    max_positions=7,
    min_size_usd=MIN_TRADE_SIZE_USD,
    confidence_delta=0.0,
    description="Larger account ($2000+): diversified multi-position operation",
)


def _base_config_for(balance: float) -> CapitalModeConfig:
    """Map a balance to the appropriate base mode config."""
    if balance < 500.0:
        return _AGGRESSIVE_SMALL
    if balance < 2_000.0:
        return _BALANCED
    return _STANDARD


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CapitalEfficiencyMode:
    """
    Thread-safe capital efficiency manager.

    Call ``update(balance_usd)`` each trading cycle to refresh the tier.
    Call ``record_trade()`` when a trade fires (resets idle counter).
    Call ``record_no_trade()`` when a cycle produces no entry.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._balance: float = 0.0
        self._base_config: CapitalModeConfig = _AGGRESSIVE_SMALL
        self._idle_cycles: int = 0
        logger.info(
            "✅ CapitalEfficiencyMode initialised — "
            "AGGRESSIVE_SMALL(<$500) / BALANCED(<$2000) / STANDARD($2000+)"
        )

    # ── Cycle API ──────────────────────────────────────────────────────────

    def update(self, balance_usd: float) -> "CapitalEfficiencyMode":
        """Refresh the mode tier from the latest account balance."""
        with self._lock:
            self._balance = max(0.0, float(balance_usd or 0.0))
            new_cfg = _base_config_for(self._balance)
            if new_cfg.mode != self._base_config.mode:
                logger.info(
                    "💰 CapitalEfficiencyMode: %s -> %s (balance=$%.2f)",
                    self._base_config.mode, new_cfg.mode, self._balance,
                )
            self._base_config = new_cfg
        return self

    def record_trade(self) -> None:
        """A trade was executed this cycle — reset the idle counter."""
        with self._lock:
            if self._idle_cycles > 0:
                logger.debug(
                    "CapitalEfficiencyMode: trade executed — idle streak reset (was %d)",
                    self._idle_cycles,
                )
            self._idle_cycles = 0

    def record_no_trade(self) -> None:
        """No trade was executed this cycle — increment the idle counter."""
        with self._lock:
            self._idle_cycles += 1
            logger.debug(
                "CapitalEfficiencyMode: no trade — idle_cycles=%d (threshold=%d)",
                self._idle_cycles, IDLE_CYCLES_THRESHOLD,
            )

    # ── Config resolution ──────────────────────────────────────────────────

    def get_config(self) -> CapitalModeConfig:
        """
        Return the effective config, applying idle-loosening when active.

        After IDLE_CYCLES_THRESHOLD consecutive cycles with no trade, the
        min_score, pass_percentile, and confidence_delta are all loosened so
        the bot escapes dead zones without user intervention.
        """
        with self._lock:
            base  = self._base_config
            idle  = self._idle_cycles

        if idle < IDLE_CYCLES_THRESHOLD:
            return base

        # --- Idle boost: lower the gate temporarily ---
        loosened = CapitalModeConfig(
            mode=f"{base.mode}+IDLE_BOOST",
            min_score=max(1.0, base.min_score - IDLE_SCORE_DELTA),
            pass_percentile=max(0.10, base.pass_percentile - IDLE_PERCENTILE_DELTA),
            max_positions=base.max_positions,
            min_size_usd=base.min_size_usd,
            confidence_delta=base.confidence_delta + IDLE_CONFIDENCE_DELTA,
            description=f"{base.description} [IDLE x{idle} — thresholds loosened]",
        )
        logger.info(
            "🔓 CapitalEfficiencyMode IDLE BOOST (idle=%d): "
            "min_score %.1f->%.1f  pass_pct %.0f%%->%.0f%%  conf_delta %+.2f->%+.2f",
            idle,
            base.min_score,      loosened.min_score,
            base.pass_percentile * 100, loosened.pass_percentile * 100,
            base.confidence_delta, loosened.confidence_delta,
        )
        return loosened

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        """Current base mode name (without idle suffix)."""
        with self._lock:
            return self._base_config.mode

    @property
    def idle_cycles(self) -> int:
        """Number of consecutive cycles without an executed trade."""
        with self._lock:
            return self._idle_cycles

    # ── Static helpers ──────────────────────────────────────────────────────

    @staticmethod
    def is_valid_trade_size(size_usd: float) -> bool:
        """
        Step 4 enforcement: return True if *size_usd* meets the $10 hard floor.

        Positions below this threshold are dust trades that lose money to fees.
        """
        return size_usd >= MIN_TRADE_SIZE_USD

    @staticmethod
    def is_mid_tier_boost(score: float, optimizer_bonus: float) -> bool:
        """
        Step 5 check: return True if this setup qualifies for mid-tier priority.

        Criteria: score >= 2.5 AND optimizer_bonus >= 1.0.

        When True the caller should bypass the percentile gate so near-threshold
        setups with strong optimizer backing are not over-filtered.
        """
        return score >= MID_TIER_SCORE_FLOOR and optimizer_bonus >= MID_TIER_BONUS_FLOOR

    # ── Reporting ───────────────────────────────────────────────────────────

    def get_report(self) -> dict:
        """Return a JSON-serialisable snapshot for logging or API endpoints."""
        cfg = self.get_config()
        with self._lock:
            return {
                "mode":             cfg.mode,
                "balance":          round(self._balance, 2),
                "idle_cycles":      self._idle_cycles,
                "idle_boost_active": self._idle_cycles >= IDLE_CYCLES_THRESHOLD,
                "min_score":        cfg.min_score,
                "pass_percentile":  cfg.pass_percentile,
                "max_positions":    cfg.max_positions,
                "min_size_usd":     cfg.min_size_usd,
                "confidence_delta": cfg.confidence_delta,
                "description":      cfg.description,
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[CapitalEfficiencyMode] = None
_lock = threading.Lock()


def get_capital_efficiency_mode() -> CapitalEfficiencyMode:
    """Return the process-wide singleton CapitalEfficiencyMode."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = CapitalEfficiencyMode()
    return _instance
