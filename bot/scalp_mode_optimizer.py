"""
NIJA Scalp Mode Optimizer
==========================

Industry Principle #5: Scalping & high-frequency micro trades
--------------------------------------------------------------
AI bots that focus on micro-scalping strategies — capturing small price
inefficiencies repeatedly — often outperform long-term swing logic on
small capital because:

    ✔ More frequent opportunities
    ✔ Compounding small gains rapidly
    ✔ Short holding periods; not exposed to slow-moving macro trends
    ✔ Requires tight execution and low-fee routing

This module provides a curated parameter set specifically optimised for
high-frequency scalping in high-liquidity markets.  It is activated when
the detected regime is CONSOLIDATION, RANGING, or otherwise low-ATR, and
complements the ``RegimeStrategyBridge`` by adding:

    1. Preferred high-liquidity pairs for tight-spread execution
    2. Micro profit-target ladder (0.5% – 1.5% per exit)
    3. Tight trailing stop (0.4 – 0.8% ATR)
    4. Maximum concurrent scalp positions (separate from swing book)
    5. Fee-aware minimum gross profit calculation per exchange
    6. Scalp-specific entry score relaxation

Integration
-----------
Import the singleton via ``get_scalp_mode_optimizer()`` and call
``get_scalp_config(broker, account_balance)`` to receive a ``ScalpConfig``
dataclass.  The APEX strategy checks ``should_use_scalp_mode(regime)``
before each entry decision.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.scalp_mode_optimizer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# High-liquidity pair universe
# ---------------------------------------------------------------------------

# These pairs have the tightest spreads and deepest order books on Coinbase,
# making them the best candidates for scalping.  Sorted by liquidity tier.
_TIER_1_LIQUID_PAIRS: List[str] = [
    "BTC-USD",  "ETH-USD",  "SOL-USD",  "XLM-USD",  "LINK-USD",
    "AVAX-USD", "MATIC-USD", "ADA-USD", "DOT-USD",  "LTC-USD",
]

_TIER_2_LIQUID_PAIRS: List[str] = [
    "ATOM-USD", "ALGO-USD", "FTM-USD",  "NEAR-USD", "SAND-USD",
    "MANA-USD", "UNI-USD",  "AAVE-USD", "CRV-USD",  "COMP-USD",
    "1INCH-USD","GRT-USD",  "ENJ-USD",  "CHZ-USD",  "AXS-USD",
]

# Pairs that historically have poor execution quality or high spreads for scalps
_SCALP_EXCLUDED_PAIRS: List[str] = [
    "XRP-USD", "XRP-USDT", "XRPUSD",  # often restricted / poor liquidity
]


# ---------------------------------------------------------------------------
# Scalp config dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScalpConfig:
    """
    Fully-resolved scalp configuration for a broker + account size.

    Each field represents a recommendation, not a hard constraint; the
    trading strategy may choose to deviate within safe bounds.
    """

    # ── Strategy identity ─────────────────────────────────────────────────
    mode_active: bool      = True
    broker: str            = "coinbase"
    description: str       = ""

    # ── Preferred universe ────────────────────────────────────────────────
    preferred_pairs: List[str] = field(default_factory=list)
    excluded_pairs:  List[str] = field(default_factory=lambda: list(_SCALP_EXCLUDED_PAIRS))

    # ── Entry parameters ──────────────────────────────────────────────────
    rsi_long_min: float    = 30.0
    rsi_long_max: float    = 52.0
    rsi_short_min: float   = 48.0
    rsi_short_max: float   = 70.0
    min_entry_score: int   = 2       # lower bar — volume compensates
    confidence_gate: float = 0.40    # looser confidence for scalps

    # ── Position sizing ───────────────────────────────────────────────────
    position_size_usd: float   = 0.0   # set dynamically from balance
    max_concurrent_scalps: int = 5
    max_position_pct: float    = 0.08  # 8% of balance per scalp

    # ── Profit targets (gross %) ──────────────────────────────────────────
    tp_levels: List[Tuple[float, float]] = field(default_factory=list)
    # Each entry: (gross_profit_pct, exit_fraction)
    # e.g. (0.008, 0.30) = exit 30% of position at +0.8% gross profit

    # ── Stop-loss ─────────────────────────────────────────────────────────
    stop_loss_pct: float       = 0.008    # 0.8% hard stop
    stop_loss_atr_mult: float  = 0.8      # ATR-based alternative
    trailing_stop_pct: float   = 0.005    # 0.5% trailing
    trailing_stop_atr_mult: float = 0.6   # ATR-based alternative

    # ── Fee-aware minimum gross profit ────────────────────────────────────
    min_gross_profit_pct: float = 0.025   # must exceed this for net profit

    # ── Frequency ─────────────────────────────────────────────────────────
    target_trades_per_hour: float = 4.0
    max_hold_minutes: int         = 45     # time-based exit if stuck

    # ── Circuit breaker ───────────────────────────────────────────────────
    max_consecutive_losses: int   = 3
    circuit_breaker_pause_mins: int = 10


# ---------------------------------------------------------------------------
# Optimizer class
# ---------------------------------------------------------------------------

class ScalpModeOptimizer:
    """
    Generates exchange-aware, balance-aware scalp configurations.

    The fee structure of each exchange directly determines how tight the
    minimum gross-profit threshold must be:
        Coinbase  1.4% round-trip → min scalp target ≥ 2.0% gross
        Kraken    0.36% round-trip → min scalp target ≥ 0.5% gross
        Binance   0.28% round-trip → min scalp target ≥ 0.4% gross

    Smaller accounts use smaller position sizes to stay fee-efficient.
    """

    # Fee tiers (broker_name_fragment → round_trip_fee)
    _BROKER_FEES: Dict[str, float] = {
        "coinbase": 0.014,  # 1.4%
        "kraken":   0.0036, # 0.36%
        "binance":  0.0028, # 0.28%
        "okx":      0.003,  # 0.30%
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        logger.info(
            "⚡ ScalpModeOptimizer initialized — "
            "T1 pairs=%d, T2 pairs=%d",
            len(_TIER_1_LIQUID_PAIRS),
            len(_TIER_2_LIQUID_PAIRS),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_scalp_config(
        self,
        broker: str = "coinbase",
        account_balance: float = 100.0,
    ) -> ScalpConfig:
        """
        Return a fully-resolved ``ScalpConfig`` for the given broker
        and account balance.

        Args:
            broker: Exchange name (case-insensitive substring match).
            account_balance: Current usable balance in USD.

        Returns:
            ``ScalpConfig`` with all fields populated.
        """
        broker_key = self._match_broker(broker)
        rt_fee = self._BROKER_FEES.get(broker_key, 0.014)  # default Coinbase

        # ── Minimum gross profit (fee × safety_multiplier) ─────────────────
        # Safety multiplier of 2.5× ensures NET profit after fees
        min_gross = round(rt_fee * 2.5, 4)

        # ── Profit-target ladder ────────────────────────────────────────────
        tp_levels = self._build_tp_ladder(rt_fee, broker_key)

        # ── Position sizing ─────────────────────────────────────────────────
        max_pos_pct = 0.08
        pos_usd = max(5.0, account_balance * max_pos_pct)

        # ── Concurrent scalps ───────────────────────────────────────────────
        if account_balance >= 1000:
            max_concurrent = 8
        elif account_balance >= 500:
            max_concurrent = 6
        elif account_balance >= 200:
            max_concurrent = 4
        else:
            max_concurrent = 3

        # ── Preferred pairs ─────────────────────────────────────────────────
        preferred = list(_TIER_1_LIQUID_PAIRS)
        if account_balance >= 100:
            preferred += _TIER_2_LIQUID_PAIRS

        # ── Stop / trailing ─────────────────────────────────────────────────
        # For Coinbase (high fee), stop must be wider to prevent stop-hunts
        # before profit target is reached.  For low-fee brokers, tighter.
        if rt_fee >= 0.010:
            sl_pct = 0.012        # 1.2% for Coinbase
            trailing_pct = 0.008  # 0.8% trailing
            sl_atr = 1.0
            trail_atr = 0.8
        else:
            sl_pct = 0.006        # 0.6% for Kraken/Binance
            trailing_pct = 0.004  # 0.4% trailing
            sl_atr = 0.7
            trail_atr = 0.5

        cfg = ScalpConfig(
            mode_active=True,
            broker=broker_key,
            description=(
                f"ScalpMode ({broker_key}) | fee={rt_fee*100:.2f}% | "
                f"min_gross={min_gross*100:.2f}% | "
                f"max_pos=${pos_usd:.0f} | {max_concurrent} concurrent"
            ),
            preferred_pairs=preferred,
            excluded_pairs=list(_SCALP_EXCLUDED_PAIRS),
            rsi_long_min=28.0,
            rsi_long_max=52.0,
            rsi_short_min=48.0,
            rsi_short_max=72.0,
            min_entry_score=2,
            confidence_gate=0.40,
            position_size_usd=pos_usd,
            max_concurrent_scalps=max_concurrent,
            max_position_pct=max_pos_pct,
            tp_levels=tp_levels,
            stop_loss_pct=sl_pct,
            stop_loss_atr_mult=sl_atr,
            trailing_stop_pct=trailing_pct,
            trailing_stop_atr_mult=trail_atr,
            min_gross_profit_pct=min_gross,
            target_trades_per_hour=4.0,
            max_hold_minutes=45,
            max_consecutive_losses=3,
            circuit_breaker_pause_mins=10,
        )

        logger.info("⚡ ScalpConfig: %s", cfg.description)
        return cfg

    @staticmethod
    def should_use_scalp_mode(regime: object) -> bool:
        """
        Return True when the detected regime is suited to scalping.

        Scalping is most effective in:
            • CONSOLIDATION (low ATR, compressed price action)
            • RANGING (clear top/bottom to bounce between)
            • WEAK_TREND (gentle drift, not strong enough for swing)
        """
        regime_str = ""
        if hasattr(regime, "value"):
            regime_str = str(regime.value).lower()
        else:
            regime_str = str(regime).lower()

        scalp_regimes = {"consolidation", "ranging", "weak_trend"}
        return regime_str in scalp_regimes

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_broker(broker: str) -> str:
        """Normalise broker name to a known key."""
        b = broker.lower()
        if "coinbase" in b or "cb" in b:
            return "coinbase"
        if "kraken" in b:
            return "kraken"
        if "binance" in b:
            return "binance"
        if "okx" in b:
            return "okx"
        return "coinbase"  # safe default

    @staticmethod
    def _build_tp_ladder(
        round_trip_fee: float, broker_key: str
    ) -> List[Tuple[float, float]]:
        """
        Build the micro profit-target ladder for a scalp.

        Each entry is (gross_profit_pct, exit_fraction).
        The ladder is fee-aware: first exit is only placed when gross
        profit reliably exceeds round-trip fees.

        Coinbase (1.4% fees):
          TP1: 2.0% gross → ~0.6% NET — exit 30%
          TP2: 2.5% gross → ~1.1% NET — exit 30%
          TP3: 3.5% gross → ~2.1% NET — exit 25%
          TP4: 5.0% gross → ~3.6% NET — exit 15% (runner)

        Kraken/Binance/OKX (≤0.5% fees):
          TP1: 0.6% gross → ~0.24% NET — exit 30%
          TP2: 1.0% gross → ~0.64% NET — exit 30%
          TP3: 1.5% gross → ~1.14% NET — exit 25%
          TP4: 2.5% gross → ~2.14% NET — exit 15% (runner)
        """
        if round_trip_fee >= 0.010:  # Coinbase
            return [
                (0.020, 0.30),  # 30% at 2.0%
                (0.025, 0.30),  # 30% at 2.5%
                (0.035, 0.25),  # 25% at 3.5%
                (0.050, 0.15),  # 15% runner at 5.0%
            ]
        else:  # Low-fee brokers
            return [
                (0.006, 0.30),  # 30% at 0.6%
                (0.010, 0.30),  # 30% at 1.0%
                (0.015, 0.25),  # 25% at 1.5%
                (0.025, 0.15),  # 15% runner at 2.5%
            ]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_optimizer_instance: Optional[ScalpModeOptimizer] = None
_optimizer_lock = threading.Lock()


def get_scalp_mode_optimizer() -> ScalpModeOptimizer:
    """Return the module-level singleton ``ScalpModeOptimizer``."""
    global _optimizer_instance
    if _optimizer_instance is None:
        with _optimizer_lock:
            if _optimizer_instance is None:
                _optimizer_instance = ScalpModeOptimizer()
    return _optimizer_instance


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    opt = get_scalp_mode_optimizer()

    for broker, balance in [("coinbase", 250), ("kraken", 250), ("binance", 1000)]:
        cfg = opt.get_scalp_config(broker, balance)
        print(f"\n{'='*70}")
        print(f"BROKER: {broker.upper()} | BALANCE: ${balance}")
        print(f"  {cfg.description}")
        print(f"  RSI long:   {cfg.rsi_long_min:.0f} – {cfg.rsi_long_max:.0f}")
        print(f"  RSI short:  {cfg.rsi_short_min:.0f} – {cfg.rsi_short_max:.0f}")
        print(f"  Min gross:  {cfg.min_gross_profit_pct*100:.2f}%")
        print(f"  Stop:       {cfg.stop_loss_pct*100:.2f}%  "
              f"Trailing: {cfg.trailing_stop_pct*100:.2f}%")
        print(f"  TP ladder:")
        for gross, frac in cfg.tp_levels:
            print(f"    {gross*100:.1f}% gross | exit {frac*100:.0f}%")
        print(f"  Concurrent: {cfg.max_concurrent_scalps} | "
              f"Target: {cfg.target_trades_per_hour:.0f}/hr")

    # Test regime detection
    print(f"\n{'='*70}")
    for r in ["consolidation", "ranging", "strong_trend", "volatile"]:
        print(f"  should_use_scalp_mode({r!r}) = "
              f"{ScalpModeOptimizer.should_use_scalp_mode(r)}")
