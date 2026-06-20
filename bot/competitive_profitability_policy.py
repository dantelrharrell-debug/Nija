"""Competitive profitability policy inspired by leading bot platform features.

The policy keeps public best-practice ideas local and deterministic:

* avoid illiquid symbols before fallback entries,
* size small exploratory entries instead of martingale-style averaging,
* derive take-profit and trailing-stop geometry from live ATR/participation,
* cap risk after poor realised outcomes.
"""

from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque

import pandas as pd


@dataclass(frozen=True)
class CompetitiveEntryProfile:
    risk_fraction: float
    stop_loss_pct: float
    trailing_stop_pct: float
    take_profit_pct: tuple[float, float, float]
    liquidity_ok: bool
    liquidity_reason: str


class CompetitiveProfitabilityPolicy:
    """Create risk-adjusted fallback-entry geometry from live market data."""

    def __init__(self) -> None:
        self._outcomes: Deque[float] = deque(maxlen=150)
        self._lock = threading.Lock()

    def record_outcome(self, pnl_pct: float) -> None:
        with self._lock:
            self._outcomes.append(float(pnl_pct))

    def profile_entry(self, df: pd.DataFrame, side: str) -> CompetitiveEntryProfile:
        atr_pct = self._atr_pct(df)
        rel_volume = self._relative_volume(df)
        spread_proxy = self._spread_proxy_pct(df)
        drawdown_guard = self._drawdown_guard()

        liquidity_ok = rel_volume >= 0.20 and spread_proxy <= 2.50
        liquidity_reason = (
            "ok"
            if liquidity_ok
            else f"rel_volume={rel_volume:.2f} spread_proxy={spread_proxy:.2f}%"
        )

        # Small exploratory entries: never martingale; reduce size when recent
        # outcomes are poor or liquidity is thin.
        base_risk = float(os.getenv("NIJA_COMPETITIVE_BASE_RISK_FRACTION", "0.035"))
        risk_fraction = max(0.005, min(0.05, base_risk * drawdown_guard))
        if rel_volume < 0.50:
            risk_fraction *= 0.65

        stop_loss_pct = max(0.45, min(2.40, atr_pct * 1.25))
        trailing_stop_pct = max(0.30, min(1.80, atr_pct * 0.85))
        tp1 = max(0.45, min(2.20, atr_pct * 0.95))
        tp2 = max(tp1 + 0.20, min(3.50, atr_pct * 1.55))
        tp3 = max(tp2 + 0.25, min(5.00, atr_pct * 2.35))

        return CompetitiveEntryProfile(
            risk_fraction=risk_fraction,
            stop_loss_pct=stop_loss_pct,
            trailing_stop_pct=trailing_stop_pct,
            take_profit_pct=(tp1, tp2, tp3),
            liquidity_ok=liquidity_ok,
            liquidity_reason=liquidity_reason,
        )

    def _drawdown_guard(self) -> float:
        with self._lock:
            outcomes = list(self._outcomes)
        if len(outcomes) < 20:
            return 1.0
        avg = sum(outcomes[-20:]) / 20.0
        losses = sum(1 for pnl in outcomes[-20:] if pnl < 0)
        if losses >= 12 or avg < 0:
            return 0.50
        if losses <= 6 and avg > 0:
            return 1.10
        return 1.0

    @staticmethod
    def _atr_pct(df: pd.DataFrame) -> float:
        try:
            high = pd.to_numeric(df["high"], errors="coerce")
            low = pd.to_numeric(df["low"], errors="coerce")
            close = pd.to_numeric(df["close"], errors="coerce")
            true_range = (high - low).abs()
            atr = float(true_range.tail(14).mean())
            price = float(close.iloc[-1])
            return (atr / price * 100.0) if price > 0 else 0.75
        except Exception:
            return 0.75

    @staticmethod
    def _relative_volume(df: pd.DataFrame) -> float:
        try:
            volume = pd.to_numeric(df["volume"], errors="coerce")
            current = float(volume.iloc[-1])
            baseline = float(volume.tail(21).iloc[:-1].mean())
            return current / baseline if baseline > 0 else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _spread_proxy_pct(df: pd.DataFrame) -> float:
        try:
            if "bid" in df.columns and "ask" in df.columns:
                bid = float(df["bid"].iloc[-1])
                ask = float(df["ask"].iloc[-1])
                mid = (bid + ask) / 2.0
                return ((ask - bid) / mid * 100.0) if mid > 0 else 99.0
            high = float(df["high"].iloc[-1])
            low = float(df["low"].iloc[-1])
            close = float(df["close"].iloc[-1])
            return ((high - low) / close * 100.0) if close > 0 else 99.0
        except Exception:
            return 99.0


_policy: CompetitiveProfitabilityPolicy | None = None
_lock = threading.Lock()


def get_competitive_profitability_policy() -> CompetitiveProfitabilityPolicy:
    global _policy
    if _policy is None:
        with _lock:
            if _policy is None:
                _policy = CompetitiveProfitabilityPolicy()
    return _policy


def record_competitive_trade_outcome(pnl_pct: float) -> None:
    get_competitive_profitability_policy().record_outcome(pnl_pct)
