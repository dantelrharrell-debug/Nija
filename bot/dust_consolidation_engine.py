"""
NIJA Dust Consolidation Engine
================================
Identifies micro-balance ("dust") positions across the live portfolio and emits
actionable consolidation recommendations so that capital is never silently bled
away by fee drag on positions too small to trade profitably.

What counts as "dust"?
-----------------------
Any open position whose current mark-to-market USD value is below the configured
``dust_threshold_usd`` (default $1.00).  Additionally, positions between
``dust_threshold_usd`` and ``micro_threshold_usd`` (default $5.00) are flagged
as "micro" – they are not dust yet, but they are at risk of sliding into dust
territory and should be monitored closely.

Consolidation Strategies
------------------------
CLOSE:    Dust is too small to roll elsewhere; emit a market-close order rec.
MERGE:    Two or more dust positions share the same base currency and can be
          merged into a single position on the highest-quality asset.
SELL_TO_QUOTE: The base currency has no tradeable pair but can be swapped back
          to the account quote currency (USD/USDC) via a direct convert order.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │              DustConsolidationEngine                         │
  │                                                              │
  │  scan_portfolio(positions)                                   │
  │    → identify_dust(positions) → List[DustEntry]             │
  │    → group_by_base_currency(dust) → Dict[str, List]         │
  │    → build_recommendations() → List[ConsolidationRec]       │
  │                                                              │
  │  get_consolidation_report() → ConsolidationReport           │
  │    (full snapshot: dust count, total USD at risk,            │
  │     recommended actions, historical summary)                 │
  └──────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.dust_consolidation_engine import get_dust_consolidation_engine

    engine = get_dust_consolidation_engine()

    # Called every trading cycle (or on demand)
    report = engine.scan_portfolio(positions)

    for rec in report.recommendations:
        if rec.action == ConsolidationAction.CLOSE:
            broker.close_position(rec.symbol)
        elif rec.action == ConsolidationAction.MERGE:
            # Engine returns the target symbol to consolidate into
            broker.close_position(rec.symbol)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.dust_consolidation")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ConsolidationAction(str, Enum):
    """Recommended action for a dust or micro position."""
    CLOSE = "CLOSE"              # Market-close immediately
    MERGE = "MERGE"              # Roll into a sibling position
    SELL_TO_QUOTE = "SELL_TO_QUOTE"  # Convert base → quote currency
    MONITOR = "MONITOR"          # Micro balance – watch but don't act yet


class DustSeverity(str, Enum):
    """Severity classification for a position's dust risk."""
    DUST = "DUST"        # Below dust_threshold_usd – act now
    MICRO = "MICRO"      # Below micro_threshold_usd – watch closely
    CLEAN = "CLEAN"      # Above micro threshold – no action needed


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DustEntry:
    """Detailed record of a single dust or micro position."""
    symbol: str
    base_currency: str       # e.g. "BTC" from "BTC-USD"
    quote_currency: str      # e.g. "USD"
    size_usd: float          # Current mark-to-market value in USD
    quantity: float          # Units held
    pnl_pct: float           # Unrealised P&L as a fraction (0.05 = +5 %)
    entry_price: float       # Original fill price
    current_price: float     # Latest mid price
    age_hours: float         # How long the position has been open
    severity: DustSeverity
    reason: str              # Human-readable reason for classification


