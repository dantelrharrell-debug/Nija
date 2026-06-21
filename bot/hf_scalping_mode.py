"""
NIJA High-Frequency Micro Scalping Mode
=========================================

Enables a high-frequency micro scalping mode that dramatically increases trade
throughput by:

  • Reducing the inter-cycle scan interval to 60 s
  • Setting MIN_CONFIDENCE to 0.15 for faster entry triggers (growth config)
  • Setting volume filters (volume_threshold 0.0045 = 0.45 %, volume_min_threshold 0.002)
  • Relaxing ADX minimum to 3 and trend confirmation count to 2 (growth config)
  • Setting tight profit targets 1.2 % for rapid realisation (growth config)
  • Setting tight stop-losses 0.35 % (growth config)
  • Capping position hold time at 3 minutes so capital re-deploys quickly
  • Enforcing a per-hour trade rate cap (default 20) to avoid overtrading (growth config)

Activation
----------
Set the environment variable ``HF_SCALP_MODE=1`` (or ``true``/``yes``) before
starting the bot.  All other parameters can be overridden via the matching
environment variables documented on ``HFScalpConfig``.

Architecture
------------
``HFScalpingMode`` is a singleton — call ``get_hf_scalping_mode()`` from any
module; the first call creates the instance, subsequent calls return the same
object.

Integration hooks
-----------------
``bot.py``
    Replace ``time.sleep(150)`` with ``time.sleep(hf.get_cycle_interval())``.

``bot/nija_apex_strategy_v71.py``
    Call ``hf.apply_to_apex(apex_instance)`` once after the strategy is
    constructed.  This patches the instance's entry-filter attributes directly
    so every ``analyze_market()`` call uses scalp thresholds without any
    further intervention.

``bot/trading_strategy.py``
    In the scan loop: call ``hf.can_enter(symbol)`` before executing an entry
    and ``hf.record_trade(symbol)`` immediately after.
"""

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

logger = logging.getLogger("nija.hf_scalping_mode")

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


def _env_float_alias(preferred: str, legacy: str, default: float) -> float:
    """Read *preferred* env var first; fall back to *legacy*, then *default*."""
    v = os.environ.get(preferred)
    if v is not None:
        try:
            return float(v)
        except (ValueError, TypeError):
            pass
    return _env_float(legacy, default)


def _env_int_alias(preferred: str, legacy: str, default: int) -> int:
    """Read *preferred* env var first; fall back to *legacy*, then *default*."""
    v = os.environ.get(preferred)
    if v is not None:
        try:
            return int(v)
        except (ValueError, TypeError):
            pass
    return _env_int(legacy, default)


def _env_volume_threshold() -> float:
    """Read HF_MIN_VOLUME_PCT (percentage) or HF_SCALP_VOLUME_THRESHOLD (fraction).

    ``HF_MIN_VOLUME_PCT=0.45`` means 0.45 %; the stored fraction is 0.0045.
    The legacy ``HF_SCALP_VOLUME_THRESHOLD`` is already in fractional form.
    Growth config default: 0.0045 (0.45 %).
    """
    pct = os.environ.get("HF_MIN_VOLUME_PCT")
    if pct is not None:
        try:
            return float(pct) / 100.0
        except (ValueError, TypeError):
            pass
    return _env_float("HF_SCALP_VOLUME_THRESHOLD", 0.0045)


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "")
    if raw.lower() in ("1", "true", "yes", "on"):
        return True
    if raw.lower() in ("0", "false", "no", "off"):
        return False
    return default


