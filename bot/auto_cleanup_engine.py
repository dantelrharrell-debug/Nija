"""
NIJA Auto-Cleanup Engine
=========================
One-step callable that eliminates dust and merges small positions into either
USDT (quote currency) or the portfolio's best-performing asset.

Pipeline (called once per cleanup cycle):
  1. **Classify**  – scan all open positions with DustConsolidationEngine and tag
     each as DUST (< dust_threshold_usd) or MICRO (< micro_threshold_usd).
  2. **Dust liquidation** – market-sell every DUST position back to USDT.
  3. **Micro merge** – for each MICRO position pick the best available target:
       a. Best-performing asset (highest risk-adjusted PnL %) that already has
          an open position and is above the micro threshold.
       b. Fall back to USDT liquidation when no worthy merge target exists or
          when the merge would violate minimum order constraints.
  4. **Report** – return a structured ``CleanupResult`` with full audit trail.

Usage (one-liner from trading_strategy.py):
    from bot.auto_cleanup_engine import get_auto_cleanup_engine
    result = get_auto_cleanup_engine().run(broker, positions, portfolio_value_usd)

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────────┐
  │                     AutoCleanupEngine                            │
  │                                                                  │
  │  run(broker, positions, portfolio_value)                         │
  │    1. DustConsolidationEngine.scan_portfolio(positions)          │
  │    2. _liquidate_dust(broker, dust_entries)  → to USDT          │
  │    3. _merge_micro(broker, micro_entries, best_asset)            │
  │         ├─ _rank_assets(positions)  → best-performing symbol    │
  │         └─ broker.place_market_order(target, side='buy')        │
  └──────────────────────────────────────────────────────────────────┘

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.auto_cleanup")

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

DUST_THRESHOLD_USD: float = 2.0    # Positions < $2 → immediate USDT liquidation
MICRO_THRESHOLD_USD: float = 10.0  # Positions $2-$10 → merge or liquidate
EXCHANGE_MIN_ORDER_USD: float = 1.0  # Skip if sell proceeds would be < $1

# Best-asset ranking weights (higher score = better merge candidate)
_W_PNL = 0.5          # Weight for unrealised P&L percentage
_W_SIZE = 0.3         # Weight for position size (larger = more liquid merge target)
_W_AGE_PENALTY = 0.2  # Penalty for very old positions (> 72 h) that might be stale


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CleanupAction:
    """Record of a single cleanup action taken."""
    symbol: str
    action: str                 # "DUST_LIQUIDATE" | "MICRO_MERGE" | "MICRO_LIQUIDATE" | "SKIP"
    size_usd: float
    quantity: float
    merge_target: Optional[str] # Filled only for MICRO_MERGE
    success: bool
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CleanupResult:
    """Full result returned by AutoCleanupEngine.run()."""
    run_timestamp: str
    total_positions_scanned: int
    dust_found: int
    micro_found: int
    dust_liquidated: int
    micro_merged: int
    micro_liquidated: int
    total_usd_recovered: float
    actions: List[CleanupAction] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    def summary(self) -> str:
        total_actioned = self.dust_liquidated + self.micro_merged + self.micro_liquidated
        return (
            f"AutoCleanup: scanned={self.total_positions_scanned} "
            f"dust={self.dust_found} micro={self.micro_found} "
            f"actioned={total_actioned} recovered=${self.total_usd_recovered:.4f}"
        )


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class AutoCleanupEngine:
    """
    Single-call auto-cleanup engine for dust liquidation and micro-position
    consolidation.

    Parameters
    ----------
    dust_threshold_usd:
        Positions below this value (USD) are considered dust and are
        immediately market-sold back to USDT.
    micro_threshold_usd:
        Positions between *dust_threshold_usd* and this value are treated as
        "micro" and are merged into the best-performing open position (or
        liquidated to USDT when no good merge target is available).
    dry_run:
        When *True* the engine logs every action it would take but does **not**
        call any broker methods.  Useful for back-testing and unit tests.
    """

    def __init__(
        self,
        dust_threshold_usd: float = DUST_THRESHOLD_USD,
        micro_threshold_usd: float = MICRO_THRESHOLD_USD,
        dry_run: bool = False,
    ) -> None:
        self.dust_threshold_usd = dust_threshold_usd
        self.micro_threshold_usd = micro_threshold_usd
        self.dry_run = dry_run
        self._lock = threading.Lock()

        logger.info(
            "🧹 AutoCleanupEngine initialised | dust<$%.2f | micro<$%.2f | dry_run=%s",
            dust_threshold_usd, micro_threshold_usd, dry_run,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        broker: Any,
        positions: List[Dict],
        portfolio_value_usd: float = 0.0,
    ) -> CleanupResult:
        """
        Execute the full cleanup pipeline in one call.

        Parameters
        ----------
        broker:
            Live broker instance.  Must expose:
              • ``place_market_order(symbol, side, quantity, size_type)``
              • ``get_current_price(symbol)``  (optional – used for validation)
        positions:
            List of open position dicts.  Each entry must have at minimum:
              ``symbol``, ``size_usd`` (or ``usd_value``), ``quantity``.
            Optional but recommended: ``pnl_pct``, ``entry_price``,
            ``current_price``, ``age_hours``.
        portfolio_value_usd:
            Total portfolio value in USD (used for concentration checks).

        Returns
        -------
        CleanupResult
        """
        with self._lock:
            return self._run_pipeline(broker, positions, portfolio_value_usd)

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        broker: Any,
        positions: List[Dict],
        portfolio_value_usd: float,
    ) -> CleanupResult:
        now_ts = datetime.now(timezone.utc).isoformat()
        result = CleanupResult(
            run_timestamp=now_ts,
            total_positions_scanned=len(positions),
            dust_found=0,
            micro_found=0,
            dust_liquidated=0,
            micro_merged=0,
            micro_liquidated=0,
            total_usd_recovered=0.0,
        )

        if not positions:
            logger.info("🧹 AutoCleanup: no positions to scan")
            return result

        logger.info(
            "🧹 AutoCleanup START | %d positions | portfolio=$%.2f",
            len(positions), portfolio_value_usd,
        )

        # ----------------------------------------------------------
        # Step 1: classify positions using DustConsolidationEngine
        # ----------------------------------------------------------
        dust_entries, micro_entries = self._classify(positions)
        result.dust_found = len(dust_entries)
        result.micro_found = len(micro_entries)

        # ----------------------------------------------------------
        # Step 2: build best-asset ranking from ALL positions
        #         (used as merge targets for micro positions)
        # ----------------------------------------------------------
        best_asset = self._rank_best_asset(positions, dust_entries, micro_entries)

        # ----------------------------------------------------------
        # Step 3: liquidate dust → USDT
        # ----------------------------------------------------------
        for entry in dust_entries:
            action = self._liquidate_to_usdt(broker, entry, reason="DUST_LIQUIDATE")
            result.actions.append(action)
            if action.success:
                result.dust_liquidated += 1
                result.total_usd_recovered += action.size_usd

        # ----------------------------------------------------------
        # Step 4: merge / liquidate micro positions
        # ----------------------------------------------------------
        for entry in micro_entries:
            if best_asset and best_asset != entry["symbol"]:
                action = self._merge_into_asset(broker, entry, best_asset)
            else:
                action = self._liquidate_to_usdt(broker, entry, reason="MICRO_LIQUIDATE")

            result.actions.append(action)
            if action.success:
                if action.action == "MICRO_MERGE":
                    result.micro_merged += 1
                else:
                    result.micro_liquidated += 1
                result.total_usd_recovered += action.size_usd

        # ----------------------------------------------------------
        # Step 5: notify consolidation engine of executed actions
        # ----------------------------------------------------------
        self._record_executed(result.actions)

        logger.info("🧹 AutoCleanup DONE | %s", result.summary())
        return result

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(
        self, positions: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Classify positions into (dust, micro) buckets.

        Delegates to DustConsolidationEngine when available; falls back to
        an inline threshold check so the engine works even in isolation.
        """
        try:
            from bot.dust_consolidation_engine import (
                get_dust_consolidation_engine,
                DustConsolidationConfig,
                ConsolidationAction,
            )
            cfg = DustConsolidationConfig(
                dust_threshold_usd=self.dust_threshold_usd,
                micro_threshold_usd=self.micro_threshold_usd,
                auto_close_dust=True,
                auto_monitor_micro=True,
            )
            engine = get_dust_consolidation_engine(cfg)
            report = engine.scan_portfolio(positions)

            # Map engine recommendations back to raw position dicts
            _close_actions = {ConsolidationAction.CLOSE, ConsolidationAction.SELL_TO_QUOTE}
            dust_syms = {r.symbol for r in report.recommendations if r.action in _close_actions}
            micro_syms = {r.symbol for r in report.recommendations
                          if r.action == ConsolidationAction.MONITOR}

            dust = [p for p in positions if p.get("symbol") in dust_syms]
            micro = [p for p in positions if p.get("symbol") in micro_syms]
            return dust, micro

        except Exception as exc:
            logger.warning(
                "⚠️  DustConsolidationEngine unavailable (%s) – using inline thresholds",
                exc,
            )
            # Inline fallback
            dust, micro = [], []
            for pos in positions:
                size = float(pos.get("size_usd") or pos.get("usd_value") or 0)
                if 0 < size < self.dust_threshold_usd:
                    dust.append(pos)
                elif self.dust_threshold_usd <= size < self.micro_threshold_usd:
                    micro.append(pos)
            return dust, micro

    # ------------------------------------------------------------------
    # Best-asset ranking
    # ------------------------------------------------------------------

    def _rank_best_asset(
        self,
        all_positions: List[Dict],
        dust_entries: List[Dict],
        micro_entries: List[Dict],
    ) -> Optional[str]:
        """
        Return the symbol of the best candidate to merge micro-positions into.

        Candidates must:
          - Have size_usd >= micro_threshold_usd (healthy, not being cleaned)
          - Not themselves be a dust or micro entry being cleaned up

        Ranking formula (higher = better):
          score = W_PNL * pnl_pct  +  W_SIZE * log(size_usd)
                  - W_AGE_PENALTY * max(0, age_hours - 72) / 72
        """
        import math

        excluded_symbols = {p.get("symbol") for p in dust_entries + micro_entries}

        candidates: List[Tuple[float, str]] = []
        for pos in all_positions:
            symbol = pos.get("symbol", "")
            if not symbol or symbol in excluded_symbols:
                continue

            size_usd = float(pos.get("size_usd") or pos.get("usd_value") or 0)
            if size_usd < self.micro_threshold_usd:
                continue

            pnl_pct = float(pos.get("pnl_pct") or 0)
            age_hours = float(pos.get("age_hours") or 0)

            age_penalty = max(0.0, age_hours - 72.0) / 72.0

            score = (
                _W_PNL * pnl_pct
                + _W_SIZE * math.log1p(size_usd)
                - _W_AGE_PENALTY * age_penalty
            )
            candidates.append((score, symbol))

        if not candidates:
            return None

        best_score, best_symbol = max(candidates, key=lambda t: t[0])
        logger.info(
            "🎯 Best merge target: %s (score=%.4f)", best_symbol, best_score
        )
        return best_symbol

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_filled(order: Any) -> bool:
        """Return True when *order* reports a terminal-success fill status."""
        return bool(order and order.get("status") in {"filled", "completed", "success"})

    def _get_quantity(self, position: Dict) -> float:
        """Extract tradeable quantity from position dict."""
        return float(
            position.get("quantity")
            or position.get("base_size")
            or position.get("size")
            or position.get("balance")
            or 0
        )

    def _get_size_usd(self, position: Dict) -> float:
        return float(position.get("size_usd") or position.get("usd_value") or 0)

    def _liquidate_to_usdt(
        self, broker: Any, position: Dict, reason: str
    ) -> CleanupAction:
        """
        Market-sell *position* back to USD/USDT.

        When the USD value of the position is below EXCHANGE_MIN_ORDER_USD the
        order is skipped to avoid guaranteed rejection errors.
        """
        symbol = position.get("symbol", "UNKNOWN")
        size_usd = self._get_size_usd(position)
        quantity = self._get_quantity(position)

        if size_usd < EXCHANGE_MIN_ORDER_USD:
            msg = (
                f"${size_usd:.4f} < exchange minimum ${EXCHANGE_MIN_ORDER_USD:.2f}"
                f" – skipping {symbol}"
            )
            logger.warning("   ⚠️  %s", msg)
            return CleanupAction(
                symbol=symbol, action="SKIP",
                size_usd=size_usd, quantity=quantity,
                merge_target=None, success=False, message=msg,
            )

        if self.dry_run:
            msg = f"[DRY RUN] Would liquidate {symbol} ${size_usd:.4f} → USDT"
            logger.info("   %s", msg)
            return CleanupAction(
                symbol=symbol, action=reason,
                size_usd=size_usd, quantity=quantity,
                merge_target=None, success=True, message=msg,
            )

        try:
            logger.info(
                "   💱 %s: liquidating %s qty=%.8f ($%.4f) → USDT",
                reason, symbol, quantity, size_usd,
            )
            order = broker.place_market_order(
                symbol=symbol,
                side="sell",
                quantity=quantity,
                size_type="base",
            )
            if self._is_filled(order):
                msg = f"Liquidated {symbol} ${size_usd:.4f} → USDT | order={order.get('order_id', '?')}"
                logger.info("   ✅ %s", msg)
                return CleanupAction(
                    symbol=symbol, action=reason,
                    size_usd=size_usd, quantity=quantity,
                    merge_target=None, success=True, message=msg,
                )
            else:
                msg = f"Order did not fill: {order}"
                logger.warning("   ⚠️  %s → %s", symbol, msg)
                return CleanupAction(
                    symbol=symbol, action=reason,
                    size_usd=size_usd, quantity=quantity,
                    merge_target=None, success=False, message=msg,
                )
        except Exception as exc:
            msg = f"Exception liquidating {symbol}: {exc}"
            logger.error("   ❌ %s", msg)
            return CleanupAction(
                symbol=symbol, action=reason,
                size_usd=size_usd, quantity=quantity,
                merge_target=None, success=False, message=msg,
            )

    def _merge_into_asset(
        self, broker: Any, position: Dict, target_symbol: str
    ) -> CleanupAction:
        """
        Close *position* and immediately re-buy *target_symbol* with the proceeds.

        If the close order fails, the merge is aborted (no orphan buy).
        If the buy order fails, the freed USDT stays as cash (not an error).
        """
        symbol = position.get("symbol", "UNKNOWN")
        size_usd = self._get_size_usd(position)
        quantity = self._get_quantity(position)

        if size_usd < EXCHANGE_MIN_ORDER_USD:
            msg = (
                f"${size_usd:.4f} < exchange minimum ${EXCHANGE_MIN_ORDER_USD:.2f}"
                f" – skipping merge of {symbol}"
            )
            logger.warning("   ⚠️  %s", msg)
            return CleanupAction(
                symbol=symbol, action="SKIP",
                size_usd=size_usd, quantity=quantity,
                merge_target=target_symbol, success=False, message=msg,
            )

        if self.dry_run:
            msg = (
                f"[DRY RUN] Would merge {symbol} ${size_usd:.4f}"
                f" → {target_symbol}"
            )
            logger.info("   %s", msg)
            return CleanupAction(
                symbol=symbol, action="MICRO_MERGE",
                size_usd=size_usd, quantity=quantity,
                merge_target=target_symbol, success=True, message=msg,
            )

        try:
            # --- Step A: close source position ---
            logger.info(
                "   🔀 MERGE: closing %s qty=%.8f ($%.4f)",
                symbol, quantity, size_usd,
            )
            close_order = broker.place_market_order(
                symbol=symbol,
                side="sell",
                quantity=quantity,
                size_type="base",
            )
            if not self._is_filled(close_order):
                msg = f"Source close failed: {close_order} – merge aborted for {symbol}"
                logger.warning("   ⚠️  %s", msg)
                return CleanupAction(
                    symbol=symbol, action="MICRO_MERGE",
                    size_usd=size_usd, quantity=quantity,
                    merge_target=target_symbol, success=False, message=msg,
                )

            # --- Step B: re-buy target with proceeds ---
            logger.info(
                "   🎯 MERGE: buying $%.4f of %s", size_usd, target_symbol
            )
            buy_order = broker.place_market_order(
                symbol=target_symbol,
                side="buy",
                quantity=size_usd,
                size_type="quote",   # Re-invest the USD proceeds from the closed position
            )
            if self._is_filled(buy_order):
                msg = (
                    f"Merged {symbol} ${size_usd:.4f} → {target_symbol} "
                    f"| close={close_order.get('order_id', '?')} "
                    f"buy={buy_order.get('order_id', '?')}"
                )
                logger.info("   ✅ %s", msg)
                return CleanupAction(
                    symbol=symbol, action="MICRO_MERGE",
                    size_usd=size_usd, quantity=quantity,
                    merge_target=target_symbol, success=True, message=msg,
                )
            else:
                # Close succeeded, buy failed – cash stays as USDT (acceptable)
                msg = (
                    f"Closed {symbol} but re-buy into {target_symbol} failed "
                    f"(proceeds remain as USDT): {buy_order}"
                )
                logger.warning("   ⚠️  %s", msg)
                return CleanupAction(
                    symbol=symbol, action="MICRO_MERGE",
                    size_usd=size_usd, quantity=quantity,
                    merge_target=target_symbol, success=True, message=msg,
                )
        except Exception as exc:
            msg = f"Exception merging {symbol} → {target_symbol}: {exc}"
            logger.error("   ❌ %s", msg)
            return CleanupAction(
                symbol=symbol, action="MICRO_MERGE",
                size_usd=size_usd, quantity=quantity,
                merge_target=target_symbol, success=False, message=msg,
            )

    # ------------------------------------------------------------------
    # Post-execution bookkeeping
    # ------------------------------------------------------------------

    def _record_executed(self, actions: List[CleanupAction]) -> None:
        """Notify DustConsolidationEngine of completed liquidations."""
        try:
            from bot.dust_consolidation_engine import get_dust_consolidation_engine
            engine = get_dust_consolidation_engine()
            for action in actions:
                if action.success and action.action not in ("SKIP",):
                    engine.record_consolidation_executed(action.symbol, action.size_usd)
        except Exception:
            pass  # Non-critical bookkeeping; silently skip if engine unavailable


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[AutoCleanupEngine] = None
_instance_lock = threading.Lock()


