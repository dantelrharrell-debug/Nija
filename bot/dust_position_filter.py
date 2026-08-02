"""NIJA Dust Position Filter.

Unified configurable filter for dust positions — positions whose USD value is
below the threshold defined by ``NIJA_DUST_THRESHOLD_USD`` (default $1.00).

Three policy tiers:
  - **Execution** : dust positions are never submitted as new orders.
  - **Reconciliation**: dust positions are excluded from cost-basis reconciliation
    and the ``auto_exit_blocked`` gate (no point reconciling $0.001 of BTC).
  - **Reporting** : dust positions are always included in portfolio reports so
    they remain visible and auditable.

Usage::

    from bot.dust_position_filter import DustPositionFilter, is_dust_position

    # Simple check
    if is_dust_position("BTC-USD", qty=0.00000001, price_usd=50000.0):
        ...

    # Batch filter
    filt = DustPositionFilter()
    active   = filt.filter_for_execution(positions, prices)
    recon    = filt.filter_for_reconciliation(positions, prices)
    report   = filt.get_dust_report(positions, prices)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.dust_position_filter")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENV_DUST_THRESHOLD = "NIJA_DUST_THRESHOLD_USD"
_ENV_MICRO_THRESHOLD = "NIJA_MICRO_THRESHOLD_USD"
_DEFAULT_DUST_USD = 1.00    # positions below this are dust
_DEFAULT_MICRO_USD = 5.00   # positions between dust and micro need special handling


def _env_float(key: str, default: float) -> float:
    try:
        val = float(os.environ.get(key, default))
        return val if val == val and val >= 0 else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DustRecord:
    """A single dust position entry."""
    symbol: str
    quantity: float
    price_usd: float
    value_usd: float
    threshold_usd: float
    is_micro: bool = False       # between dust and micro thresholds
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DustFilterReport:
    """Summary from a :class:`DustPositionFilter` run."""
    total_positions: int = 0
    dust_count: int = 0
    micro_count: int = 0
    active_count: int = 0
    dust_total_usd: float = 0.0
    active_total_usd: float = 0.0
    threshold_usd: float = _DEFAULT_DUST_USD
    dust_positions: List[DustRecord] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Main filter class
# ---------------------------------------------------------------------------

class DustPositionFilter:
    """Identify and filter dust positions across the portfolio.

    Args:
        dust_threshold_usd: Positions with USD value below this are dust.
            Reads ``NIJA_DUST_THRESHOLD_USD`` from environment if not supplied.
        micro_threshold_usd: Positions between dust and this value are flagged
            as "micro" for reporting.  Reads ``NIJA_MICRO_THRESHOLD_USD``.
    """

    def __init__(
        self,
        dust_threshold_usd: Optional[float] = None,
        micro_threshold_usd: Optional[float] = None,
    ) -> None:
        self.dust_threshold_usd = (
            dust_threshold_usd
            if dust_threshold_usd is not None
            else _env_float(_ENV_DUST_THRESHOLD, _DEFAULT_DUST_USD)
        )
        self.micro_threshold_usd = (
            micro_threshold_usd
            if micro_threshold_usd is not None
            else _env_float(_ENV_MICRO_THRESHOLD, _DEFAULT_MICRO_USD)
        )

    # ------------------------------------------------------------------
    # Core predicate
    # ------------------------------------------------------------------

    def is_dust(self, symbol: str, quantity: float, price_usd: float) -> bool:
        """Return True if the position's USD value is below the dust threshold.

        Args:
            symbol: Trading symbol (informational only).
            quantity: Base-asset quantity.
            price_usd: Current USD price per unit.

        Returns:
            True when ``quantity * price_usd < dust_threshold_usd``.
        """
        if quantity <= 0 or price_usd < 0:
            return True   # zero/negative quantity is always dust
        value_usd = quantity * price_usd
        return value_usd < self.dust_threshold_usd

    def is_dust_position(self, position: Dict[str, Any], price_usd: Optional[float] = None) -> bool:
        """Return True if a position dict represents a dust position.

        Tries (in order):
          1. ``quantity × price_usd`` if *price_usd* is supplied.
          2. ``quantity × last_broker_snapshot_price`` from the position dict.
          3. ``size_usd`` stored in the position dict.

        Args:
            position: Position dict with ``quantity``, ``size_usd``, etc.
            price_usd: Current market price (optional).
        """
        qty = float(position.get("quantity") or 0)
        if qty <= 0:
            return True

        if price_usd and price_usd > 0:
            return qty * price_usd < self.dust_threshold_usd

        snapshot_price = float(position.get("last_broker_snapshot_price") or 0)
        if snapshot_price > 0:
            return qty * snapshot_price < self.dust_threshold_usd

        size_usd = float(position.get("size_usd") or 0)
        if size_usd > 0:
            return size_usd < self.dust_threshold_usd

        # Cannot determine value — treat tiny quantities as dust
        return qty < 1e-7

    # ------------------------------------------------------------------
    # Batch filters
    # ------------------------------------------------------------------

    def filter_for_execution(
        self,
        positions: Dict[str, Dict[str, Any]],
        prices: Dict[str, float],
    ) -> Dict[str, Dict[str, Any]]:
        """Return only non-dust positions eligible for order execution.

        Dust positions are silently excluded; no exceptions are raised.

        Args:
            positions: Mapping of symbol → position dict.
            prices: Current USD prices per symbol.

        Returns:
            Filtered positions dict (dust entries removed).
        """
        active: Dict[str, Dict[str, Any]] = {}
        dust_count = 0
        for symbol, pos in positions.items():
            price = prices.get(symbol, 0.0)
            if self.is_dust_position(pos, price):
                dust_count += 1
                logger.debug(
                    "DUST_FILTER_EXEC_EXCLUDED symbol=%s qty=%.8f price=%.4f threshold=%.2f",
                    symbol,
                    float(pos.get("quantity") or 0),
                    price,
                    self.dust_threshold_usd,
                )
            else:
                active[symbol] = pos
        if dust_count:
            logger.info(
                "DUST_FILTER_EXEC_SUMMARY excluded=%d total=%d threshold=$%.2f",
                dust_count, len(positions), self.dust_threshold_usd,
            )
        return active

    def filter_for_reconciliation(
        self,
        positions: Dict[str, Dict[str, Any]],
        prices: Dict[str, float],
    ) -> Dict[str, Dict[str, Any]]:
        """Return positions eligible for cost-basis reconciliation.

        Dust positions are excluded — there is no value in spending API quota
        reconciling positions worth less than the dust threshold.

        Args:
            positions: Mapping of symbol → position dict.
            prices: Current USD prices per symbol.

        Returns:
            Filtered positions dict.
        """
        active: Dict[str, Dict[str, Any]] = {}
        dust_count = 0
        for symbol, pos in positions.items():
            price = prices.get(symbol, 0.0)
            if self.is_dust_position(pos, price):
                dust_count += 1
                logger.debug(
                    "DUST_FILTER_RECON_EXCLUDED symbol=%s threshold=$%.2f",
                    symbol, self.dust_threshold_usd,
                )
            else:
                active[symbol] = pos
        if dust_count:
            logger.info(
                "DUST_FILTER_RECON_SUMMARY excluded=%d total=%d threshold=$%.2f",
                dust_count, len(positions), self.dust_threshold_usd,
            )
        return active

    def get_dust_report(
        self,
        positions: Dict[str, Dict[str, Any]],
        prices: Dict[str, float],
    ) -> DustFilterReport:
        """Build a full dust position report (for dashboards / audit logs).

        All positions are inspected; dust positions are recorded in detail.
        This never excludes anything — it is read-only reporting.

        Args:
            positions: Mapping of symbol → position dict.
            prices: Current USD prices per symbol.

        Returns:
            :class:`DustFilterReport`.
        """
        report = DustFilterReport(
            total_positions=len(positions),
            threshold_usd=self.dust_threshold_usd,
        )
        for symbol, pos in positions.items():
            price = prices.get(symbol, 0.0)
            qty = float(pos.get("quantity") or 0)
            value_usd = qty * price if price > 0 else float(pos.get("size_usd") or 0)

            if self.is_dust_position(pos, price if price > 0 else None):
                is_micro = value_usd >= self.dust_threshold_usd and value_usd < self.micro_threshold_usd
                record = DustRecord(
                    symbol=symbol,
                    quantity=qty,
                    price_usd=price,
                    value_usd=value_usd,
                    threshold_usd=self.dust_threshold_usd,
                    is_micro=is_micro,
                )
                report.dust_positions.append(record)
                report.dust_total_usd += value_usd
                if is_micro:
                    report.micro_count += 1
                else:
                    report.dust_count += 1
            else:
                report.active_count += 1
                report.active_total_usd += value_usd

        return report

    # ------------------------------------------------------------------
    # Convenience class method
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "DustPositionFilter":
        """Create a filter instance using current environment variable values."""
        return cls(
            dust_threshold_usd=_env_float(_ENV_DUST_THRESHOLD, _DEFAULT_DUST_USD),
            micro_threshold_usd=_env_float(_ENV_MICRO_THRESHOLD, _DEFAULT_MICRO_USD),
        )


class DustPositionManager:
    """Classify positions and apply dust exclusion flags."""

    def __init__(self, threshold_usd: Optional[float] = None) -> None:
        self.threshold_usd = (
            float(threshold_usd)
            if threshold_usd is not None
            else _env_float(_ENV_DUST_THRESHOLD, _DEFAULT_DUST_USD)
        )
        self._filter = DustPositionFilter(dust_threshold_usd=self.threshold_usd)

    def classify(
        self,
        symbol: str,
        position: Dict[str, Any],
        price_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        is_dust = self._filter.is_dust_position(position, price_usd=price_usd)
        value_usd = float(position.get("size_usd") or 0.0)
        if price_usd and float(position.get("quantity") or 0.0) > 0:
            value_usd = float(position.get("quantity") or 0.0) * float(price_usd)
        payload = {
            "classification": "DUST" if is_dust else "ACTIVE",
            "position_value_usd": value_usd,
            "dust_threshold_usd": self.threshold_usd,
            "exclude_from_reconciliation": bool(is_dust),
            "exclude_from_auto_exit": bool(is_dust),
            "exclude_from_strategy": bool(is_dust),
            "exclude_from_position_limit": bool(is_dust),
        }
        if is_dust:
            logger.info(
                "DUST_CLASSIFIED symbol=%s classification=DUST position_value_usd=%.8f threshold_usd=%.2f",
                symbol,
                value_usd,
                self.threshold_usd,
            )
        return payload

    def apply_to_position(
        self,
        symbol: str,
        position: Dict[str, Any],
        price_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        enriched = dict(position)
        enriched.update(self.classify(symbol, enriched, price_usd=price_usd))
        return enriched


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def is_dust_position(
    symbol: str,
    qty: float,
    price_usd: float,
    threshold_usd: Optional[float] = None,
) -> bool:
    """Return True if *qty × price_usd* is below the dust threshold.

    Args:
        symbol: Trading symbol (informational).
        qty: Base-asset quantity held.
        price_usd: Current USD price per unit.
        threshold_usd: Override threshold (reads env if not supplied).

    Returns:
        bool
    """
    t = threshold_usd if threshold_usd is not None else _env_float(_ENV_DUST_THRESHOLD, _DEFAULT_DUST_USD)
    filt = DustPositionFilter(dust_threshold_usd=t)
    return filt.is_dust(symbol, qty, price_usd)


def get_active_positions(
    positions: Dict[str, Dict[str, Any]],
    prices: Dict[str, float],
    for_reconciliation: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Filter *positions* dict, removing dust entries.

    Args:
        positions: Full position map.
        prices: Current USD prices.
        for_reconciliation: If True, use reconciliation filter (excludes dust
            from cost-basis work); otherwise uses execution filter.

    Returns:
        Filtered positions dict.
    """
    filt = DustPositionFilter.from_env()
    if for_reconciliation:
        return filt.filter_for_reconciliation(positions, prices)
    return filt.filter_for_execution(positions, prices)


__all__ = [
    "DustPositionFilter",
    "DustPositionManager",
    "DustRecord",
    "DustFilterReport",
    "is_dust_position",
    "get_active_positions",
]
