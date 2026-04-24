"""
NIJA Portfolio Alpha Allocator
===============================

Unified position-sizing engine that combines the institutional risk-first
formula with a three-layer market condition filter stack and automatic
compounding as the portfolio grows.

Core formula
------------
    risk_per_trade  = portfolio_value × risk_pct    (scales automatically as balance grows)
    stop_distance   = |entry_price - stop_price| / entry_price
    position_size   = risk_per_trade / stop_distance

Example (2 % risk, 5 % stop):
    Portfolio $500   → risk $10   → position $200
    Portfolio $2 000 → risk $40   → position $800

Filter stack (applied before every trade)
-----------------------------------------
1. **ATR Volatility Filter**  – skip trade when ``atr_pct < min_atr_threshold``
   (avoids choppy, directionless markets where signals are noise).

2. **Trend Filter (200 EMA)** – multiply position size by ``trend_filter_multiplier``
   (default 0.5) when ``current_price < ema_200``.  Trading against the primary
   trend is allowed but with a reduced size.  Set ``trend_filter_multiplier=0``
   to skip the trade entirely when price is below the 200 EMA.

3. **Market Regime Filter**   – pause altcoin trading when BTC's ATR percentage
   exceeds ``btc_spike_threshold``.  BTC volatility spikes often crush alt
   liquidity and invalidate alt signals, so the filter returns a skip decision
   for any non-BTC symbol during such events.

Compounding
-----------
No manual adjustment is needed.  The caller simply passes the current
``portfolio_value`` on each call.  As the portfolio grows, ``risk_per_trade``
grows proportionally, which in turn increases position sizes automatically.

Author : NIJA Trading Systems
Version: 1.0
Date   : March 2026
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger("nija.portfolio_alpha_allocator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RISK_PCT: float = 0.02          # 2 % of portfolio per trade
DEFAULT_MIN_ATR_THRESHOLD: float = 0.005  # 0.5 % minimum ATR (skip below)
DEFAULT_TREND_MULTIPLIER: float = 0.5   # halve size when price < 200 EMA
DEFAULT_BTC_SPIKE_THRESHOLD: float = 0.04  # 4 % BTC ATR → pause altcoins

MIN_POSITION_USD: float = 1.0           # absolute minimum order value
MAX_POSITION_PCT: float = 0.50          # maximum 50 % of portfolio per trade

# Symbols treated as Bitcoin — not subject to the BTC regime filter
BTC_SYMBOLS: Set[str] = {
    "BTC-USD", "BTC-USDT", "BTCUSD", "WBTC-USD",
    "BTC-EUR", "BTC-GBP", "BTC-USDC",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PortfolioAlphaConfig:
    """Configuration for the Portfolio Alpha Allocator."""

    # Baseline risk fraction applied to portfolio_value each trade
    risk_pct: float = DEFAULT_RISK_PCT

    # ATR Volatility Filter — skip trades in choppy markets
    min_atr_threshold: float = DEFAULT_MIN_ATR_THRESHOLD

    # Trend Filter — multiplier applied when price is below the 200 EMA
    trend_filter_multiplier: float = DEFAULT_TREND_MULTIPLIER

    # Market Regime Filter — BTC ATR spike threshold (pause alts above this)
    btc_spike_threshold: float = DEFAULT_BTC_SPIKE_THRESHOLD

    # Position size bounds
    min_position_usd: float = MIN_POSITION_USD
    max_position_pct: float = MAX_POSITION_PCT  # fraction of portfolio_value (50 % default)


@dataclass
class FilterResult:
    """Outcome of a single filter evaluation."""

    approved: bool          # True → allow trade (possibly with reduced size)
    size_multiplier: float  # 1.0 = full size; 0.0 = skip trade
    reason: str             # human-readable explanation


@dataclass
class AllocationResult:
    """Complete result returned by :meth:`PortfolioAlphaAllocator.calculate_position_size`."""

    valid: bool
    position_size_usd: float
    risk_per_trade_usd: float
    stop_distance_pct: float
    risk_pct_used: float
    portfolio_value: float

    # Filter outcomes
    atr_filter: FilterResult = field(default_factory=lambda: FilterResult(True, 1.0, "not evaluated"))
    trend_filter: FilterResult = field(default_factory=lambda: FilterResult(True, 1.0, "not evaluated"))
    regime_filter: FilterResult = field(default_factory=lambda: FilterResult(True, 1.0, "not evaluated"))

    # Compounding metadata
    effective_multiplier: float = 1.0  # combined multiplier from all filters
    clamped: bool = False
    clamp_reason: str = ""

    error: str = ""

    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "position_size_usd": round(self.position_size_usd, 2),
            "risk_per_trade_usd": round(self.risk_per_trade_usd, 2),
            "stop_distance_pct": round(self.stop_distance_pct, 6),
            "risk_pct_used": self.risk_pct_used,
            "portfolio_value": self.portfolio_value,
            "filters": {
                "atr": {
                    "approved": self.atr_filter.approved,
                    "size_multiplier": self.atr_filter.size_multiplier,
                    "reason": self.atr_filter.reason,
                },
                "trend_200ema": {
                    "approved": self.trend_filter.approved,
                    "size_multiplier": self.trend_filter.size_multiplier,
                    "reason": self.trend_filter.reason,
                },
                "btc_regime": {
                    "approved": self.regime_filter.approved,
                    "size_multiplier": self.regime_filter.size_multiplier,
                    "reason": self.regime_filter.reason,
                },
            },
            "effective_multiplier": round(self.effective_multiplier, 4),
            "clamped": self.clamped,
            "clamp_reason": self.clamp_reason,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class PortfolioAlphaAllocator:
    """
    Institutional-grade position sizer with automatic compounding and
    a three-layer market condition filter stack.

    Usage
    -----
    allocator = PortfolioAlphaAllocator()

    # Pass the *current* portfolio value on each call — compounding is automatic.
    result = allocator.calculate_position_size(
        portfolio_value=2_000.0,
        entry_price=100.0,
        stop_price=95.0,
        atr_pct=0.012,          # 1.2 % ATR — medium volatility
        ema_200=98.0,           # current 200-period EMA
        symbol="ETH-USD",
        btc_atr_pct=0.025,      # BTC ATR — below spike threshold
    )
    print(result.position_size_usd)  # → $800.0  (2 % of $2k / 5 % stop)
    """

    def __init__(self, config: Optional[PortfolioAlphaConfig] = None) -> None:
        self.config = config or PortfolioAlphaConfig()

        logger.info("=" * 65)
        logger.info("🏛️  Portfolio Alpha Allocator Initialized")
        logger.info("=" * 65)
        logger.info(f"  Risk per trade       : {self.config.risk_pct:.2%}")
        logger.info(f"  Min ATR threshold    : {self.config.min_atr_threshold:.3%}")
        logger.info(f"  Trend multiplier     : {self.config.trend_filter_multiplier:.2f}×")
        logger.info(f"  BTC spike threshold  : {self.config.btc_spike_threshold:.3%}")
        logger.info(f"  Min position         : ${self.config.min_position_usd:.2f}")
        logger.info(f"  Max position (%)     : {self.config.max_position_pct:.0%} of portfolio")
        logger.info("=" * 65)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        portfolio_value: float,
        entry_price: float,
        stop_price: float,
        *,
        atr_pct: Optional[float] = None,
        ema_200: Optional[float] = None,
        symbol: str = "",
        btc_atr_pct: Optional[float] = None,
    ) -> AllocationResult:
        """
        Calculate the optimal position size after applying all filters.

        Parameters
        ----------
        portfolio_value : float
            Current total portfolio value in USD.  Position sizes compound
            automatically as this value grows.
        entry_price : float
            Planned entry price for the trade.
        stop_price : float
            Stop-loss price for the trade.
        atr_pct : float, optional
            Current Average True Range as a fraction of price (e.g. 0.012 = 1.2 %).
            When provided, the ATR volatility filter is applied.
        ema_200 : float, optional
            Current 200-period EMA value.  When provided, the trend filter is applied.
        symbol : str, optional
            Trading symbol (e.g. "ETH-USD").  Used by the market regime filter to
            determine whether the asset is an altcoin.
        btc_atr_pct : float, optional
            BTC's current ATR as a fraction of price.  When provided together with
            a non-BTC ``symbol``, the market regime filter is applied.

        Returns
        -------
        :class:`AllocationResult`
            Contains position size, filter outcomes, and compounding metadata.
        """
        result = AllocationResult(
            valid=False,
            position_size_usd=0.0,
            risk_per_trade_usd=0.0,
            stop_distance_pct=0.0,
            risk_pct_used=self.config.risk_pct,
            portfolio_value=portfolio_value,
            error="",
        )

        # --- input validation ---
        if portfolio_value <= 0:
            result.error = f"Invalid portfolio_value: {portfolio_value}"
            logger.error("❌ %s", result.error)
            return result

        if entry_price <= 0:
            result.error = f"Invalid entry_price: {entry_price}"
            logger.error("❌ %s", result.error)
            return result

        if stop_price <= 0:
            result.error = f"Invalid stop_price: {stop_price}"
            logger.error("❌ %s", result.error)
            return result

        if stop_price == entry_price:
            result.error = "stop_price must differ from entry_price"
            logger.error("❌ %s", result.error)
            return result

        # --- filter stack ---
        atr_fr = self._apply_atr_filter(atr_pct)
        trend_fr = self._apply_trend_filter(entry_price, ema_200)
        regime_fr = self._apply_btc_regime_filter(symbol, btc_atr_pct)

        result.atr_filter = atr_fr
        result.trend_filter = trend_fr
        result.regime_filter = regime_fr

        # If any filter blocks the trade, return immediately (size = 0)
        if not atr_fr.approved or not trend_fr.approved or not regime_fr.approved:
            blocked_by: List[str] = []
            if not atr_fr.approved:
                blocked_by.append(f"ATR ({atr_fr.reason})")
            if not trend_fr.approved:
                blocked_by.append(f"Trend ({trend_fr.reason})")
            if not regime_fr.approved:
                blocked_by.append(f"Regime ({regime_fr.reason})")
            result.error = f"Trade blocked by: {'; '.join(blocked_by)}"
            result.valid = True   # inputs were valid; filters decided to skip
            logger.info("🚫 AlphaAllocator | SKIP | %s", result.error)
            return result

        # --- combined size multiplier from approved filters ---
        combined_multiplier = atr_fr.size_multiplier * trend_fr.size_multiplier * regime_fr.size_multiplier
        result.effective_multiplier = combined_multiplier

        # --- institutional formula (compounding built-in) ---
        risk_per_trade = portfolio_value * self.config.risk_pct
        stop_distance = abs(entry_price - stop_price) / entry_price

        if stop_distance == 0:
            result.error = "Computed stop_distance is zero; check prices"
            logger.error("❌ %s", result.error)
            return result

        raw_position_size = (risk_per_trade / stop_distance) * combined_multiplier

        # --- clamp ---
        clamped_size, clamped, clamp_reason = self._clamp_position(raw_position_size, portfolio_value)

        result.valid = True
        result.position_size_usd = round(clamped_size, 2)
        result.risk_per_trade_usd = round(risk_per_trade, 2)
        result.stop_distance_pct = round(stop_distance, 6)
        result.clamped = clamped
        result.clamp_reason = clamp_reason

        logger.info(
            "📐 AlphaAllocator | portfolio=$%.2f | risk=%.2f%% | stop_dist=%.3f%% "
            "| multiplier=%.2f× | raw=$%.2f → final=$%.2f%s",
            portfolio_value,
            self.config.risk_pct * 100,
            stop_distance * 100,
            combined_multiplier,
            raw_position_size,
            clamped_size,
            f" [CLAMPED: {clamp_reason}]" if clamped else "",
        )
        return result

    # ------------------------------------------------------------------
    # Filter implementations
    # ------------------------------------------------------------------

    def _apply_atr_filter(self, atr_pct: Optional[float]) -> FilterResult:
        """
        ATR Volatility Filter.

        Skip the trade when ``atr_pct`` is below ``min_atr_threshold``.
        Low ATR indicates a choppy, directionless market where signals are
        unreliable and spreads eat into any edge.

        Parameters
        ----------
        atr_pct : float or None
            ATR as a fraction of current price (e.g. 0.012 = 1.2 %).
            When ``None`` the filter is bypassed and full size is approved.
        """
        if atr_pct is None:
            return FilterResult(True, 1.0, "ATR filter not active (no data)")

        if atr_pct < self.config.min_atr_threshold:
            return FilterResult(
                False,
                0.0,
                f"ATR {atr_pct:.3%} < min threshold {self.config.min_atr_threshold:.3%} — market too choppy",
            )

        return FilterResult(
            True,
            1.0,
            f"ATR {atr_pct:.3%} ≥ min threshold {self.config.min_atr_threshold:.3%}",
        )

    def _apply_trend_filter(
        self,
        current_price: float,
        ema_200: Optional[float],
    ) -> FilterResult:
        """
        200 EMA Trend Filter.

        Reduce position size by ``trend_filter_multiplier`` when
        ``current_price < ema_200`` (price is below the primary trend).
        A multiplier of 0 blocks the trade entirely; 0.5 halves the size.

        Parameters
        ----------
        current_price : float
            Current market price of the asset.
        ema_200 : float or None
            Value of the 200-period EMA.
            When ``None`` the filter is bypassed.
        """
        if ema_200 is None:
            return FilterResult(True, 1.0, "Trend filter not active (no EMA data)")

        if current_price < ema_200:
            multiplier = self.config.trend_filter_multiplier
            if multiplier == 0.0:
                return FilterResult(
                    False,
                    0.0,
                    f"Price ${current_price:.4f} < 200 EMA ${ema_200:.4f} — trend filter blocked trade",
                )
            return FilterResult(
                True,
                multiplier,
                f"Price ${current_price:.4f} < 200 EMA ${ema_200:.4f} — size reduced to {multiplier:.0%}",
            )

        return FilterResult(
            True,
            1.0,
            f"Price ${current_price:.4f} ≥ 200 EMA ${ema_200:.4f} — uptrend confirmed",
        )

    def _apply_btc_regime_filter(
        self,
        symbol: str,
        btc_atr_pct: Optional[float],
    ) -> FilterResult:
        """
        BTC Market Regime Filter.

        Pause altcoin trading when BTC's ATR exceeds ``btc_spike_threshold``.
        During BTC volatility spikes, alt liquidity collapses, correlations
        break down, and alt-specific signals become unreliable.

        This filter is a no-op for BTC symbols themselves.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. "ETH-USD").
        btc_atr_pct : float or None
            BTC's current ATR as a fraction of its price.
            When ``None`` or when ``symbol`` is a BTC pair, the filter is bypassed.
        """
        # Not applicable to BTC pairs or when symbol is unknown
        if not symbol or self._is_btc_symbol(symbol):
            label = symbol if symbol else "unknown symbol"
            return FilterResult(True, 1.0, f"{label} — BTC regime filter not applicable")

        if btc_atr_pct is None:
            return FilterResult(True, 1.0, "BTC regime filter not active (no BTC ATR data)")

        if btc_atr_pct > self.config.btc_spike_threshold:
            return FilterResult(
                False,
                0.0,
                (
                    f"BTC ATR {btc_atr_pct:.3%} > spike threshold "
                    f"{self.config.btc_spike_threshold:.3%} — altcoin trading paused"
                ),
            )

        return FilterResult(
            True,
            1.0,
            f"BTC ATR {btc_atr_pct:.3%} ≤ spike threshold {self.config.btc_spike_threshold:.3%} — regime normal",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_btc_symbol(self, symbol: str) -> bool:
        """Return True when *symbol* refers to a Bitcoin pair."""
        return symbol.upper() in BTC_SYMBOLS

    def _clamp_position(
        self,
        raw_size: float,
        portfolio_value: float,
    ) -> tuple[float, bool, str]:
        """
        Apply floor and cap constraints.

        Returns
        -------
        (clamped_size, was_clamped, reason)
        """
        floor = self.config.min_position_usd
        cap = portfolio_value * self.config.max_position_pct

        if raw_size < floor:
            return floor, True, f"floor=${floor:.2f}"

        if raw_size > cap:
            return cap, True, f"cap={self.config.max_position_pct:.0%} of portfolio (${cap:,.2f})"

        return raw_size, False, ""


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def allocate_alpha_position(
    portfolio_value: float,
    entry_price: float,
    stop_price: float,
    *,
    atr_pct: Optional[float] = None,
    ema_200: Optional[float] = None,
    symbol: str = "",
    btc_atr_pct: Optional[float] = None,
    config: Optional[PortfolioAlphaConfig] = None,
) -> Dict:
    """
    Stateless convenience wrapper around :class:`PortfolioAlphaAllocator`.

    All parameters are forwarded to
    :meth:`PortfolioAlphaAllocator.calculate_position_size`.

    Returns
    -------
    dict – same structure as :meth:`AllocationResult.to_dict`
    """
    allocator = PortfolioAlphaAllocator(config)
    result = allocator.calculate_position_size(
        portfolio_value=portfolio_value,
        entry_price=entry_price,
        stop_price=stop_price,
        atr_pct=atr_pct,
        ema_200=ema_200,
        symbol=symbol,
        btc_atr_pct=btc_atr_pct,
    )
    return result.to_dict()