@dataclass
class ConsolidationRec:
    """A single consolidation recommendation."""
    symbol: str
    action: ConsolidationAction
    size_usd: float
    pnl_pct: float
    severity: DustSeverity
    merge_target: Optional[str]  # Populated when action == MERGE
    reason: str
    priority: int            # 1 = highest priority (act first)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ConsolidationReport:
    """Full portfolio dust consolidation snapshot."""
    scan_timestamp: str
    total_positions_scanned: int
    dust_count: int          # Positions with DUST severity
    micro_count: int         # Positions with MICRO severity
    total_dust_usd: float    # Sum of USD value of DUST positions
    total_micro_usd: float   # Sum of USD value of MICRO positions
    recommendations: List[ConsolidationRec]
    dust_entries: List[DustEntry]
    # Rolling session totals
    session_dust_freed_usd: float = 0.0
    session_consolidations: int = 0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DustConsolidationConfig:
    """Tunable parameters for the engine."""
    dust_threshold_usd: float = 1.00   # Hard dust line
    micro_threshold_usd: float = 5.00  # Soft micro-watch line
    min_merge_sibling_usd: float = 10.00  # Sibling must be at least this large to accept a merge
    max_age_hours_for_merge: float = 168.0  # 7 days; older micro = close, not merge
    auto_close_dust: bool = True       # Emit CLOSE recs automatically for DUST
    auto_monitor_micro: bool = True    # Emit MONITOR recs for MICRO
    log_clean_positions: bool = False  # Set True for verbose debugging


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class DustConsolidationEngine:
    """
    Scans an open-position list for dust and micro balances and produces
    prioritised consolidation recommendations.

    Thread-safe; designed as a singleton (use ``get_dust_consolidation_engine()``).
    """

    def __init__(self, config: Optional[DustConsolidationConfig] = None) -> None:
        self._config = config or DustConsolidationConfig()
        self._lock = threading.Lock()

        # Session-level accumulators
        self._session_dust_freed_usd: float = 0.0
        self._session_consolidations: int = 0
        self._last_report: Optional[ConsolidationReport] = None

        logger.info("🧹 DustConsolidationEngine initialised")
        logger.info("   dust_threshold  : $%.2f USD", self._config.dust_threshold_usd)
        logger.info("   micro_threshold : $%.2f USD", self._config.micro_threshold_usd)
        logger.info("   auto_close_dust : %s", self._config.auto_close_dust)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_portfolio(self, positions: List[Dict]) -> ConsolidationReport:
        """
        Scan all open positions and return a full consolidation report.

        Args:
            positions: List of position dicts.  Each dict must contain at
                       minimum: ``symbol`` and one of ``size_usd`` / ``usd_value``.
                       Optional keys: ``quantity``, ``pnl_pct``, ``entry_price``,
                       ``current_price``, ``age_hours``.

        Returns:
            ConsolidationReport with dust entries and recommendations.
        """
        with self._lock:
            dust_entries, micro_entries, clean_count = self._classify_positions(positions)
            all_flagged = dust_entries + micro_entries

            recs = self._build_recommendations(dust_entries, micro_entries, positions)

            total_dust_usd = sum(e.size_usd for e in dust_entries)
            total_micro_usd = sum(e.size_usd for e in micro_entries)

            report = ConsolidationReport(
                scan_timestamp=datetime.now(timezone.utc).isoformat(),
                total_positions_scanned=len(positions),
                dust_count=len(dust_entries),
                micro_count=len(micro_entries),
                total_dust_usd=total_dust_usd,
                total_micro_usd=total_micro_usd,
                recommendations=recs,
                dust_entries=all_flagged,
                session_dust_freed_usd=self._session_dust_freed_usd,
                session_consolidations=self._session_consolidations,
            )

            self._last_report = report
            self._log_report(report)
            return report

    def record_consolidation_executed(self, symbol: str, freed_usd: float) -> None:
        """
        Call this after a recommended consolidation has been acted upon so that
        session-level totals stay accurate.

        Args:
            symbol: The symbol that was closed / merged.
            freed_usd: The USD value recovered (or released) by the action.
        """
        with self._lock:
            self._session_dust_freed_usd += freed_usd
            self._session_consolidations += 1
            logger.info(
                "✅ Consolidation recorded: %s freed $%.2f  (session total: $%.2f, %d actions)",
                symbol, freed_usd, self._session_dust_freed_usd, self._session_consolidations,
            )

    def get_last_report(self) -> Optional[ConsolidationReport]:
        """Return the most recent consolidation report, or None if no scan yet."""
        return self._last_report

    def get_session_summary(self) -> Dict:
        """Return lightweight session statistics for dashboards."""
        return {
            "session_dust_freed_usd": self._session_dust_freed_usd,
            "session_consolidations": self._session_consolidations,
            "last_scan": self._last_report.scan_timestamp if self._last_report else None,
            "dust_threshold_usd": self._config.dust_threshold_usd,
            "micro_threshold_usd": self._config.micro_threshold_usd,
        }

    def update_config(self, **kwargs) -> None:
        """
        Update configuration parameters at runtime.

        Accepted keyword arguments match fields of DustConsolidationConfig:
        dust_threshold_usd, micro_threshold_usd, auto_close_dust, etc.
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)
                    logger.info("⚙️  DustConsolidationEngine config updated: %s = %s", key, value)
                else:
                    logger.warning("⚠️  Unknown config key ignored: %s", key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify_positions(
        self, positions: List[Dict]
    ) -> Tuple[List[DustEntry], List[DustEntry], int]:
        """Classify positions into dust, micro, and clean buckets."""
        dust: List[DustEntry] = []
        micro: List[DustEntry] = []
        clean_count = 0

        for pos in positions:
            entry = self._make_dust_entry(pos)
            if entry.severity == DustSeverity.DUST:
                dust.append(entry)
            elif entry.severity == DustSeverity.MICRO:
                micro.append(entry)
            else:
                clean_count += 1
                if self._config.log_clean_positions:
                    logger.debug("✔  %s  $%.2f – CLEAN", entry.symbol, entry.size_usd)

        return dust, micro, clean_count

    def _make_dust_entry(self, pos: Dict) -> DustEntry:
        """Convert a raw position dict into a typed DustEntry."""
        symbol = pos.get("symbol", "UNKNOWN")
        size_usd = float(pos.get("size_usd", 0) or pos.get("usd_value", 0))
        quantity = float(pos.get("quantity", 0) or pos.get("size", 0))
        pnl_pct = float(pos.get("pnl_pct", 0) or pos.get("unrealized_pnl_pct", 0))
        entry_price = float(pos.get("entry_price", 0) or pos.get("avg_entry_price", 0))
        current_price = float(pos.get("current_price", 0) or pos.get("mark_price", 0))
        age_hours = float(pos.get("age_hours", 0))

        # Derive base / quote from symbol (e.g. "BTC-USD" → "BTC", "USD")
        parts = symbol.split("-")
        base_currency = parts[0] if len(parts) >= 1 else symbol
        quote_currency = parts[1] if len(parts) >= 2 else "USD"

        if size_usd < self._config.dust_threshold_usd:
            severity = DustSeverity.DUST
            reason = (
                f"Size ${size_usd:.4f} is below dust threshold ${self._config.dust_threshold_usd:.2f}"
            )
        elif size_usd < self._config.micro_threshold_usd:
            severity = DustSeverity.MICRO
            reason = (
                f"Size ${size_usd:.2f} is below micro threshold ${self._config.micro_threshold_usd:.2f}"
            )
        else:
            severity = DustSeverity.CLEAN
            reason = "Position size is healthy"

        return DustEntry(
            symbol=symbol,
            base_currency=base_currency,
            quote_currency=quote_currency,
            size_usd=size_usd,
            quantity=quantity,
            pnl_pct=pnl_pct,
            entry_price=entry_price,
            current_price=current_price,
            age_hours=age_hours,
            severity=severity,
            reason=reason,
        )

    def _build_recommendations(
        self,
        dust_entries: List[DustEntry],
        micro_entries: List[DustEntry],
        all_positions: List[Dict],
    ) -> List[ConsolidationRec]:
        """Generate prioritised recommendations for all flagged entries."""
        recs: List[ConsolidationRec] = []

        # Build a lookup of non-dust positions by base currency for merge candidates
        sibling_map: Dict[str, List[Dict]] = defaultdict(list)
        for pos in all_positions:
            sym = pos.get("symbol", "")
            size_usd = float(pos.get("size_usd", 0) or pos.get("usd_value", 0))
            if size_usd >= self._config.min_merge_sibling_usd:
                base = sym.split("-")[0] if "-" in sym else sym
                sibling_map[base].append(pos)

        priority = 1

        # -- DUST entries: highest priority --
        if self._config.auto_close_dust:
            for entry in sorted(dust_entries, key=lambda e: e.size_usd):
                action, target = self._select_action(entry, sibling_map)
                recs.append(ConsolidationRec(
                    symbol=entry.symbol,
                    action=action,
                    size_usd=entry.size_usd,
                    pnl_pct=entry.pnl_pct,
                    severity=entry.severity,
                    merge_target=target,
                    reason=entry.reason,
                    priority=priority,
                ))
                priority += 1

        # -- MICRO entries: lower priority, MONITOR unless old --
        if self._config.auto_monitor_micro:
            for entry in sorted(micro_entries, key=lambda e: e.size_usd):
                if entry.age_hours > self._config.max_age_hours_for_merge:
                    action = ConsolidationAction.CLOSE
                    reason = (
                        f"{entry.reason}; position age {entry.age_hours:.0f}h "
                        f"exceeds {self._config.max_age_hours_for_merge:.0f}h limit"
                    )
                else:
                    action = ConsolidationAction.MONITOR
                    reason = entry.reason
                recs.append(ConsolidationRec(
                    symbol=entry.symbol,
                    action=action,
                    size_usd=entry.size_usd,
                    pnl_pct=entry.pnl_pct,
                    severity=entry.severity,
                    merge_target=None,
                    reason=reason,
                    priority=priority,
                ))
                priority += 1

        return recs

    def _select_action(
        self, entry: DustEntry, sibling_map: Dict[str, List[Dict]]
    ) -> Tuple[ConsolidationAction, Optional[str]]:
        """Choose the best consolidation action for a single dust entry."""
        siblings = sibling_map.get(entry.base_currency, [])

        # If there is a healthy sibling in the same base currency, merge
        if siblings:
            best_sibling = max(
                siblings,
                key=lambda p: float(p.get("size_usd", 0) or p.get("usd_value", 0)),
            )
            target_sym = best_sibling.get("symbol", "")
            if target_sym and target_sym != entry.symbol:
                return ConsolidationAction.MERGE, target_sym

        # No sibling – just close and let the cash sit as quote currency
        return ConsolidationAction.CLOSE, None

    def _log_report(self, report: ConsolidationReport) -> None:
        """Emit a structured log summary of the scan results."""
        if report.dust_count == 0 and report.micro_count == 0:
            logger.info(
                "✅ Dust scan complete – no dust or micro positions found "
                "(%d positions scanned)", report.total_positions_scanned
            )
            return

        logger.warning(
            "🧹 DUST CONSOLIDATION SCAN: %d dust ($%.2f) | %d micro ($%.2f) "
            "| %d total positions scanned",
            report.dust_count, report.total_dust_usd,
            report.micro_count, report.total_micro_usd,
            report.total_positions_scanned,
        )
        for rec in report.recommendations:
            if rec.action == ConsolidationAction.CLOSE:
                logger.warning(
                    "   ❌ CLOSE  %s  $%.4f  PnL %+.1f%%  – %s",
                    rec.symbol, rec.size_usd, rec.pnl_pct * 100, rec.reason,
                )
            elif rec.action == ConsolidationAction.MERGE:
                logger.warning(
                    "   🔀 MERGE  %s  $%.4f  → %s  – %s",
                    rec.symbol, rec.size_usd, rec.merge_target, rec.reason,
                )
            elif rec.action == ConsolidationAction.SELL_TO_QUOTE:
                logger.warning(
                    "   💱 SELL_TO_QUOTE  %s  $%.4f  – %s",
                    rec.symbol, rec.size_usd, rec.reason,
                )
            else:
                logger.info(
                    "   👁  MONITOR  %s  $%.2f  – %s",
                    rec.symbol, rec.size_usd, rec.reason,
                )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[DustConsolidationEngine] = None
_engine_lock = threading.Lock()


def get_dust_consolidation_engine(
    config: Optional[DustConsolidationConfig] = None,
) -> DustConsolidationEngine:
    """
    Return the process-wide DustConsolidationEngine singleton.

    Thread-safe.  Pass *config* only on the first call; subsequent calls
    ignore it and return the already-created instance.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = DustConsolidationEngine(config)
    return _engine_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    logger.info("=== DustConsolidationEngine self-test ===")

    engine = get_dust_consolidation_engine()

    sample_positions = [
        {"symbol": "BTC-USD",  "size_usd": 150.00, "pnl_pct": 0.03,  "age_hours": 12},
        {"symbol": "ETH-USD",  "size_usd": 3.50,   "pnl_pct": -0.01, "age_hours": 48},
        {"symbol": "DOGE-USD", "size_usd": 0.42,   "pnl_pct": -0.05, "age_hours": 96},
        {"symbol": "SHIB-USD", "size_usd": 0.07,   "pnl_pct": -0.20, "age_hours": 200},
        {"symbol": "SOL-USD",  "size_usd": 4.80,   "pnl_pct": 0.01,  "age_hours": 300},
        {"symbol": "ADA-USD",  "size_usd": 25.00,  "pnl_pct": 0.02,  "age_hours": 6},
    ]

    report = engine.scan_portfolio(sample_positions)

    print("\n=== REPORT SUMMARY ===")
    print(f"  Scanned        : {report.total_positions_scanned} positions")
    print(f"  Dust           : {report.dust_count}  (${report.total_dust_usd:.4f})")
    print(f"  Micro          : {report.micro_count}  (${report.total_micro_usd:.2f})")
    print(f"  Recommendations: {len(report.recommendations)}")
    for r in report.recommendations:
        tgt = f" → {r.merge_target}" if r.merge_target else ""
        print(f"    [{r.priority}] {r.action.value:20s} {r.symbol}{tgt}  ${r.size_usd:.4f}")

    # Simulate recording a consolidation
    engine.record_consolidation_executed("SHIB-USD", 0.07)
    engine.record_consolidation_executed("DOGE-USD", 0.42)

    summary = engine.get_session_summary()
    print("\n=== SESSION SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    logger.info("=== Self-test complete ===")
    sys.exit(0)
