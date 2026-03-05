"""
NIJA Entry Guardrails
=====================
Three institutional-grade filters that run immediately before any new position
is opened.  They prevent the three biggest causes of bot blow-ups:

1. PortfolioCorrelationFilter
   Blocks new entries when the portfolio already holds too many positions whose
   daily returns are highly correlated with the candidate symbol.  Prevents a
   single macro shock from wiping out every open position simultaneously.

2. LiquidityFilter
   Blocks entries when the candidate market lacks sufficient 24-hour volume or
   has an excessively wide bid-ask spread.  Prevents entries that would suffer
   crippling slippage or where the position cannot be unwound cleanly.

3. ExchangeLatencyGuard
   Blocks entries when the exchange API round-trip time has risen above a safe
   threshold.  High latency indicates server-side stress, degraded connectivity,
   or an overloaded order book — all conditions that increase execution risk and
   slippage significantly.

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

_T = TypeVar("_T")

import numpy as np

logger = logging.getLogger("nija.entry_guardrails")

# ---------------------------------------------------------------------------
# Shared result type
# ---------------------------------------------------------------------------

@dataclass
class GuardrailResult:
    """Result returned by every guardrail check."""
    passed: bool
    reason: str
    details: Dict = field(default_factory=dict)


# ===========================================================================
# 1. Portfolio Correlation Filter
# ===========================================================================

# Static correlation-group map used when live price history is unavailable.
# Keys are group names; values list the symbols that belong to each group.
_DEFAULT_CORRELATION_GROUPS: Dict[str, List[str]] = {
    "BTC_RELATED":  ["BTC-USD", "BTC-USDT", "WBTC-USD"],
    "ETH_RELATED":  ["ETH-USD", "ETH-USDT", "ETH2-USD"],
    "MEME_COINS":   ["DOGE-USD", "SHIB-USD", "PEPE-USD", "FLOKI-USD"],
    "DEFI":         ["UNI-USD", "AAVE-USD", "COMP-USD", "SUSHI-USD", "CRV-USD"],
    "LAYER1":       ["SOL-USD", "ADA-USD", "AVAX-USD", "DOT-USD", "NEAR-USD"],
    "LAYER2":       ["MATIC-USD", "ARB-USD", "OP-USD"],
    "STABLECOINS":  ["USDT-USD", "USDC-USD", "DAI-USD"],
}


class PortfolioCorrelationFilter:
    """
    Block new entries when the candidate symbol is too highly correlated with
    the current portfolio.

    Two complementary checks are performed:

    a) **Static group check** – Uses a predefined map of correlation groups
       (e.g. all meme-coins, all ETH tokens).  If the portfolio already contains
       ``max_positions_per_group`` or more members of the same group as the
       candidate, the entry is blocked.

    b) **Dynamic return-correlation check** – When price history is available,
       computes the rolling Pearson correlation between the candidate's daily
       returns and those of every existing position.  If the average pairwise
       correlation exceeds ``max_avg_correlation``, the entry is blocked.
    """

    def __init__(
        self,
        max_positions_per_group: int = 2,
        max_avg_correlation: float = 0.75,
        correlation_window: int = 20,
        correlation_groups: Optional[Dict[str, List[str]]] = None,
    ):
        """
        Args:
            max_positions_per_group: Maximum positions allowed from the same
                static correlation group (default 2).
            max_avg_correlation: Maximum average pairwise correlation (Pearson)
                allowed before blocking entry (default 0.75).
            correlation_window: Number of recent price bars to use when
                computing rolling correlations (default 20).
            correlation_groups: Optional custom group map.  Defaults to
                ``_DEFAULT_CORRELATION_GROUPS``.
        """
        self.max_positions_per_group = max_positions_per_group
        self.max_avg_correlation = max_avg_correlation
        self.correlation_window = correlation_window
        self.correlation_groups = (
            correlation_groups if correlation_groups is not None
            else _DEFAULT_CORRELATION_GROUPS
        )
        # Reverse index: symbol -> group name (populated lazily)
        self._symbol_to_group: Dict[str, str] = {}
        for group, symbols in self.correlation_groups.items():
            for sym in symbols:
                self._symbol_to_group[sym] = group

        # Price history store: symbol -> deque of recent close prices
        self._price_history: Dict[str, deque] = {}

        logger.info(
            "🔗 PortfolioCorrelationFilter initialized "
            f"(max_per_group={max_positions_per_group}, "
            f"max_avg_corr={max_avg_correlation:.2f})"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_price(self, symbol: str, close_price: float) -> None:
        """Record the latest close price for a symbol."""
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=self.correlation_window + 1)
        self._price_history[symbol].append(float(close_price))

    def check(
        self,
        candidate_symbol: str,
        open_position_symbols: List[str],
    ) -> GuardrailResult:
        """
        Run both correlation checks for ``candidate_symbol``.

        Args:
            candidate_symbol: The symbol about to be entered.
            open_position_symbols: Symbols of currently open positions.

        Returns:
            GuardrailResult with ``passed=True`` if the entry is safe.
        """
        if not open_position_symbols:
            return GuardrailResult(
                passed=True,
                reason="No open positions – correlation check skipped",
            )

        # (a) Static group check
        group_result = self._check_static_group(candidate_symbol, open_position_symbols)
        if not group_result.passed:
            return group_result

        # (b) Dynamic correlation check (only if we have price history)
        dyn_result = self._check_dynamic_correlation(
            candidate_symbol, open_position_symbols
        )
        return dyn_result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_static_group(
        self,
        candidate: str,
        positions: List[str],
    ) -> GuardrailResult:
        candidate_group = self._symbol_to_group.get(candidate)
        if candidate_group is None:
            return GuardrailResult(
                passed=True,
                reason=f"{candidate} not in any static group – group check skipped",
            )

        same_group_open = [
            s for s in positions
            if self._symbol_to_group.get(s) == candidate_group
        ]

        details = {
            "group": candidate_group,
            "same_group_open": same_group_open,
            "max_allowed": self.max_positions_per_group,
        }

        if len(same_group_open) >= self.max_positions_per_group:
            msg = (
                f"Correlation group '{candidate_group}' already has "
                f"{len(same_group_open)}/{self.max_positions_per_group} positions "
                f"({', '.join(same_group_open)})"
            )
            logger.info(f"   🔗 CORRELATION FILTER blocked {candidate}: {msg}")
            return GuardrailResult(passed=False, reason=msg, details=details)

        return GuardrailResult(
            passed=True,
            reason=(
                f"Group '{candidate_group}': "
                f"{len(same_group_open)}/{self.max_positions_per_group} — OK"
            ),
            details=details,
        )

    def _check_dynamic_correlation(
        self,
        candidate: str,
        positions: List[str],
    ) -> GuardrailResult:
        if candidate not in self._price_history:
            return GuardrailResult(
                passed=True,
                reason=f"No price history for {candidate} – dynamic check skipped",
            )

        candidate_prices = list(self._price_history[candidate])
        if len(candidate_prices) < 3:
            return GuardrailResult(
                passed=True,
                reason="Insufficient price history for dynamic correlation check",
            )

        candidate_returns = np.diff(candidate_prices) / np.array(candidate_prices[:-1])

        correlations: List[float] = []
        for sym in positions:
            if sym not in self._price_history:
                continue
            sym_prices = list(self._price_history[sym])
            if len(sym_prices) < 3:
                continue
            sym_returns = np.diff(sym_prices) / np.array(sym_prices[:-1])

            # Align lengths
            min_len = min(len(candidate_returns), len(sym_returns))
            if min_len < 3:
                continue
            corr = float(np.corrcoef(
                candidate_returns[-min_len:],
                sym_returns[-min_len:],
            )[0, 1])
            if np.isfinite(corr):
                correlations.append(corr)

        if not correlations:
            return GuardrailResult(
                passed=True,
                reason="No overlapping price history for dynamic correlation check",
            )

        avg_corr = float(np.mean(correlations))
        max_corr = float(np.max(correlations))

        details = {
            "avg_correlation": round(avg_corr, 4),
            "max_correlation": round(max_corr, 4),
            "threshold": self.max_avg_correlation,
            "checked_symbols": len(correlations),
        }

        if avg_corr > self.max_avg_correlation:
            msg = (
                f"Average portfolio correlation {avg_corr:.2f} > "
                f"threshold {self.max_avg_correlation:.2f} "
                f"(max pairwise: {max_corr:.2f})"
            )
            logger.info(f"   🔗 CORRELATION FILTER blocked {candidate}: {msg}")
            return GuardrailResult(passed=False, reason=msg, details=details)

        return GuardrailResult(
            passed=True,
            reason=f"Average correlation {avg_corr:.2f} ≤ {self.max_avg_correlation:.2f} — OK",
            details=details,
        )


# ===========================================================================
# 2. Liquidity Filter
# ===========================================================================


class LiquidityFilter:
    """
    Block entries in markets that are too illiquid to trade safely.

    Checks three dimensions:
    - **Minimum 24 h volume** (USD): position cannot be a disproportionate
      fraction of daily turnover.
    - **Maximum bid-ask spread** (basis points): wide spread implies high
      slippage cost on entry *and* exit.
    - **Position-as-fraction-of-volume**: large positions in thin markets
      move price against the bot.
    """

    def __init__(
        self,
        min_volume_24h_usd: float = 1_000_000.0,
        max_spread_bps: float = 50.0,
        max_position_volume_fraction: float = 0.05,
    ):
        """
        Args:
            min_volume_24h_usd: Minimum acceptable 24 h USD volume (default $1M).
                This default is calibrated for accounts trading position sizes in
                the $10–$500 range (STARTER/SAVER tiers).  Larger accounts
                (INCOME/BALLER tiers) should raise this to $5M–$25M to avoid
                moving the market with their positions.
            max_spread_bps: Maximum bid-ask spread in basis points (default 50 bps
                = 0.5 %).  This is a *conservative* ceiling; actual top-10
                liquidity pairs (BTC, ETH, SOL) typically have spreads of 1–5 bps.
                For pairs not directly observable via the broker API the caller
                should supply a measured bid/ask rather than rely on the internal
                0.1 % estimate.
            max_position_volume_fraction: Maximum allowed ratio of proposed position
                size to 24 h volume (default 5 %).
        """
        self.min_volume_24h_usd = min_volume_24h_usd
        self.max_spread_bps = max_spread_bps
        self.max_position_volume_fraction = max_position_volume_fraction

        logger.info(
            "💧 LiquidityFilter initialized "
            f"(min_vol=${min_volume_24h_usd:,.0f}, "
            f"max_spread={max_spread_bps:.0f}bps, "
            f"max_pos_frac={max_position_volume_fraction:.1%})"
        )

    def check(
        self,
        symbol: str,
        volume_24h_usd: float,
        bid: float,
        ask: float,
        position_size_usd: Optional[float] = None,
    ) -> GuardrailResult:
        """
        Run all liquidity checks.

        Args:
            symbol: Trading pair being evaluated.
            volume_24h_usd: 24-hour USD volume for the symbol.
            bid: Current best bid price.
            ask: Current best ask price.
            position_size_usd: Proposed position size in USD (optional).

        Returns:
            GuardrailResult.
        """
        failures: List[str] = []
        details: Dict = {}

        # --- Volume check ---
        details["volume_24h_usd"] = volume_24h_usd
        details["min_volume_24h_usd"] = self.min_volume_24h_usd
        if volume_24h_usd < self.min_volume_24h_usd:
            failures.append(
                f"Volume ${volume_24h_usd:,.0f} < min ${self.min_volume_24h_usd:,.0f}"
            )

        # --- Spread check ---
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
            spread_bps = ((ask - bid) / mid) * 10_000 if mid > 0 else 0.0
            details["spread_bps"] = round(spread_bps, 2)
            details["max_spread_bps"] = self.max_spread_bps
            if spread_bps > self.max_spread_bps:
                failures.append(
                    f"Spread {spread_bps:.1f}bps > max {self.max_spread_bps:.0f}bps"
                )
        else:
            # No reliable bid/ask – skip spread check but warn
            details["spread_bps"] = None
            logger.debug(
                f"   💧 {symbol}: No valid bid/ask for spread check "
                f"(bid={bid}, ask={ask})"
            )

        # --- Position-as-fraction-of-volume check ---
        if position_size_usd is not None and volume_24h_usd > 0:
            frac = position_size_usd / volume_24h_usd
            details["position_volume_fraction"] = round(frac, 4)
            details["max_position_volume_fraction"] = self.max_position_volume_fraction
            if frac > self.max_position_volume_fraction:
                failures.append(
                    f"Position {frac:.1%} of daily volume "
                    f"> max {self.max_position_volume_fraction:.1%}"
                )

        if failures:
            reason = " | ".join(failures)
            logger.info(f"   💧 LIQUIDITY FILTER blocked {symbol}: {reason}")
            return GuardrailResult(passed=False, reason=reason, details=details)

        return GuardrailResult(
            passed=True,
            reason="Liquidity checks passed",
            details=details,
        )


# ===========================================================================
# 3. Exchange Latency Guard
# ===========================================================================


class ExchangeLatencyGuard:
    """
    Block entries when the exchange API is responding too slowly.

    Maintains a rolling window of recent API round-trip times (RTTs).  If
    the rolling average RTT exceeds ``max_avg_latency_ms``, or the single
    most recent RTT exceeds ``max_single_latency_ms``, the entry is blocked
    until the exchange recovers.

    Callers are responsible for recording RTT samples via
    :meth:`record_latency` after each API call.  The guard also exposes a
    :meth:`measure` context manager / helper for in-line timing.
    """

    def __init__(
        self,
        max_avg_latency_ms: float = 2_000.0,
        max_single_latency_ms: float = 5_000.0,
        window_size: int = 10,
    ):
        """
        Args:
            max_avg_latency_ms: Maximum acceptable rolling-average RTT in ms
                (default 2 000 ms = 2 s).
            max_single_latency_ms: Maximum acceptable single RTT in ms before
                the guard blocks regardless of the rolling average (default
                5 000 ms = 5 s).
            window_size: Number of recent RTT samples to include in the rolling
                average (default 10).
        """
        self.max_avg_latency_ms = max_avg_latency_ms
        self.max_single_latency_ms = max_single_latency_ms
        self._samples: deque = deque(maxlen=window_size)

        logger.info(
            "⏱️  ExchangeLatencyGuard initialized "
            f"(max_avg={max_avg_latency_ms:.0f}ms, "
            f"max_single={max_single_latency_ms:.0f}ms, "
            f"window={window_size})"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_latency(self, latency_ms: float) -> None:
        """Record an API round-trip time in milliseconds."""
        self._samples.append(float(latency_ms))

    def measure(self, func: "Callable[..., _T]", *args: Any, **kwargs: Any) -> "_T":
        """
        Call ``func(*args, **kwargs)``, record the elapsed time, and return
        the function's result.

        Example::

            result = guard.measure(broker.get_ticker, "BTC-USD")
        """
        t0 = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1_000
            self.record_latency(elapsed_ms)

    def check(self, symbol: str = "") -> GuardrailResult:
        """
        Decide whether the exchange is fast enough to trade safely.

        Args:
            symbol: Candidate symbol (used only for logging).

        Returns:
            GuardrailResult.
        """
        if not self._samples:
            # No samples yet – optimistically allow trading
            return GuardrailResult(
                passed=True,
                reason="No latency samples yet – guard inactive",
                details={"samples": 0},
            )

        last_ms = self._samples[-1]
        avg_ms = float(np.mean(self._samples))

        details = {
            "last_latency_ms": round(last_ms, 1),
            "avg_latency_ms": round(avg_ms, 1),
            "max_avg_latency_ms": self.max_avg_latency_ms,
            "max_single_latency_ms": self.max_single_latency_ms,
            "samples": len(self._samples),
        }

        if last_ms > self.max_single_latency_ms:
            msg = (
                f"Last RTT {last_ms:.0f}ms > single-sample ceiling "
                f"{self.max_single_latency_ms:.0f}ms"
            )
            logger.warning(f"   ⏱️  LATENCY GUARD blocked{' ' + symbol if symbol else ''}: {msg}")
            return GuardrailResult(passed=False, reason=msg, details=details)

        if avg_ms > self.max_avg_latency_ms:
            msg = (
                f"Rolling-avg RTT {avg_ms:.0f}ms > threshold "
                f"{self.max_avg_latency_ms:.0f}ms "
                f"(last: {last_ms:.0f}ms, n={len(self._samples)})"
            )
            logger.warning(f"   ⏱️  LATENCY GUARD blocked{' ' + symbol if symbol else ''}: {msg}")
            return GuardrailResult(passed=False, reason=msg, details=details)

        return GuardrailResult(
            passed=True,
            reason=f"RTT avg {avg_ms:.0f}ms, last {last_ms:.0f}ms — OK",
            details=details,
        )

    @property
    def avg_latency_ms(self) -> float:
        """Current rolling-average RTT in milliseconds (0 if no samples)."""
        return float(np.mean(self._samples)) if self._samples else 0.0

    @property
    def last_latency_ms(self) -> float:
        """Most recent RTT sample in milliseconds (0 if no samples)."""
        return float(self._samples[-1]) if self._samples else 0.0


# ===========================================================================
# Composite helper — run all three in one call
# ===========================================================================


def run_all_guardrails(
    *,
    correlation_filter: PortfolioCorrelationFilter,
    liquidity_filter: LiquidityFilter,
    latency_guard: ExchangeLatencyGuard,
    candidate_symbol: str,
    open_position_symbols: List[str],
    volume_24h_usd: float,
    bid: float,
    ask: float,
    position_size_usd: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Run all three guardrails and return a single pass/fail decision.

    Args:
        correlation_filter: Initialised PortfolioCorrelationFilter.
        liquidity_filter:   Initialised LiquidityFilter.
        latency_guard:      Initialised ExchangeLatencyGuard.
        candidate_symbol:   Symbol about to be entered.
        open_position_symbols: Symbols of currently open positions.
        volume_24h_usd:     24-hour USD volume.
        bid:                Current best bid.
        ask:                Current best ask.
        position_size_usd:  Proposed position size in USD.

    Returns:
        (passed: bool, reason: str)  ``passed`` is True only when all three
        guardrails allow the entry.
    """
    # 1. Latency (checked first – cheapest, most time-sensitive)
    lat = latency_guard.check(candidate_symbol)
    if not lat.passed:
        return False, f"[Latency] {lat.reason}"

    # 2. Liquidity
    liq = liquidity_filter.check(
        symbol=candidate_symbol,
        volume_24h_usd=volume_24h_usd,
        bid=bid,
        ask=ask,
        position_size_usd=position_size_usd,
    )
    if not liq.passed:
        return False, f"[Liquidity] {liq.reason}"

    # 3. Correlation
    corr = correlation_filter.check(
        candidate_symbol=candidate_symbol,
        open_position_symbols=open_position_symbols,
    )
    if not corr.passed:
        return False, f"[Correlation] {corr.reason}"

    return True, "All guardrails passed"
