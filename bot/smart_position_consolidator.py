"""
SMART POSITION CONSOLIDATOR
============================
Intelligently consolidates fragmented small positions into the single
best-performing position in the portfolio, rather than converting them
all to USDT.

Why consolidate into the best winner?
--------------------------------------
* Concentrates capital in the highest-performing asset (momentum compounding).
* Reduces position count and management overhead.
* Avoids idle cash drag that occurs when everything is liquidated to USDT.
* Winner-weighted compounding: capital from losers flows to the winner.

Consolidation pipeline
----------------------
1. **Score all positions** – rank by a composite score (PnL%, size, momentum).
2. **Identify the best winner** – the position with the highest score becomes
   the consolidation target.
3. **Select fragmented positions** – positions below ``fragment_threshold_usd``
   that are not the target are candidates for consolidation.
4. **Sort candidates by profit priority** – close losers first, winners last.
5. **Execute consolidation** – sell each fragment; re-buy the winner.
6. **Report** – return a structured ``ConsolidationResult`` for audit.

Usage
-----
    from bot.smart_position_consolidator import get_smart_position_consolidator

    consolidator = get_smart_position_consolidator()
    result = consolidator.consolidate(broker, positions, portfolio_value_usd=5000.0)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from bot.pipeline_order_submitter import submit_market_order_via_pipeline
except ImportError:
    try:
        from pipeline_order_submitter import submit_market_order_via_pipeline
    except ImportError:
        submit_market_order_via_pipeline = None  # type: ignore

logger = logging.getLogger("nija.smart_position_consolidator")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default threshold: positions below this are "fragment" candidates
DEFAULT_FRAGMENT_THRESHOLD_USD: float = 15.0

# Minimum size for a position to be considered as the consolidation target
DEFAULT_MIN_TARGET_SIZE_USD: float = 10.0

# Minimum PnL% required for the target to be considered a "winner"
DEFAULT_MIN_TARGET_PNL_PCT: float = 0.0   # 0% = at least break-even

# Scoring weights for target selection
_W_PNL = 0.5        # PnL % weight
_W_SIZE = 0.3       # Log(size_usd) weight
_W_AGE = 0.2        # Age penalty (older = less desirable as target)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConsolidationAction:
    """Record for one action (sell or buy) during consolidation."""
    symbol: str
    action: str          # "SELL_FRAGMENT" | "BUY_WINNER" | "SKIP" | "ERROR"
    size_usd: float
    quantity: float
    pnl_pct: float
    target_symbol: Optional[str]
    success: bool
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ConsolidationResult:
    """Full result returned by SmartPositionConsolidator.consolidate()."""
    run_timestamp: str
    target_symbol: Optional[str]       # Symbol that fragments were merged into
    positions_scanned: int
    fragments_found: int
    fragments_consolidated: int
    fragments_skipped: int
    proceeds_usd: float                # Total USD from sold fragments
    rebuy_attempted: bool
    rebuy_success: bool
    rebuy_usd: float
    actions: List[ConsolidationAction] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"SmartConsolidator: scanned={self.positions_scanned} "
            f"fragments={self.fragments_found} "
            f"consolidated={self.fragments_consolidated} "
            f"skipped={self.fragments_skipped} "
            f"proceeds=${self.proceeds_usd:.4f} "
            f"→{self.target_symbol or 'N/A'} "
            f"rebuy={'✅' if self.rebuy_success else '❌'}"
        )


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class SmartPositionConsolidator:
    """
    Consolidate fragmented small positions into the best-performing winner.

    Parameters
    ----------
    fragment_threshold_usd:
        Positions below this USD value are eligible to be consolidated.
    min_target_size_usd:
        The consolidation target must be at least this large.
    min_target_pnl_pct:
        Target must have at least this PnL% to qualify as a winner.
    dry_run:
        Logs all planned actions but makes no broker calls.
    min_proceeds_usd:
        Minimum total proceeds before the re-buy is executed.
    """

    def __init__(
        self,
        fragment_threshold_usd: float = DEFAULT_FRAGMENT_THRESHOLD_USD,
        min_target_size_usd: float = DEFAULT_MIN_TARGET_SIZE_USD,
        min_target_pnl_pct: float = DEFAULT_MIN_TARGET_PNL_PCT,
        dry_run: bool = False,
        min_proceeds_usd: float = 1.0,
    ) -> None:
        self.fragment_threshold_usd = fragment_threshold_usd
        self.min_target_size_usd = min_target_size_usd
        self.min_target_pnl_pct = min_target_pnl_pct
        self.dry_run = dry_run
        self.min_proceeds_usd = min_proceeds_usd
        self._lock = threading.Lock()
        logger.info(
            "🔗 SmartPositionConsolidator initialised "
            "| fragment<$%.2f | min_target_size=$%.2f | min_target_pnl=%.1f%% | dry_run=%s",
            fragment_threshold_usd, min_target_size_usd, min_target_pnl_pct, dry_run,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consolidate(
        self,
        broker: Any,
        positions: List[Dict],
        portfolio_value_usd: float = 0.0,
    ) -> ConsolidationResult:
        """
        Run smart consolidation: sell fragments, buy the best winner.

        Parameters
        ----------
        broker:
            Live broker instance with ``place_market_order``.
        positions:
            Current open positions list.
        portfolio_value_usd:
            Total portfolio value (used for logging).
        """
        with self._lock:
            return self._run(broker, positions, portfolio_value_usd)

    def find_best_target(self, positions: List[Dict]) -> Optional[str]:
        """
        Return the symbol of the best consolidation target, or None.

        Exposed publicly so callers can pre-check before running a full sweep.
        """
        target, _ = self._pick_target(positions, fragment_symbols=set())
        return target

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _run(
        self,
        broker: Any,
        positions: List[Dict],
        portfolio_value_usd: float,
    ) -> ConsolidationResult:
        now_ts = datetime.now(timezone.utc).isoformat()
        result = ConsolidationResult(
            run_timestamp=now_ts,
            target_symbol=None,
            positions_scanned=len(positions),
            fragments_found=0,
            fragments_consolidated=0,
            fragments_skipped=0,
            proceeds_usd=0.0,
            rebuy_attempted=False,
            rebuy_success=False,
            rebuy_usd=0.0,
        )

        if not positions:
            logger.info("🔗 SmartConsolidator: no positions to consolidate")
            return result

        logger.info(
            "🔗 SmartConsolidator START | %d positions | portfolio=$%.2f",
            len(positions), portfolio_value_usd,
        )

        # Step 1 – identify fragment candidates (small positions)
        fragments = [
            p for p in positions
            if 0 < self._size_usd(p) < self.fragment_threshold_usd
        ]
        result.fragments_found = len(fragments)

        if not fragments:
            logger.info("🔗 SmartConsolidator: no fragment positions below $%.2f", self.fragment_threshold_usd)
            return result

        fragment_symbols = {p.get("symbol") for p in fragments}

        # Step 2 – pick best target (must NOT be a fragment itself)
        target_symbol, target_score = self._pick_target(positions, fragment_symbols)
        if not target_symbol:
            logger.info(
                "🔗 SmartConsolidator: no qualifying winner target found "
                "(need size>$%.2f and pnl>=%.1f%%) – skipping",
                self.min_target_size_usd, self.min_target_pnl_pct,
            )
            return result

        result.target_symbol = target_symbol
        logger.info(
            "🔗 SmartConsolidator: target=%s (score=%.4f) | %d fragment(s) to consolidate",
            target_symbol, target_score, len(fragments),
        )

        # Step 3 – sort fragments: losers first (profit-priority)
        fragments = self._sort_losers_first(fragments)

        # Step 4 – sell each fragment
        for pos in fragments:
            sym = pos.get("symbol", "UNKNOWN")
            if sym == target_symbol:
                continue  # Safety guard
            action = self._sell_fragment(broker, pos, target_symbol)
            result.actions.append(action)
            if action.success:
                result.fragments_consolidated += 1
                result.proceeds_usd += action.size_usd
            else:
                result.fragments_skipped += 1
                if action.action == "ERROR":
                    result.errors.append(action.message)

        # Step 5 – re-buy target with aggregated proceeds
        if result.proceeds_usd >= self.min_proceeds_usd:
            rebuy = self._buy_target(broker, target_symbol, result.proceeds_usd)
            result.rebuy_attempted = True
            result.rebuy_success = rebuy.success
            result.rebuy_usd = result.proceeds_usd if rebuy.success else 0.0
            result.actions.append(rebuy)
            if not rebuy.success:
                result.errors.append(rebuy.message)
        else:
            logger.info(
                "🔗 SmartConsolidator: proceeds $%.4f < min $%.2f – skipping re-buy",
                result.proceeds_usd, self.min_proceeds_usd,
            )

        logger.info("🔗 SmartConsolidator DONE | %s", result.summary())
        return result

    # ------------------------------------------------------------------
    # Target selection
    # ------------------------------------------------------------------

    def _pick_target(
        self,
        positions: List[Dict],
        fragment_symbols: set,
    ) -> Tuple[Optional[str], float]:
        """
        Select the best consolidation target from non-fragment positions.

        Returns (symbol, score) or (None, 0.0).
        """
        candidates: List[Tuple[float, str]] = []

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol or symbol in fragment_symbols:
                continue

            size_usd = self._size_usd(pos)
            if size_usd < self.min_target_size_usd:
                continue

            pnl_pct = float(pos.get("pnl_pct") or 0)
            if pnl_pct < self.min_target_pnl_pct:
                continue

            age_hours = float(pos.get("age_hours") or 0)
            age_penalty = max(0.0, age_hours - 72.0) / 72.0

            score = (
                _W_PNL * pnl_pct
                + _W_SIZE * math.log1p(size_usd)
                - _W_AGE * age_penalty
            )
            candidates.append((score, symbol))

        if not candidates:
            return None, 0.0

        best_score, best_symbol = max(candidates, key=lambda t: t[0])
        return best_symbol, best_score

    # ------------------------------------------------------------------
    # Sorting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sort_losers_first(positions: List[Dict]) -> List[Dict]:
        """Sort positions so worst P&L comes first (profit-priority)."""
        return sorted(positions, key=lambda p: float(p.get("pnl_pct") or 0))

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    def _sell_fragment(
        self, broker: Any, position: Dict, target_symbol: str
    ) -> ConsolidationAction:
        symbol = position.get("symbol", "UNKNOWN")
        size_usd = self._size_usd(position)
        quantity = self._quantity(position)
        pnl_pct = float(position.get("pnl_pct") or 0)

        if quantity <= 0:
            msg = f"No quantity to sell for fragment {symbol}"
            return ConsolidationAction(
                symbol=symbol, action="SKIP", size_usd=size_usd, quantity=quantity,
                pnl_pct=pnl_pct, target_symbol=target_symbol, success=False, message=msg,
            )

        if self.dry_run:
            msg = (
                f"[DRY RUN] Would sell fragment {symbol} "
                f"qty={quantity:.8f} (${size_usd:.4f}, pnl={pnl_pct:+.2f}%) "
                f"→ {target_symbol}"
            )
            logger.info("   %s", msg)
            return ConsolidationAction(
                symbol=symbol, action="SELL_FRAGMENT", size_usd=size_usd,
                quantity=quantity, pnl_pct=pnl_pct, target_symbol=target_symbol,
                success=True, message=msg,
            )

        try:
            logger.info(
                "   💱 Selling fragment %s qty=%.8f ($%.4f, pnl=%+.2f%%) → %s",
                symbol, quantity, size_usd, pnl_pct, target_symbol,
            )
            if submit_market_order_via_pipeline is None:
                raise RuntimeError("ExecutionPipeline submit helper unavailable")

            order = submit_market_order_via_pipeline(
                broker=broker,
                symbol=symbol,
                side="sell",
                quantity=quantity,
                size_type="base",
                strategy="SmartPositionConsolidator",
            )
            filled = bool(
                order and order.get("status") in {"filled", "completed", "success"}
            )
            if filled:
                msg = (
                    f"Fragment sold: {symbol} ${size_usd:.4f} "
                    f"| order={order.get('order_id', '?')}"
                )
                logger.info("   ✅ %s", msg)
                return ConsolidationAction(
                    symbol=symbol, action="SELL_FRAGMENT", size_usd=size_usd,
                    quantity=quantity, pnl_pct=pnl_pct, target_symbol=target_symbol,
                    success=True, message=msg,
                )
            else:
                msg = f"Sell order did not fill for {symbol}: {order}"
                logger.warning("   ⚠️  %s", msg)
                return ConsolidationAction(
                    symbol=symbol, action="SKIP", size_usd=size_usd,
                    quantity=quantity, pnl_pct=pnl_pct, target_symbol=target_symbol,
                    success=False, message=msg,
                )
        except Exception as exc:
            msg = f"Exception selling fragment {symbol}: {exc}"
            logger.error("   ❌ %s", msg)
            return ConsolidationAction(
                symbol=symbol, action="ERROR", size_usd=size_usd,
                quantity=quantity, pnl_pct=pnl_pct, target_symbol=target_symbol,
                success=False, message=msg,
            )

    def _buy_target(
        self, broker: Any, target_symbol: str, amount_usd: float
    ) -> ConsolidationAction:
        if self.dry_run:
            msg = (
                f"[DRY RUN] Would buy ${amount_usd:.4f} of {target_symbol} "
                f"(consolidated proceeds)"
            )
            logger.info("   %s", msg)
            return ConsolidationAction(
                symbol=target_symbol, action="BUY_WINNER", size_usd=amount_usd,
                quantity=0.0, pnl_pct=0.0, target_symbol=target_symbol,
                success=True, message=msg,
            )

        try:
            logger.info(
                "   🏆 Buying $%.4f of winner %s (smart consolidation)",
                amount_usd, target_symbol,
            )
            if submit_market_order_via_pipeline is None:
                raise RuntimeError("ExecutionPipeline submit helper unavailable")

            order = submit_market_order_via_pipeline(
                broker=broker,
                symbol=target_symbol,
                side="buy",
                quantity=amount_usd,
                size_type="quote",
                strategy="SmartPositionConsolidator",
            )
            filled = bool(
                order and order.get("status") in {"filled", "completed", "success"}
            )
            if filled:
                msg = (
                    f"Consolidated ${amount_usd:.4f} → {target_symbol} "
                    f"| order={order.get('order_id', '?')}"
                )
                logger.info("   ✅ %s", msg)
                return ConsolidationAction(
                    symbol=target_symbol, action="BUY_WINNER", size_usd=amount_usd,
                    quantity=0.0, pnl_pct=0.0, target_symbol=target_symbol,
                    success=True, message=msg,
                )
            else:
                msg = f"Re-buy into {target_symbol} did not fill: {order}"
                logger.warning("   ⚠️  %s", msg)
                return ConsolidationAction(
                    symbol=target_symbol, action="BUY_WINNER", size_usd=amount_usd,
                    quantity=0.0, pnl_pct=0.0, target_symbol=target_symbol,
                    success=False, message=msg,
                )
        except Exception as exc:
            msg = f"Exception buying {target_symbol}: {exc}"
            logger.error("   ❌ %s", msg)
            return ConsolidationAction(
                symbol=target_symbol, action="ERROR", size_usd=amount_usd,
                quantity=0.0, pnl_pct=0.0, target_symbol=target_symbol,
                success=False, message=msg,
            )

    # ------------------------------------------------------------------
    # Field extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _size_usd(position: Dict) -> float:
        return float(position.get("size_usd") or position.get("usd_value") or 0)

    @staticmethod
    def _quantity(position: Dict) -> float:
        return float(
            position.get("quantity")
            or position.get("base_size")
            or position.get("size")
            or position.get("balance")
            or 0
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[SmartPositionConsolidator] = None
_instance_lock = threading.Lock()


def get_smart_position_consolidator(
    fragment_threshold_usd: float = DEFAULT_FRAGMENT_THRESHOLD_USD,
    min_target_size_usd: float = DEFAULT_MIN_TARGET_SIZE_USD,
    min_target_pnl_pct: float = DEFAULT_MIN_TARGET_PNL_PCT,
    dry_run: bool = False,
    min_proceeds_usd: float = 1.0,
) -> SmartPositionConsolidator:
    """
    Return the process-wide SmartPositionConsolidator singleton.

    Configuration is applied only on the first call.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SmartPositionConsolidator(
                    fragment_threshold_usd=fragment_threshold_usd,
                    min_target_size_usd=min_target_size_usd,
                    min_target_pnl_pct=min_target_pnl_pct,
                    dry_run=dry_run,
                    min_proceeds_usd=min_proceeds_usd,
                )
    return _instance
