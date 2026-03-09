"""
NIJA Capital Allocation Engine
================================

Enforces a **fixed asset-class allocation** across all capital deployed by
the bot:

  * 20 % → Crypto  (Coinbase, Kraken, Binance)
  * 30 % → Equities (Alpaca, Interactive Brokers)
  * 20 % → Futures  (Interactive Brokers, CME Direct)
  * 30 % → Options  (Interactive Brokers, TD Ameritrade)

The engine answers three key questions for the rest of the system:

1. **How much capital can be deployed in each asset class right now?**
   ``get_available(asset_class)`` returns the USD amount still available
   within the target allocation, given current open-position exposure.

2. **Is a proposed trade within allocation limits?**
   ``approve_trade(asset_class, size_usd)`` returns True/False with a
   reason string.

3. **What is the current allocation health?**
   ``get_report()`` prints a dashboard showing target vs. actual exposure.

Architecture
------------
::

  ┌────────────────────────────────────────────────────────────┐
  │              CapitalAllocationEngine                        │
  │                                                             │
  │  Targets: crypto=20%, equity=30%, futures=20%, options=30% │
  │                                                             │
  │  approve_trade(asset_class, size_usd)                       │
  │  update_exposure(asset_class, delta_usd)                    │
  │  get_available(asset_class) → float                         │
  │  get_report() → str                                         │
  └────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.capital_allocation_engine import (
        get_capital_allocation_engine, AllocationTarget
    )

    engine = get_capital_allocation_engine(total_capital=50_000.0)

    # Before placing a $5 000 crypto trade:
    ok, reason = engine.approve_trade("crypto", 5_000.0)
    if ok:
        engine.update_exposure("crypto", +5_000.0)   # mark as deployed
        # … place trade …
        engine.update_exposure("crypto", -5_000.0)   # release on close

    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nija.capital_allocation_engine")

# ---------------------------------------------------------------------------
# Default allocation targets (must sum to 1.0)
# ---------------------------------------------------------------------------

DEFAULT_ALLOCATIONS: Dict[str, float] = {
    "crypto":   0.20,   # 20 %
    "equity":   0.30,   # 30 %
    "futures":  0.20,   # 20 %
    "options":  0.30,   # 30 %
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AllocationTarget:
    """Per-asset-class allocation target and live exposure tracking."""
    asset_class: str
    target_pct: float           # fraction of total capital (0–1)
    current_exposure_usd: float = 0.0
    total_deployed_usd: float = 0.0     # cumulative; never decremented
    trade_count: int = 0
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def target_usd(self) -> float:
        """Computed at call-time; requires CapitalAllocationEngine._total_capital."""
        # The engine injects this via a closure; left as 0 here as a sentinel
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_class": self.asset_class,
            "target_pct": self.target_pct,
            "current_exposure_usd": self.current_exposure_usd,
            "total_deployed_usd": self.total_deployed_usd,
            "trade_count": self.trade_count,
            "last_updated": self.last_updated,
        }


# ---------------------------------------------------------------------------
# CapitalAllocationEngine
# ---------------------------------------------------------------------------


class CapitalAllocationEngine:
    """
    Enforces fixed asset-class capital allocation.

    Thread-safe; process-wide singleton via ``get_capital_allocation_engine()``.
    """

    def __init__(
        self,
        total_capital: float = 0.0,
        allocations: Optional[Dict[str, float]] = None,
        allow_overflow_pct: float = 0.05,
    ) -> None:
        """
        Parameters
        ----------
        total_capital : float
            Total USD capital under management.  Can be updated later with
            ``set_total_capital()``.
        allocations : dict, optional
            Override the default 20/30/20/30 split.  Keys must be one of
            ``{"crypto", "equity", "futures", "options"}``.  Values are
            fractions (not percentages) and must sum to 1.0.
        allow_overflow_pct : float
            Fractional slack allowed above the target before a trade is
            rejected (default 5 %).
        """
        self._lock = threading.RLock()
        self._total_capital: float = max(0.0, total_capital)
        self._allow_overflow_pct: float = allow_overflow_pct

        raw_allocs = allocations if allocations is not None else DEFAULT_ALLOCATIONS
        self._validate_allocations(raw_allocs)

        self._targets: Dict[str, AllocationTarget] = {
            ac: AllocationTarget(asset_class=ac, target_pct=pct)
            for ac, pct in raw_allocs.items()
        }

        logger.info(
            "CapitalAllocationEngine initialised | capital=$%.2f | "
            "crypto=%.0f%% equity=%.0f%% futures=%.0f%% options=%.0f%%",
            self._total_capital,
            raw_allocs.get("crypto", 0) * 100,
            raw_allocs.get("equity", 0) * 100,
            raw_allocs.get("futures", 0) * 100,
            raw_allocs.get("options", 0) * 100,
        )

    # ------------------------------------------------------------------
    # Capital management
    # ------------------------------------------------------------------

    def set_total_capital(self, total_capital: float) -> None:
        """Update the total capital under management."""
        with self._lock:
            self._total_capital = max(0.0, total_capital)
            logger.info("Total capital updated to $%.2f", self._total_capital)

    def get_total_capital(self) -> float:
        """Return the current total capital."""
        with self._lock:
            return self._total_capital

    # ------------------------------------------------------------------
    # Allocation queries
    # ------------------------------------------------------------------

    def get_target_usd(self, asset_class: str) -> float:
        """Return the target USD allocation for *asset_class*."""
        ac = self._normalize(asset_class)
        with self._lock:
            if ac not in self._targets:
                return 0.0
            return self._total_capital * self._targets[ac].target_pct

    def get_current_exposure(self, asset_class: str) -> float:
        """Return current open exposure in USD for *asset_class*."""
        ac = self._normalize(asset_class)
        with self._lock:
            if ac not in self._targets:
                return 0.0
            return self._targets[ac].current_exposure_usd

    def get_available(self, asset_class: str) -> float:
        """
        Return USD headroom remaining within the allocation for *asset_class*.

        A positive value means more capital can be deployed; zero or negative
        means the allocation is full.
        """
        ac = self._normalize(asset_class)
        with self._lock:
            if ac not in self._targets:
                return 0.0
            t = self._targets[ac]
            ceiling = self._total_capital * (t.target_pct + self._allow_overflow_pct)
            return max(0.0, ceiling - t.current_exposure_usd)

    def get_allocation_summary(self) -> Dict[str, Dict[str, float]]:
        """
        Return a dict of dicts with allocation details per asset class:

        .. code-block:: python

            {
                "crypto": {
                    "target_pct": 20.0,
                    "target_usd": 10_000.0,
                    "exposure_usd": 4_500.0,
                    "available_usd": 6_000.0,
                    "utilisation_pct": 45.0,
                },
                ...
            }
        """
        with self._lock:
            result: Dict[str, Dict[str, float]] = {}
            for ac, t in self._targets.items():
                target_usd = self._total_capital * t.target_pct
                ceiling = self._total_capital * (t.target_pct + self._allow_overflow_pct)
                available = max(0.0, ceiling - t.current_exposure_usd)
                utilisation = (
                    (t.current_exposure_usd / target_usd * 100)
                    if target_usd > 0 else 0.0
                )
                result[ac] = {
                    "target_pct": t.target_pct * 100,
                    "target_usd": target_usd,
                    "exposure_usd": t.current_exposure_usd,
                    "available_usd": available,
                    "utilisation_pct": utilisation,
                }
            return result

    # ------------------------------------------------------------------
    # Trade approval
    # ------------------------------------------------------------------

    def approve_trade(
        self, asset_class: str, size_usd: float
    ) -> Tuple[bool, str]:
        """
        Check whether a trade of *size_usd* is within allocation limits.

        Returns ``(approved: bool, reason: str)``.
        """
        if size_usd <= 0:
            return False, f"Invalid trade size: ${size_usd:.2f}"

        ac = self._normalize(asset_class)
        with self._lock:
            if ac not in self._targets:
                return False, f"Unknown asset class: '{asset_class}'"

            available = self.get_available(ac)
            if size_usd > available:
                t = self._targets[ac]
                target_usd = self._total_capital * t.target_pct
                return False, (
                    f"Allocation exceeded for {ac}: "
                    f"requested ${size_usd:.2f}, "
                    f"available ${available:.2f} "
                    f"(target ${target_usd:.2f}, "
                    f"exposure ${t.current_exposure_usd:.2f})"
                )

            return True, f"Approved: ${size_usd:.2f} within {ac} allocation"

    # ------------------------------------------------------------------
    # Exposure tracking
    # ------------------------------------------------------------------

    def update_exposure(self, asset_class: str, delta_usd: float) -> float:
        """
        Adjust live exposure for *asset_class* by *delta_usd*.

        Pass a **positive** value when opening a position and a **negative**
        value when closing it.

        Returns the new exposure for the asset class.
        """
        ac = self._normalize(asset_class)
        with self._lock:
            if ac not in self._targets:
                logger.warning("update_exposure: unknown asset class '%s'", asset_class)
                return 0.0

            t = self._targets[ac]
            t.current_exposure_usd = max(0.0, t.current_exposure_usd + delta_usd)
            t.last_updated = datetime.now(timezone.utc).isoformat()

            if delta_usd > 0:
                t.total_deployed_usd += delta_usd
                t.trade_count += 1

            logger.debug(
                "Exposure update [%s]: delta=$%.2f  new_exposure=$%.2f",
                ac, delta_usd, t.current_exposure_usd,
            )
            return t.current_exposure_usd

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Generate a human-readable allocation report."""
        summary = self.get_allocation_summary()

        lines = [
            "=" * 70,
            "  NIJA CAPITAL ALLOCATION ENGINE — PORTFOLIO ALLOCATION",
            "=" * 70,
            f"  Total Capital  : ${self._total_capital:>14,.2f}",
            "",
            f"  {'Asset Class':<14} {'Target':>8} {'Target $':>12} "
            f"{'Exposure $':>12} {'Available $':>12} {'Util %':>7}",
            "-" * 70,
        ]

        total_exposure = 0.0
        for ac in ("crypto", "equity", "futures", "options"):
            if ac not in summary:
                continue
            s = summary[ac]
            bar = "▓" * int(s["utilisation_pct"] / 10) + "░" * (10 - int(s["utilisation_pct"] / 10))
            lines.append(
                f"  {ac:<14} {s['target_pct']:>7.0f}% "
                f"${s['target_usd']:>11,.2f} "
                f"${s['exposure_usd']:>11,.2f} "
                f"${s['available_usd']:>11,.2f} "
                f"{s['utilisation_pct']:>6.1f}%  {bar}"
            )
            total_exposure += s["exposure_usd"]

        utilisation_total = (
            (total_exposure / self._total_capital * 100)
            if self._total_capital > 0 else 0.0
        )
        lines += [
            "-" * 70,
            f"  {'TOTAL':<14} {'100':>7}% "
            f"${self._total_capital:>11,.2f} "
            f"${total_exposure:>11,.2f} "
            f"${max(0, self._total_capital - total_exposure):>11,.2f} "
            f"{utilisation_total:>6.1f}%",
            "=" * 70,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(asset_class: str) -> str:
        """Normalise asset class to lowercase key."""
        return asset_class.strip().lower()

    @staticmethod
    def _validate_allocations(allocs: Dict[str, float]) -> None:
        total = sum(allocs.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Allocations must sum to 1.0, got {total:.4f}. "
                f"Received: {allocs}"
            )
        for ac, pct in allocs.items():
            if not 0.0 <= pct <= 1.0:
                raise ValueError(
                    f"Allocation for '{ac}' must be between 0 and 1, got {pct}"
                )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[CapitalAllocationEngine] = None
_instance_lock = threading.Lock()


def get_capital_allocation_engine(
    total_capital: float = 0.0,
    allocations: Optional[Dict[str, float]] = None,
    allow_overflow_pct: float = 0.05,
) -> CapitalAllocationEngine:
    """
    Return the process-wide :class:`CapitalAllocationEngine` singleton.

    The *total_capital*, *allocations*, and *allow_overflow_pct* parameters
    are only applied on **first call** when the singleton is created.
    Subsequent calls with different parameters are ignored; use
    ``engine.set_total_capital()`` to update capital after creation.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CapitalAllocationEngine(
                    total_capital=total_capital,
                    allocations=allocations,
                    allow_overflow_pct=allow_overflow_pct,
                )
    return _instance


__all__ = [
    "DEFAULT_ALLOCATIONS",
    "AllocationTarget",
    "CapitalAllocationEngine",
    "get_capital_allocation_engine",
]

# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    engine = get_capital_allocation_engine(total_capital=100_000.0)
    print(engine.get_report())

    # Approve a crypto trade
    ok, reason = engine.approve_trade("crypto", 5_000.0)
    print(f"\nApprove $5k crypto trade: {ok} — {reason}")

    engine.update_exposure("crypto", +5_000.0)
    engine.update_exposure("equity", +20_000.0)
    engine.update_exposure("futures", +8_000.0)
    engine.update_exposure("options", +15_000.0)

    print("\nAfter exposure updates:")
    print(engine.get_report())

    # Try to over-allocate crypto
    ok, reason = engine.approve_trade("crypto", 20_000.0)
    print(f"\nApprove $20k crypto trade: {ok} — {reason}")