def get_auto_cleanup_engine(
    dust_threshold_usd: float = DUST_THRESHOLD_USD,
    micro_threshold_usd: float = MICRO_THRESHOLD_USD,
    dry_run: bool = False,
) -> AutoCleanupEngine:
    """
    Return the process-wide AutoCleanupEngine singleton.

    Thread-safe. Configuration parameters are applied only on the **first**
    call; subsequent calls return the already-created instance unchanged.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AutoCleanupEngine(
                    dust_threshold_usd=dust_threshold_usd,
                    micro_threshold_usd=micro_threshold_usd,
                    dry_run=dry_run,
                )
    return _instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    class _MockBroker:
        """Minimal broker stub for self-test."""
        def place_market_order(self, symbol, side, quantity, size_type="base", **_kw):
            logger.info(
                "[MockBroker] %s %s qty=%.8f size_type=%s",
                side.upper(), symbol, quantity, size_type,
            )
            return {"status": "filled", "order_id": f"mock-{symbol}-{side}"}

    sample_positions = [
        # dust (< $2)
        {"symbol": "SHIB-USD",  "size_usd": 0.07,  "quantity": 5_000_000, "pnl_pct": -0.20, "age_hours": 200},
        {"symbol": "DOGE-USD",  "size_usd": 0.95,  "quantity": 5.0,       "pnl_pct": -0.05, "age_hours": 96},
        # micro ($2-$10)
        {"symbol": "ETH-USD",   "size_usd": 3.50,  "quantity": 0.0015,    "pnl_pct": -0.01, "age_hours": 48},
        {"symbol": "SOL-USD",   "size_usd": 4.80,  "quantity": 0.05,      "pnl_pct":  0.01, "age_hours": 300},
        # healthy (> $10)
        {"symbol": "BTC-USD",   "size_usd": 150.0, "quantity": 0.004,     "pnl_pct":  0.03, "age_hours": 12},
        {"symbol": "ADA-USD",   "size_usd": 25.0,  "quantity": 50.0,      "pnl_pct":  0.02, "age_hours": 6},
    ]

    engine = AutoCleanupEngine(dry_run=True)
    result = engine.run(_MockBroker(), sample_positions, portfolio_value_usd=184.32)

    print("\n=== CLEANUP RESULT ===")
    print(f"  Dust found/liquidated : {result.dust_found}/{result.dust_liquidated}")
    print(f"  Micro found           : {result.micro_found}")
    print(f"  Micro merged          : {result.micro_merged}")
    print(f"  Micro liquidated      : {result.micro_liquidated}")
    print(f"  USD recovered         : ${result.total_usd_recovered:.4f}")
    print(f"\n  Actions:")
    for a in result.actions:
        tgt = f" → {a.merge_target}" if a.merge_target else ""
        status = "✅" if a.success else "❌"
        print(f"    {status} [{a.action:20s}] {a.symbol}{tgt}  ${a.size_usd:.4f}  {a.message}")

    sys.exit(0)
