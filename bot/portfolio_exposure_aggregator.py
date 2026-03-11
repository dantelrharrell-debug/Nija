"""
NIJA Portfolio Exposure Aggregator
=====================================

Tracks total portfolio exposure by asset class and direction (long / short),
and enforces institutional-grade limits to prevent portfolio drift.

What institutional systems track
---------------------------------
::

    Asset Class     Long     Short
    ───────────────────────────────
    Crypto          35 %     10 %
    Equities        20 %      5 %
    Commodities     10 %      0 %

Enforced rules (all configurable)
-----------------------------------
* Crypto exposure        ≤ 40 % of portfolio
* Single asset (symbol)  ≤ 15 % of portfolio
* Total leverage         ≤ 2× (total gross exposure ÷ portfolio value)

Architecture
------------
::

    on position open:
        result = aggregator.approve_entry(symbol, size_usd, direction, portfolio_value)
        if not result.allowed:
            return

    after position opens:
        aggregator.register_position(symbol, size_usd, direction)

    on position close:
        aggregator.remove_position(symbol, direction)

    diagnostics:
        aggregator.get_exposure_table()   → Exposure by class × direction
        aggregator.get_full_report()      → All metrics

Asset classification
--------------------
Symbols are auto-classified using suffix/prefix patterns:
    * ``"-USD"`` / ``"-BTC"`` / ``"-ETH"`` suffixes → Crypto
    * ``"SPY"`` / ``"QQQ"`` / ``"AAPL"`` etc.     → Equities (configurable)
    * ``"GC=F"`` / ``"CL=F"`` / ``"SI=F"`` etc.   → Commodities (configurable)
    * Unknown symbols                                → Other

Usage
-----
::

    from bot.portfolio_exposure_aggregator import get_portfolio_exposure_aggregator

    agg = get_portfolio_exposure_aggregator()

    # Before opening a position:
    result = agg.approve_entry("BTC-USD", size_usd=3_000.0, direction="long",
                                portfolio_value=10_000.0)
    if not result.allowed:
        logger.warning("Exposure limit: %s", result.reason)
        return

    # After the order fills:
    agg.register_position("BTC-USD", size_usd=3_000.0, direction="long")

    # When the position closes:
    agg.remove_position("BTC-USD", direction="long")

    # Diagnostic view:
    table = agg.get_exposure_table(portfolio_value=10_000.0)

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
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("nija.portfolio_exposure_aggregator")


# ---------------------------------------------------------------------------
# Asset classification
# ---------------------------------------------------------------------------

class AssetClass(Enum):
    """Broad asset class used for exposure bucketing."""
    CRYPTO = "Crypto"
    EQUITIES = "Equities"
    COMMODITIES = "Commodities"
    OTHER = "Other"


# Suffix patterns → Crypto (Coinbase-style pairs)
_CRYPTO_SUFFIXES: Tuple[str, ...] = (
    "-USD", "-USDT", "-USDC", "-BTC", "-ETH", "-EUR", "-GBP",
)

# Known equity tickers (expand as needed)
_EQUITY_TICKERS: Set[str] = {
    "SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "TSLA", "META", "JPM", "BAC", "GS", "V", "MA",
}

# Commodity futures suffix patterns (e.g. yfinance style)
_COMMODITY_SUFFIXES: Tuple[str, ...] = ("=F",)
_COMMODITY_PREFIXES: Tuple[str, ...] = ("GC", "SI", "CL", "NG", "ZC", "ZS", "ZW")


def classify_symbol(symbol: str) -> AssetClass:
    """Classify a trading symbol into an asset class.

    Parameters
    ----------
    symbol:
        Instrument identifier (e.g. ``"BTC-USD"``, ``"AAPL"``, ``"GC=F"``).

    Returns
    -------
    AssetClass
    """
    s = symbol.upper().strip()

    # Commodity check first (before equity catch-all)
    if any(s.endswith(suffix) for suffix in _COMMODITY_SUFFIXES):
        return AssetClass.COMMODITIES
    if any(s.startswith(pfx) for pfx in _COMMODITY_PREFIXES):
        return AssetClass.COMMODITIES

    # Crypto
    if any(s.endswith(suffix) for suffix in _CRYPTO_SUFFIXES):
        return AssetClass.CRYPTO

    # Equities
    if s in _EQUITY_TICKERS:
        return AssetClass.EQUITIES

    return AssetClass.OTHER


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ExposureAggregatorConfig:
    """Configurable exposure limits.

    All percentage values are expressed as fractions of portfolio value
    (0.0–1.0 unless noted).

    Attributes
    ----------
    max_crypto_exposure_pct:
        Maximum gross crypto exposure as a fraction of portfolio.
        Default: 0.40 (40 %).
    max_single_asset_pct:
        Maximum exposure in any single symbol.
        Default: 0.15 (15 %).
    max_total_leverage:
        Maximum total leverage (gross exposure ÷ portfolio value).
        Default: 2.0 (2×).
    max_equities_exposure_pct:
        Maximum gross equity exposure.
        Default: 0.50 (50 %).
    max_commodities_exposure_pct:
        Maximum gross commodity exposure.
        Default: 0.30 (30 %).
    max_single_class_long_pct:
        Maximum *long* exposure in any single asset class.
        Default: 0.40 (40 %).
    warn_only:
        If True, log warnings instead of blocking trades when limits are
        breached.  Set to False (default) for hard enforcement.
    """
    max_crypto_exposure_pct: float = 0.40
    max_single_asset_pct: float = 0.15
    max_total_leverage: float = 2.0
    max_equities_exposure_pct: float = 0.50
    max_commodities_exposure_pct: float = 0.30
    max_single_class_long_pct: float = 0.40
    warn_only: bool = False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PositionRecord:
    """Single tracked position."""
    symbol: str
    size_usd: float
    direction: str           # "long" or "short"
    asset_class: AssetClass
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class ExposureEntry:
    """Exposure data for one asset-class / direction cell."""
    asset_class: str
    long_usd: float = 0.0
    short_usd: float = 0.0
    long_pct: float = 0.0
    short_pct: float = 0.0


@dataclass
class ApprovalResult:
    """Result of ``approve_entry``."""
    allowed: bool
    reason: str = ""
    violations: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------

class PortfolioExposureAggregator:
    """Asset-class exposure tracker with institutional-grade limit enforcement.

    Thread-safe.  Use ``get_portfolio_exposure_aggregator()`` for the singleton.
    """

    def __init__(
        self,
        config: Optional[ExposureAggregatorConfig] = None,
    ) -> None:
        self._config = config or ExposureAggregatorConfig()
        self._lock = threading.RLock()

        # symbol → PositionRecord (we allow multiple records per symbol for
        # long + short tracking separately — keyed by "SYMBOL:direction")
        self._positions: Dict[str, PositionRecord] = {}

        logger.info(
            "📊 PortfolioExposureAggregator initialised | "
            "crypto≤%.0f%% | single≤%.0f%% | leverage≤%.1f×",
            self._config.max_crypto_exposure_pct * 100,
            self._config.max_single_asset_pct * 100,
            self._config.max_total_leverage,
        )

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    @staticmethod
    def _position_key(symbol: str, direction: str) -> str:
        return f"{symbol.upper()}:{direction.lower()}"

    def register_position(
        self,
        symbol: str,
        size_usd: float,
        direction: str,
    ) -> None:
        """Record an open position.

        Parameters
        ----------
        symbol:
            Instrument identifier.
        size_usd:
            Position size in USD (gross notional).
        direction:
            ``"long"`` or ``"short"``.
        """
        key = self._position_key(symbol, direction)
        asset_class = classify_symbol(symbol)
        record = PositionRecord(
            symbol=symbol.upper(),
            size_usd=max(size_usd, 0.0),
            direction=direction.lower(),
            asset_class=asset_class,
        )
        with self._lock:
            self._positions[key] = record
        logger.debug(
            "📌 Position registered: %s %s $%.2f [%s]",
            direction,
            symbol,
            size_usd,
            asset_class.value,
        )

    def remove_position(
        self,
        symbol: str,
        direction: str,
    ) -> bool:
        """Remove a closed position.

        Parameters
        ----------
        symbol, direction:
            Must match the values used in ``register_position``.

        Returns
        -------
        bool
            True if the position was found and removed.
        """
        key = self._position_key(symbol, direction)
        with self._lock:
            if key in self._positions:
                del self._positions[key]
                logger.debug("🗑️  Position removed: %s %s", direction, symbol)
                return True
        logger.warning(
            "⚠️  remove_position: key '%s' not found in registry", key
        )
        return False

    def update_position_size(
        self,
        symbol: str,
        direction: str,
        new_size_usd: float,
    ) -> bool:
        """Update the size of an existing position (e.g. after partial close).

        Returns
        -------
        bool
            True if the position was found and updated.
        """
        key = self._position_key(symbol, direction)
        with self._lock:
            if key in self._positions:
                self._positions[key].size_usd = max(new_size_usd, 0.0)
                return True
        return False

    # ------------------------------------------------------------------
    # Exposure calculations
    # ------------------------------------------------------------------

    def _compute_exposure(self) -> Dict[AssetClass, Dict[str, float]]:
        """Compute long / short exposure in USD by asset class.

        Returns
        -------
        dict
            ``{AssetClass: {"long": float, "short": float}}``
        """
        exposure: Dict[AssetClass, Dict[str, float]] = {
            cls: {"long": 0.0, "short": 0.0}
            for cls in AssetClass
        }
        with self._lock:
            for rec in self._positions.values():
                exposure[rec.asset_class][rec.direction] += rec.size_usd
        return exposure

    def _symbol_exposure(self, symbol: str) -> float:
        """Return total gross exposure (long + short) for a single symbol."""
        sym = symbol.upper()
        with self._lock:
            return sum(
                rec.size_usd
                for rec in self._positions.values()
                if rec.symbol == sym
            )

    def _total_gross_exposure(self) -> float:
        """Return total gross exposure across all positions."""
        with self._lock:
            return sum(rec.size_usd for rec in self._positions.values())

    # ------------------------------------------------------------------
    # Approval gate
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        symbol: str,
        size_usd: float,
        direction: str,
        portfolio_value: float,
    ) -> ApprovalResult:
        """Check whether a proposed position is within all exposure limits.

        Call this **before** registering the position or placing an order.

        Parameters
        ----------
        symbol:
            Instrument identifier.
        size_usd:
            Proposed position size in USD.
        direction:
            ``"long"`` or ``"short"``.
        portfolio_value:
            Current portfolio value in USD (used for percentage calculations).

        Returns
        -------
        ApprovalResult
            ``allowed=True`` → proceed.
            ``allowed=False`` → one or more limits would be breached.
        """
        if portfolio_value <= 0:
            return ApprovalResult(allowed=True)  # can't calculate — let through

        violations: List[str] = []
        cfg = self._config
        asset_class = classify_symbol(symbol)

        # ---- 1. Single-asset limit ----
        existing_symbol_exp = self._symbol_exposure(symbol)
        projected_symbol_exp = existing_symbol_exp + size_usd
        projected_symbol_pct = projected_symbol_exp / portfolio_value
        if projected_symbol_pct > cfg.max_single_asset_pct:
            violations.append(
                f"Single-asset limit breached: {symbol} would be "
                f"{projected_symbol_pct * 100:.1f}% of portfolio "
                f"(limit: {cfg.max_single_asset_pct * 100:.0f}%)"
            )

        # ---- 2. Asset-class limit ----
        exp_by_class = self._compute_exposure()
        current_class_exp = exp_by_class[asset_class]["long"] + exp_by_class[asset_class]["short"]
        projected_class_exp = current_class_exp + size_usd
        projected_class_pct = projected_class_exp / portfolio_value

        if asset_class == AssetClass.CRYPTO and projected_class_pct > cfg.max_crypto_exposure_pct:
            violations.append(
                f"Crypto exposure limit breached: would be "
                f"{projected_class_pct * 100:.1f}% "
                f"(limit: {cfg.max_crypto_exposure_pct * 100:.0f}%)"
            )
        elif asset_class == AssetClass.EQUITIES and projected_class_pct > cfg.max_equities_exposure_pct:
            violations.append(
                f"Equities exposure limit breached: would be "
                f"{projected_class_pct * 100:.1f}% "
                f"(limit: {cfg.max_equities_exposure_pct * 100:.0f}%)"
            )
        elif asset_class == AssetClass.COMMODITIES and projected_class_pct > cfg.max_commodities_exposure_pct:
            violations.append(
                f"Commodities exposure limit breached: would be "
                f"{projected_class_pct * 100:.1f}% "
                f"(limit: {cfg.max_commodities_exposure_pct * 100:.0f}%)"
            )

        # ---- 3. Long exposure per class ----
        if direction.lower() == "long":
            current_class_long = exp_by_class[asset_class]["long"]
            projected_class_long_pct = (current_class_long + size_usd) / portfolio_value
            if projected_class_long_pct > cfg.max_single_class_long_pct:
                violations.append(
                    f"Long exposure limit for {asset_class.value} breached: "
                    f"would be {projected_class_long_pct * 100:.1f}% "
                    f"(limit: {cfg.max_single_class_long_pct * 100:.0f}%)"
                )

        # ---- 4. Total leverage ----
        total_gross = self._total_gross_exposure() + size_usd
        projected_leverage = total_gross / portfolio_value
        if projected_leverage > cfg.max_total_leverage:
            violations.append(
                f"Total leverage limit breached: would be "
                f"{projected_leverage:.2f}× "
                f"(limit: {cfg.max_total_leverage:.1f}×)"
            )

        if not violations:
            return ApprovalResult(allowed=True)

        reason = " | ".join(violations)
        if cfg.warn_only:
            logger.warning("⚠️  Exposure limit warning (warn_only=True): %s", reason)
            return ApprovalResult(allowed=True, reason=reason, violations=violations)

        logger.warning("🚫 Exposure limit — trade blocked: %s", reason)
        return ApprovalResult(allowed=False, reason=reason, violations=violations)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_exposure_table(
        self,
        portfolio_value: float,
    ) -> List[ExposureEntry]:
        """Return a structured exposure table (one row per asset class).

        Parameters
        ----------
        portfolio_value:
            Current portfolio value used to compute percentages.

        Returns
        -------
        list of ExposureEntry
        """
        exp = self._compute_exposure()
        pv = max(portfolio_value, 1e-9)
        table: List[ExposureEntry] = []
        for cls in AssetClass:
            long_usd = exp[cls]["long"]
            short_usd = exp[cls]["short"]
            table.append(ExposureEntry(
                asset_class=cls.value,
                long_usd=long_usd,
                short_usd=short_usd,
                long_pct=long_usd / pv * 100,
                short_pct=short_usd / pv * 100,
            ))
        return table

    def get_full_report(self, portfolio_value: float) -> Dict:
        """Return a comprehensive JSON-serialisable exposure report.

        Parameters
        ----------
        portfolio_value:
            Current portfolio value in USD.
        """
        pv = max(portfolio_value, 1e-9)
        table = self.get_exposure_table(portfolio_value)
        total_gross = self._total_gross_exposure()
        leverage = total_gross / pv

        with self._lock:
            position_count = len(self._positions)
            positions = [
                {
                    "symbol": rec.symbol,
                    "direction": rec.direction,
                    "size_usd": rec.size_usd,
                    "asset_class": rec.asset_class.value,
                    "pct_of_portfolio": rec.size_usd / pv * 100,
                }
                for rec in self._positions.values()
            ]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "portfolio_value": portfolio_value,
            "position_count": position_count,
            "total_gross_exposure_usd": total_gross,
            "total_leverage": leverage,
            "limits": {
                "max_crypto_pct": self._config.max_crypto_exposure_pct * 100,
                "max_single_asset_pct": self._config.max_single_asset_pct * 100,
                "max_leverage": self._config.max_total_leverage,
            },
            "exposure_table": [
                {
                    "asset_class": e.asset_class,
                    "long_usd": e.long_usd,
                    "short_usd": e.short_usd,
                    "long_pct": e.long_pct,
                    "short_pct": e.short_pct,
                }
                for e in table
            ],
            "positions": positions,
        }

    def print_exposure_table(self, portfolio_value: float) -> None:
        """Print a human-readable exposure table to the logger."""
        table = self.get_exposure_table(portfolio_value)
        total = self._total_gross_exposure()
        pv = max(portfolio_value, 1e-9)
        lines = [
            "",
            "📊 PORTFOLIO EXPOSURE TABLE",
            f"   Portfolio value : ${portfolio_value:,.2f}",
            f"   Total gross exp : ${total:,.2f}  ({total / pv * 100:.1f}%)",
            f"   Leverage        : {total / pv:.2f}×",
            "",
            f"{'Asset Class':<15} {'Long $':>12} {'Long %':>8} {'Short $':>12} {'Short %':>8}",
            "-" * 60,
        ]
        for e in table:
            lines.append(
                f"{e.asset_class:<15} "
                f"${e.long_usd:>11,.2f} "
                f"{e.long_pct:>7.1f}% "
                f"${e.short_usd:>11,.2f} "
                f"{e.short_pct:>7.1f}%"
            )
        lines.append("-" * 60)
        logger.info("\n".join(lines))

    def get_status(self) -> Dict:
        """Return a compact JSON-serialisable status snapshot."""
        with self._lock:
            return {
                "position_count": len(self._positions),
                "limits": {
                    "max_crypto_pct": self._config.max_crypto_exposure_pct * 100,
                    "max_single_asset_pct": self._config.max_single_asset_pct * 100,
                    "max_leverage": self._config.max_total_leverage,
                    "warn_only": self._config.warn_only,
                },
            }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[PortfolioExposureAggregator] = None
_instance_lock = threading.Lock()


def get_portfolio_exposure_aggregator(
    config: Optional[ExposureAggregatorConfig] = None,
) -> PortfolioExposureAggregator:
    """Return (or create) the global ``PortfolioExposureAggregator`` singleton.

    Parameters
    ----------
    config:
        Optional configuration; only used on the **first** call.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PortfolioExposureAggregator(config)
    return _instance


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    cfg = ExposureAggregatorConfig(
        max_crypto_exposure_pct=0.40,
        max_single_asset_pct=0.15,
        max_total_leverage=2.0,
    )
    agg = PortfolioExposureAggregator(cfg)
    portfolio = 10_000.0

    print("\n=== Portfolio Exposure Aggregator — smoke test ===\n")

    # Open a BTC position (10% of portfolio = $1,000)
    r = agg.approve_entry("BTC-USD", 1_000.0, "long", portfolio)
    print(f"BTC $1000 long — allowed: {r.allowed}")
    agg.register_position("BTC-USD", 1_000.0, "long")

    # Open another BTC position (8% more = $800 → 18% total → exceeds 15%)
    r2 = agg.approve_entry("BTC-USD", 800.0, "long", portfolio)
    print(f"BTC $800 more  — allowed: {r2.allowed}  reason={r2.reason[:80] if r2.reason else ''}")

    # Open ETH (10% of portfolio = $1,000)
    r3 = agg.approve_entry("ETH-USD", 1_000.0, "long", portfolio)
    print(f"ETH $1000 long — allowed: {r3.allowed}")
    agg.register_position("ETH-USD", 1_000.0, "long")

    # Print table
    agg.print_exposure_table(portfolio)

    # Full report
    import json
    report = agg.get_full_report(portfolio)
    print(json.dumps(report, indent=2)[:600], "…")

    print("\n✅ Smoke test complete")