def _env_stop_loss_pct() -> float:
    """Read stop-loss as a fraction, accepting legacy percent-style values."""
    value = _env_float_alias("HF_STOP_LOSS_PCT", "HF_SCALP_STOP_LOSS_PCT", 0.0035)
    if value > 0.05:
        return value / 100.0
    return value


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class HFScalpConfig:
    """
    All tunable parameters for the HF scalping mode.

    Every field can be overridden at startup via a matching environment variable
    (shown in the comment next to each field).  Phase 1 short-form names take
    priority; legacy ``HF_SCALP_*`` names are honoured as fallback for
    backward compatibility.

    Growth config defaults (lower thresholds = more trade frequency):

        MIN_CONFIDENCE    0.15   (HF_MIN_CONFIDENCE or HF_SCALP_MIN_CONFIDENCE)
        min_adx           3      (HF_MIN_ADX or HF_SCALP_MIN_ADX)
        volume_threshold  0.0045 (HF_MIN_VOLUME_PCT=0.45 or HF_SCALP_VOLUME_THRESHOLD)
        TAKE_PROFIT       1.2 %  (HF_TAKE_PROFIT_PCT or HF_SCALP_PROFIT_TARGET_PCT)
        STOP_LOSS         0.35 % (HF_STOP_LOSS_PCT or HF_SCALP_STOP_LOSS_PCT)
        MAX_TRADES/HR     20     (HF_MAX_TRADES_PER_HOUR or HF_SCALP_MAX_TRADES_PER_HOUR)
        SCAN_INTERVAL     60 s
    """

    # ── Master switch ──────────────────────────────────────────────────────────
    enabled: bool = field(default_factory=lambda: _env_bool("HF_SCALP_MODE", True))
    # env: HF_SCALP_MODE (1/true/yes to enable; default True)

    # ── Timing ────────────────────────────────────────────────────────────────
    cycle_interval_seconds: int = field(
        default_factory=lambda: _env_int("HF_SCALP_CYCLE_SECONDS", 60)
    )
    # env: HF_SCALP_CYCLE_SECONDS  (default 60 s vs normal 150 s)

    candle_cache_ttl: int = field(
        default_factory=lambda: _env_int("HF_SCALP_CACHE_TTL", 25)
    )
    # env: HF_SCALP_CACHE_TTL  (25 s to fit inside 60-s cycle)

    max_hold_seconds: int = field(
        default_factory=lambda: _env_int("HF_SCALP_MAX_HOLD_SECONDS", 180)
    )
    # env: HF_SCALP_MAX_HOLD_SECONDS  (default 3 minutes)

    # ── Entry quality gate — GUARANTEE trades start ───────────────────────────
    min_confidence: float = field(
        default_factory=lambda: _env_float_alias(
            "HF_MIN_CONFIDENCE", "HF_SCALP_MIN_CONFIDENCE", 0.15
        )
    )
    # env: HF_MIN_CONFIDENCE (preferred) or HF_SCALP_MIN_CONFIDENCE (legacy)

    kraken_min_confidence: float = field(
        default_factory=lambda: _env_float("HF_SCALP_KRAKEN_MIN_CONFIDENCE", 0.15)
    )
    # env: HF_SCALP_KRAKEN_MIN_CONFIDENCE

    min_adx: int = field(
        default_factory=lambda: _env_int_alias(
            "HF_MIN_ADX", "HF_SCALP_MIN_ADX", 3
        )
    )
    # env: HF_MIN_ADX (preferred) or HF_SCALP_MIN_ADX (legacy)

    volume_threshold: float = field(
        default_factory=_env_volume_threshold
    )
    # env: HF_MIN_VOLUME_PCT in % (Phase 1 preferred, e.g. 0.6 = 0.6 %)
    #      or HF_SCALP_VOLUME_THRESHOLD in fraction (legacy, e.g. 0.006)

    volume_min_threshold: float = field(
        default_factory=lambda: _env_float("HF_SCALP_VOLUME_MIN_THRESHOLD", 0.002)
    )
    # env: HF_SCALP_VOLUME_MIN_THRESHOLD

    min_trend_confirmation: int = field(
        default_factory=lambda: _env_int("HF_SCALP_MIN_TREND_CONF", 2)
    )
    # env: HF_SCALP_MIN_TREND_CONF

    min_entry_score: float = field(
        default_factory=lambda: _env_float("HF_SCALP_MIN_SCORE", 3.0)
    )
    # env: HF_SCALP_MIN_SCORE

    # ── Profit / stop management ───────────────────────────────────────────────
    profit_target_pct: float = field(
        default_factory=lambda: _env_float_alias(
            "HF_TAKE_PROFIT_PCT", "HF_SCALP_PROFIT_TARGET_PCT", 1.2
        )
    )
    # env: HF_TAKE_PROFIT_PCT (preferred) or HF_SCALP_PROFIT_TARGET_PCT (legacy)

    stop_loss_pct: float = field(
        default_factory=_env_stop_loss_pct
    )
    # env: HF_STOP_LOSS_PCT (Phase 1 preferred) or HF_SCALP_STOP_LOSS_PCT (legacy)

    # ── Rate limiting ─────────────────────────────────────────────────────────
    max_trades_per_hour: int = field(
        default_factory=lambda: _env_int_alias(
            "HF_MAX_TRADES_PER_HOUR", "HF_SCALP_MAX_TRADES_PER_HOUR", 20
        )
    )
    # env: HF_MAX_TRADES_PER_HOUR (preferred) or HF_SCALP_MAX_TRADES_PER_HOUR (legacy)

    trade_cooldown_seconds: float = field(
        default_factory=lambda: _env_float("HF_SCALP_COOLDOWN_SECONDS", 30.0)
    )
    # env: HF_SCALP_COOLDOWN_SECONDS  (min gap between consecutive entries)


