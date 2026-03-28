"""
NIJA Risk-Per-Trade Position Sizer
=====================================

Industry Principle #3: Position sizing grounded in RISK, not balance alone
---------------------------------------------------------------------------
Expert consensus is clear: "risk per trade" rules beat naïve balance-percentage
sizing.  A correct risk-based formula:

    position_size_usd = (account_balance × risk_pct) / stop_loss_pct

Example:
    account_balance = $1 000
    risk_pct        = 1.5%   ($15 at risk)
    stop_loss_pct   = 2.0%   (2% from entry to stop)
    → position_size = $15 / 0.02 = $750

This ensures that regardless of asset volatility:
  • A tight stop (0.5%) → large position ($3 000 on $1k account) — but capped
  • A wide stop (3.0%)  → small position ($500 on $1k account)
  • Every trade risks the same dollar amount

ATR-based stop sizing variant:
    stop_loss_pct = (ATR × atr_multiplier) / entry_price
    position_size = (account_balance × risk_pct) / stop_loss_pct

Features
--------
- Fixed-fractional risk model (1-2% per trade default)
- ATR-based dynamic stop-loss distance (more accurate than fixed %)
- Position clamped between min/max bounds
- Regime-aware risk_pct adjustment (higher in trends, lower in chop)
- Singleton via ``get_risk_per_trade_sizer()``

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger("nija.risk_per_trade_sizer")


# ---------------------------------------------------------------------------
# Configuration defaults (overridable via env vars)
# ---------------------------------------------------------------------------

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


# Default risk per trade as % of account balance (1.5% = $15 risk on $1k account)
_DEFAULT_RISK_PCT = _env_float("RISK_PER_TRADE_PCT", 1.5) / 100.0

# Hard bounds to prevent catastrophically large / tiny positions
_DEFAULT_MIN_POSITION_USD = _env_float("MIN_POSITION_USD", 5.0)
_DEFAULT_MAX_POSITION_PCT = _env_float("MAX_POSITION_PCT", 0.15)  # 15% of account max

# ATR multiplier used when computing dynamic stop-loss distance
_DEFAULT_ATR_MULTIPLIER = _env_float("RISK_SIZER_ATR_MULTIPLIER", 1.5)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RiskSizingResult:
    """Full breakdown of a risk-based position-size calculation."""

    # Core output
    position_size_usd: float        # Final position size in USD
    stop_loss_price: float          # Suggested stop-loss price
    stop_loss_pct: float            # Stop distance as fraction of entry

    # Risk accounting
    dollar_risk: float              # Exact dollars at risk ($)
    risk_pct_used: float            # Risk fraction actually applied
    account_balance: float

    # Clamping metadata
    was_clamped: bool               # True if min/max bounds were applied
    clamp_reason: str               # e.g. "min_position", "max_position_pct"

    # Sizing inputs
    entry_price: float
    atr_value: Optional[float]
    stop_method: str                # "atr_based" | "fixed_pct" | "supplied"

    # Risk:Reward
    take_profit_price: Optional[float]
    risk_reward_ratio: Optional[float]


# ---------------------------------------------------------------------------
# Sizer class
# ---------------------------------------------------------------------------

class RiskPerTradeSizer:
    """
    Computes position size based on a fixed fraction of account equity
    at risk per trade — using either ATR-based or fixed-% stop distances.

    Thread-safe (stateless computation).
    """

    def __init__(
        self,
        risk_pct: Optional[float] = None,
        min_position_usd: Optional[float] = None,
        max_position_pct: Optional[float] = None,
        atr_multiplier: Optional[float] = None,
    ) -> None:
        self._risk_pct         = risk_pct         or _DEFAULT_RISK_PCT
        self._min_position_usd = min_position_usd or _DEFAULT_MIN_POSITION_USD
        self._max_position_pct = max_position_pct or _DEFAULT_MAX_POSITION_PCT
        self._atr_multiplier   = atr_multiplier   or _DEFAULT_ATR_MULTIPLIER

        logger.info(
            "💰 RiskPerTradeSizer initialized — "
            "risk=%.1f%% | min=$%.2f | max=%.0f%% | ATR×%.1f",
            self._risk_pct * 100,
            self._min_position_usd,
            self._max_position_pct * 100,
            self._atr_multiplier,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        account_balance: float,
        entry_price: float,
        *,
        # --- Stop-loss specification (mutually exclusive; ATR preferred) ---
        atr_value: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,     # e.g. 0.015 = 1.5%
        stop_loss_price: Optional[float] = None,   # absolute price
        # --- Risk override (e.g. from regime bridge) ---
        risk_pct_override: Optional[float] = None,
        atr_multiplier_override: Optional[float] = None,
        # --- Optional take-profit for R:R calculation ---
        take_profit_price: Optional[float] = None,
        # --- Trade direction ---
        side: str = "long",
    ) -> RiskSizingResult:
        """
        Calculate the risk-adjusted position size.

        Priority for stop determination:
            1. ``atr_value`` — dynamic ATR-based stop (best)
            2. ``stop_loss_price`` — supplied absolute price
            3. ``stop_loss_pct`` — supplied percentage
            4. Fallback: use ``_DEFAULT_ATR_MULTIPLIER × 0.02`` (2% ATR proxy)

        Args:
            account_balance: Current usable account balance in USD.
            entry_price: Proposed entry price.
            atr_value: Most recent ATR value in price units.
            stop_loss_pct: Stop distance as a fraction (e.g. 0.015 = 1.5%).
            stop_loss_price: Absolute stop-loss price.
            risk_pct_override: Override the default risk fraction for this call.
            atr_multiplier_override: Override the ATR multiplier for this call.
            take_profit_price: Target price (used only for R:R display).
            side: "long" or "short".

        Returns:
            ``RiskSizingResult`` with position size and all intermediate values.
        """
        if account_balance <= 0 or entry_price <= 0:
            logger.warning(
                "⚠️  RiskPerTradeSizer: invalid inputs "
                "(balance=%.2f, entry=%.4f) — returning zero",
                account_balance, entry_price,
            )
            return self._zero_result(account_balance, entry_price)

        risk_pct = risk_pct_override if risk_pct_override is not None else self._risk_pct
        atr_mult = atr_multiplier_override if atr_multiplier_override is not None else self._atr_multiplier

        # ── 1. Determine stop-loss distance ───────────────────────────────
        computed_sl_price, sl_pct, stop_method = self._compute_stop(
            entry_price=entry_price,
            side=side,
            atr_value=atr_value,
            atr_mult=atr_mult,
            stop_loss_pct=stop_loss_pct,
            stop_loss_price=stop_loss_price,
        )

        # ── 2. Dollar-risk position sizing ────────────────────────────────
        dollar_risk = account_balance * risk_pct
        if sl_pct <= 0:
            sl_pct = 0.02  # emergency fallback: 2%

        raw_position_usd = dollar_risk / sl_pct

        # ── 3. Clamp to min/max bounds ────────────────────────────────────
        max_position_usd = account_balance * self._max_position_pct
        was_clamped = False
        clamp_reason = ""

        if raw_position_usd < self._min_position_usd:
            raw_position_usd = self._min_position_usd
            was_clamped = True
            clamp_reason = "min_position"
        elif raw_position_usd > max_position_usd:
            raw_position_usd = max_position_usd
            was_clamped = True
            clamp_reason = "max_position_pct"

        final_position_usd = raw_position_usd
        actual_dollar_risk = final_position_usd * sl_pct

        # ── 4. Risk:Reward ────────────────────────────────────────────────
        rr_ratio = None
        if take_profit_price is not None and entry_price > 0:
            reward = abs(take_profit_price - entry_price)
            risk   = abs(computed_sl_price - entry_price)
            rr_ratio = (reward / risk) if risk > 0 else None

        logger.debug(
            "💰 RiskSizer: balance=$%.2f | risk=%.1f%% | "
            "stop=%.2f%% (%s) | position=$%.2f%s | R:R=%s",
            account_balance,
            risk_pct * 100,
            sl_pct * 100,
            stop_method,
            final_position_usd,
            f" [CLAMPED:{clamp_reason}]" if was_clamped else "",
            f"1:{rr_ratio:.2f}" if rr_ratio else "n/a",
        )

        return RiskSizingResult(
            position_size_usd=final_position_usd,
            stop_loss_price=computed_sl_price,
            stop_loss_pct=sl_pct,
            dollar_risk=actual_dollar_risk,
            risk_pct_used=risk_pct,
            account_balance=account_balance,
            was_clamped=was_clamped,
            clamp_reason=clamp_reason,
            entry_price=entry_price,
            atr_value=atr_value,
            stop_method=stop_method,
            take_profit_price=take_profit_price,
            risk_reward_ratio=rr_ratio,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_stop(
        self,
        entry_price: float,
        side: str,
        atr_value: Optional[float],
        atr_mult: float,
        stop_loss_pct: Optional[float],
        stop_loss_price: Optional[float],
    ) -> Tuple[float, float, str]:
        """Return (stop_price, stop_pct_fraction, method_label)."""

        # Priority 1: ATR-based dynamic stop
        if atr_value is not None and atr_value > 0:
            stop_distance = atr_value * atr_mult
            if side == "long":
                sl_price = entry_price - stop_distance
            else:
                sl_price = entry_price + stop_distance
            sl_pct = stop_distance / entry_price
            return sl_price, sl_pct, "atr_based"

        # Priority 2: Supplied absolute stop price
        if stop_loss_price is not None and stop_loss_price > 0:
            sl_pct = abs(entry_price - stop_loss_price) / entry_price
            return stop_loss_price, sl_pct, "supplied_price"

        # Priority 3: Supplied percentage stop
        if stop_loss_pct is not None and stop_loss_pct > 0:
            if side == "long":
                sl_price = entry_price * (1.0 - stop_loss_pct)
            else:
                sl_price = entry_price * (1.0 + stop_loss_pct)
            return sl_price, stop_loss_pct, "fixed_pct"

        # Fallback: 2% stop
        fallback_pct = 0.02
        if side == "long":
            sl_price = entry_price * (1.0 - fallback_pct)
        else:
            sl_price = entry_price * (1.0 + fallback_pct)
        return sl_price, fallback_pct, "fallback_2pct"

    @staticmethod
    def _zero_result(balance: float, entry: float) -> RiskSizingResult:
        return RiskSizingResult(
            position_size_usd=0.0,
            stop_loss_price=0.0,
            stop_loss_pct=0.0,
            dollar_risk=0.0,
            risk_pct_used=0.0,
            account_balance=balance,
            was_clamped=False,
            clamp_reason="invalid_input",
            entry_price=entry,
            atr_value=None,
            stop_method="none",
            take_profit_price=None,
            risk_reward_ratio=None,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_sizer_instance: Optional[RiskPerTradeSizer] = None
_sizer_lock = threading.Lock()


def get_risk_per_trade_sizer(
    risk_pct: Optional[float] = None,
    min_position_usd: Optional[float] = None,
    max_position_pct: Optional[float] = None,
) -> RiskPerTradeSizer:
    """Return the module-level singleton ``RiskPerTradeSizer``."""
    global _sizer_instance
    if _sizer_instance is None:
        with _sizer_lock:
            if _sizer_instance is None:
                _sizer_instance = RiskPerTradeSizer(
                    risk_pct=risk_pct,
                    min_position_usd=min_position_usd,
                    max_position_pct=max_position_pct,
                )
    return _sizer_instance


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    sizer = get_risk_per_trade_sizer()

    scenarios = [
        # (balance, entry, atr, side, label)
        (1000, 100.0, 1.5,  "long",  "Normal: $1k, ATR 1.5%"),
        (1000, 100.0, 0.3,  "long",  "Tight ATR: $1k, ATR 0.3%"),
        (1000, 100.0, 5.0,  "long",  "Wide ATR: $1k, ATR 5%"),
        (200,  50.0,  0.75, "long",  "Small account: $200"),
        (5000, 2000.0, 30.0, "short", "BTC short: $5k balance"),
    ]

    print("\n" + "=" * 90)
    print("RISK-PER-TRADE SIZER — SCENARIOS")
    print("=" * 90)
    for balance, entry, atr, side, label in scenarios:
        r = sizer.calculate(balance, entry, atr_value=atr, side=side,
                            take_profit_price=entry * 1.025 if side == "long"
                            else entry * 0.975)
        print(
            f"\n{label}\n"
            f"  Position: ${r.position_size_usd:,.2f} | "
            f"Stop: ${r.stop_loss_price:.4f} ({r.stop_loss_pct*100:.2f}%) | "
            f"Dollar risk: ${r.dollar_risk:.2f} | "
            f"R:R = 1:{r.risk_reward_ratio:.2f}" if r.risk_reward_ratio else
            f"  Position: ${r.position_size_usd:,.2f} | Stop: ${r.stop_loss_price:.4f}"
        )
    print("\n" + "=" * 90)