# ──────────────────────────────────────────────────────────────────────────────
# Core class
# ──────────────────────────────────────────────────────────────────────────────

class HFScalpingMode:
    """
    High-frequency micro scalping mode controller.

    Singleton — obtain via ``get_hf_scalping_mode()``.
    """

    def __init__(self, config: Optional[HFScalpConfig] = None) -> None:
        self.config = config or HFScalpConfig()
        self._apply_live_safety_floor()
        # Timestamps of recent trades for per-hour rate limiting
        self._trade_timestamps: Deque[float] = deque()
        self._last_trade_ts: float = 0.0

        if self.config.enabled:
            logger.info(
                "🚀 HF Scalping Mode ACTIVE — "
                f"cycle={self.config.cycle_interval_seconds}s  "
                f"confidence≥{self.config.min_confidence:.2f}  "
                f"ADX≥{self.config.min_adx}  "
                f"vol≥{self.config.volume_threshold * 100:.1f}%  "
                f"TP={self.config.profit_target_pct:.1f}%  "
                f"SL={self.config.stop_loss_pct * 100:.2f}%  "
                f"max={self.config.max_trades_per_hour} trades/hr"
            )
            _live_mode = _env_bool("LIVE_CAPITAL_VERIFIED", False) and not _env_bool("DRY_RUN_MODE", False)
            logger.info(
                "HF effective gates — "
                f"min_conf={self.config.min_confidence:.2f} "
                f"vol={self.config.volume_threshold * 100:.1f}%"
            )
        else:
            logger.info("ℹ️  HF Scalping Mode INACTIVE (set HF_SCALP_MODE=1 to enable)")

    def _apply_live_safety_floor(self) -> None:
        """Clamp overly aggressive HF settings to protect against bad env vars.

        This protects all deployments where environment variables may carry
        values that would cause trades to be rejected by the execution engine's
        target_geometry_gate (minimum tp_pct=0.800%).  Operators can disable
        this clamp explicitly via ``HF_SCALP_ENFORCE_SAFETY_FLOOR=false``.
        """
        if not self.config.enabled:
            return

        enforce_floor = _env_bool("HF_SCALP_ENFORCE_SAFETY_FLOOR", True)
        if not enforce_floor:
            return

        # Growth config baselines — lower thresholds for more trade frequency
        # while keeping capital-protection systems intact.
        # profit_target_pct floor is 1.0 (= 1.0% after /100 in the strategy),
        # which safely clears the execution engine's MIN_TP_PCT of 0.800%.
        floors = {
            "cycle_interval_seconds": 60,
            "kraken_min_confidence": 0.15,
            "volume_min_threshold": 0.002,
            "min_trend_confirmation": 2,
            "min_entry_score": 3.0,
            "profit_target_pct": 1.0,
            "max_trades_per_hour": 20,
            "trade_cooldown_seconds": 30.0,
        }

        # Optional hard profile lock for operator-requested settings.
        # Disabled by default — env vars and growth config take precedence.
        # Set HF_SCALP_LOCK_PROFILE=true only to pin thresholds explicitly.
        lock_profile = _env_bool("HF_SCALP_LOCK_PROFILE", False)
        if lock_profile:
            self.config.min_confidence = 0.15
            self.config.kraken_min_confidence = 0.15
            self.config.min_adx = 3
            self.config.volume_threshold = 0.0045
            self.config.profit_target_pct = 1.2
            self.config.stop_loss_pct = 0.0035
            # Growth config band: 10–20 trades/hr
            if self.config.max_trades_per_hour < 10:
                self.config.max_trades_per_hour = 10
            elif self.config.max_trades_per_hour > 20:
                self.config.max_trades_per_hour = 20
            logger.info(
                "HF profile lock active — "
                f"conf={self.config.min_confidence:.2f} "
                f"adx={self.config.min_adx} "
                f"vol={self.config.volume_threshold * 100:.2f}% "
                f"tp={self.config.profit_target_pct:.1f}% "
                f"sl={self.config.stop_loss_pct * 100:.2f}%"
            )

        # Lower cap for trade frequency, lower bound for all other fields.
        clamped = []
        if self.config.max_trades_per_hour > floors["max_trades_per_hour"]:
            clamped.append(("max_trades_per_hour", self.config.max_trades_per_hour, floors["max_trades_per_hour"]))
            self.config.max_trades_per_hour = floors["max_trades_per_hour"]

        for key, floor in floors.items():
            if key == "max_trades_per_hour":
                continue
            current = getattr(self.config, key)
            if current < floor:
                clamped.append((key, current, floor))
                setattr(self.config, key, floor)

        if clamped:
            logger.warning("HF live safety floor enforced (%d adjustments)", len(clamped))
            for key, old, new in clamped:
                logger.warning("  • %s: %s -> %s", key, old, new)

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    # ── Apex integration ───────────────────────────────────────────────────────

    def apply_to_apex(self, apex_instance) -> None:
        """
        Patch a ``NIJAApexStrategyV71`` instance to use scalp thresholds.

        This must be called once, immediately after the apex strategy is
        constructed in ``TradingStrategy.__init__()``.

        Attributes patched on the apex instance
        ----------------------------------------
        _hf_scalp_active        bool  — sentinel read by analyze_market()
        _hf_min_confidence      float — overrides module-level MIN_CONFIDENCE
        _hf_stop_pct            float — stop-loss fraction  (e.g. 0.0035)
        _hf_tp_pct              float — take-profit % (e.g. 0.5)
        min_adx                 int   — overrides self.min_adx (was 15 → 8)
        volume_threshold        float — overrides self.volume_threshold
        volume_min_threshold    float — overrides self.volume_min_threshold
        min_trend_confirmation  int   — overrides self.min_trend_confirmation
        kraken_min_confidence   float — overrides self.kraken_min_confidence
        """
        if apex_instance is None:
            return
        if not self.config.enabled:
            return

        apex_instance._hf_scalp_active       = True
        apex_instance._hf_min_confidence     = self.config.min_confidence
        apex_instance._hf_stop_pct           = self.config.stop_loss_pct
        apex_instance._hf_tp_pct             = self.config.profit_target_pct
        apex_instance.min_adx                = self.config.min_adx
        apex_instance.volume_threshold       = self.config.volume_threshold
        apex_instance.volume_min_threshold   = self.config.volume_min_threshold
        apex_instance.min_trend_confirmation = self.config.min_trend_confirmation
        apex_instance.kraken_min_confidence  = self.config.kraken_min_confidence

        logger.info(
            "✅ HF Scalp applied to APEX — "
            f"confidence≥{self.config.min_confidence:.2f}  "
            f"ADX≥{self.config.min_adx}  "
            f"vol≥{self.config.volume_threshold * 100:.1f}%  "
            f"trend_conf={self.config.min_trend_confirmation}/5  "
            f"TP={self.config.profit_target_pct:.1f}%  "
            f"SL={self.config.stop_loss_pct * 100:.2f}%"
        )

    # ── Cycle timing ───────────────────────────────────────────────────────────

    def get_cycle_interval(self) -> int:
        """Return the inter-cycle sleep in seconds (60 when active, 150 otherwise)."""
        return self.config.cycle_interval_seconds if self.config.enabled else 150

    def get_candle_cache_ttl(self) -> int:
        """Return candle cache TTL appropriate for the active mode."""
        return self.config.candle_cache_ttl if self.config.enabled else 150

    # ── Rate limiting ──────────────────────────────────────────────────────────

    def can_enter(self, symbol: str) -> tuple:
        """
        Check whether a new scalp entry is permitted.

        Returns ``(allowed: bool, reason: str)``.
        Always returns ``(True, …)`` when HF scalp mode is inactive.
        """
        if not self.config.enabled:
            return True, "HF scalp mode inactive"

        now = time.monotonic()

        # Per-entry cooldown
        elapsed = now - self._last_trade_ts
        if elapsed < self.config.trade_cooldown_seconds:
            wait = self.config.trade_cooldown_seconds - elapsed
            return (
                False,
                f"HF scalp cooldown: {wait:.1f}s remaining "
                f"(min gap {self.config.trade_cooldown_seconds:.0f}s)",
            )

        # Per-hour cap
        one_hour_ago = now - 3600.0
        while self._trade_timestamps and self._trade_timestamps[0] < one_hour_ago:
            self._trade_timestamps.popleft()
        if len(self._trade_timestamps) >= self.config.max_trades_per_hour:
            return (
                False,
                f"HF scalp rate limit: "
                f"{len(self._trade_timestamps)}/{self.config.max_trades_per_hour} trades/hr",
            )

        return True, "ok"

    def record_trade(self, symbol: str) -> None:
        """Call this immediately after a scalp entry is successfully executed."""
        if not self.config.enabled:
            return
        now = time.monotonic()
        self._trade_timestamps.append(now)
        self._last_trade_ts = now
        logger.debug(
            "⚡ HF scalp entry recorded — %s  (trades this hour: %d)",
            symbol, len(self._trade_timestamps),
        )

    # ── Hold-time enforcement ──────────────────────────────────────────────────

    def should_force_exit(self, symbol: str, entry_time: float) -> tuple:
        """
        Return ``(True, reason)`` when the scalp max-hold time has elapsed.

        Parameters
        ----------
        entry_time : float
            The ``time.time()`` value recorded at position open.
        """
        if not self.config.enabled:
            return False, ""
        elapsed = time.time() - entry_time
        if elapsed >= self.config.max_hold_seconds:
            return (
                True,
                f"[HF-SCALP] Max hold {self.config.max_hold_seconds}s reached "
                f"({elapsed:.0f}s elapsed)",
            )
        return False, ""

    # ── Status ─────────────────────────────────────────────────────────────────

    def status_dict(self) -> Dict:
        """Return a JSON-serialisable status snapshot for dashboards."""
        now = time.monotonic()
        one_hour_ago = now - 3600.0
        while self._trade_timestamps and self._trade_timestamps[0] < one_hour_ago:
            self._trade_timestamps.popleft()
        return {
            "enabled": self.config.enabled,
            "cycle_interval_seconds": self.config.cycle_interval_seconds,
            "candle_cache_ttl": self.config.candle_cache_ttl,
            "min_confidence": self.config.min_confidence,
            "min_adx": self.config.min_adx,
            "volume_threshold": self.config.volume_threshold,
            "volume_min_threshold": self.config.volume_min_threshold,
            "min_trend_confirmation": self.config.min_trend_confirmation,
            "profit_target_pct": self.config.profit_target_pct,
            "stop_loss_pct": self.config.stop_loss_pct,
            "max_hold_seconds": self.config.max_hold_seconds,
            "max_trades_per_hour": self.config.max_trades_per_hour,
            "trades_this_hour": len(self._trade_timestamps),
            "trade_cooldown_seconds": self.config.trade_cooldown_seconds,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Singleton factory
# ──────────────────────────────────────────────────────────────────────────────

_hf_scalping_instance: Optional[HFScalpingMode] = None


def get_hf_scalping_mode(config: Optional[HFScalpConfig] = None) -> HFScalpingMode:
    """Return the singleton ``HFScalpingMode`` instance.

    Supply *config* only on the very first call to override defaults; it is
    ignored on subsequent calls.
    """
    global _hf_scalping_instance
    if _hf_scalping_instance is None:
        _hf_scalping_instance = HFScalpingMode(config)
    return _hf_scalping_instance
