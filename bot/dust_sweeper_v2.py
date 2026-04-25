"""
DUST SWEEPER V2
===============
Permanently kills the dust retry loop by:

1. Identifying all sub-$1 positions that the exchange can never fill.
2. Permanently blacklisting each one (DustBlacklist + in-memory set).
3. Attempting to consolidate the *largest* (most likely sellable) dust
   position into USDT — giving the account one clean position rather than
   N unsellable fragments.
4. Never recording a skipped dust position as a LOSS.

Design principles
-----------------
* **One sweep call** — trading_strategy.py calls ``DustSweeperV2.sweep()``
  once per cleanup cycle instead of iterating over every position itself.
* **Idempotent** — re-running the sweep on already-blacklisted symbols is a
  no-op (fast in-memory check, no broker call).
* **Audit trail** — every action is logged and returned in ``SweepResult``.

Usage
-----
    from bot.dust_sweeper_v2 import get_dust_sweeper_v2

    sweeper = get_dust_sweeper_v2()
    result  = sweeper.sweep(broker, positions)
    logger.info(result.summary())
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

try:
    from bot.pipeline_order_submitter import submit_market_order_via_pipeline
except ImportError:
    try:
        from pipeline_order_submitter import submit_market_order_via_pipeline
    except ImportError:
        submit_market_order_via_pipeline = None  # type: ignore

logger = logging.getLogger("nija.dust_sweeper_v2")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Exchange hard floor — positions below this USD value can NEVER be sold via
# API (Coinbase, Kraken, Binance all reject sub-$3 market orders reliably).
EXCHANGE_MIN_SELL_USD: float = 3.00

# Absolute dust floor — anything below this is blacklisted immediately and
# not even attempted.
DUST_BLACKLIST_USD: float = 3.00


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SweepAction:
    """Record for a single action taken during the sweep."""
    symbol: str
    size_usd: float
    action: str          # "BLACKLISTED" | "CONSOLIDATE_OK" | "CONSOLIDATE_SKIP" | "ALREADY_BLACKLISTED"
    success: bool
    reason: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class SweepResult:
    """Aggregated result of a single sweep run."""
    run_timestamp: str
    positions_scanned: int
    dust_found: int
    newly_blacklisted: int
    already_blacklisted: int
    consolidation_attempted: bool
    consolidation_success: bool
    actions: List[SweepAction] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"DustSweeperV2 | scanned={self.positions_scanned} "
            f"dust={self.dust_found} blacklisted={self.newly_blacklisted} "
            f"consolidate={'OK' if self.consolidation_success else ('SKIP' if not self.consolidation_attempted else 'FAIL')}"
        )


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class DustSweeperV2:
    """
    Sweeper that permanently kills the dust retry loop.

    Parameters
    ----------
    dust_threshold_usd:
        Positions at or below this value are treated as dust.  Default 1.00.
    dry_run:
        When True, log actions but do NOT call any broker methods and do NOT
        persist anything to the DustBlacklist file.
    """

    def __init__(
        self,
        dust_threshold_usd: float = DUST_BLACKLIST_USD,
        dry_run: bool = False,
    ) -> None:
        self.dust_threshold_usd = dust_threshold_usd
        self.dry_run = dry_run

        # Fast in-memory set — checked before every broker call
        self._blacklist: Set[str] = set()
        self._lock = threading.Lock()

        # Persistent blacklist (survives restarts) — loaded lazily
        self._persistent_blacklist = self._load_persistent_blacklist()

        # Pre-load already-blacklisted symbols into the in-memory set
        if self._persistent_blacklist:
            try:
                self._blacklist.update(
                    self._persistent_blacklist.get_blacklisted_symbols()
                )
            except Exception:
                pass

        logger.info(
            "🧹 DustSweeperV2 initialised | threshold=$%.2f | dry_run=%s | "
            "pre-loaded %d blacklisted symbols",
            dust_threshold_usd, dry_run, len(self._blacklist),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sweep(
        self,
        broker: Any,
        positions: List[Dict],
    ) -> SweepResult:
        """
        Run a full dust sweep.

        1. Identify all positions below ``dust_threshold_usd``.
        2. Blacklist each one permanently (skip if already blacklisted).
        3. Attempt to consolidate the *single* largest dust position into
           USDT so the account ends up with at least one usable balance.
        4. Return a structured ``SweepResult`` for audit / logging.

        Parameters
        ----------
        broker:
            Live broker instance (``place_market_order``, ``get_current_price``).
        positions:
            Raw position list from ``broker.get_positions()`` or
            ``get_current_positions()``.  Must contain at minimum
            ``symbol``, ``size_usd`` or ``usd_value``, and ``quantity``.
        """
        with self._lock:
            return self._run(broker, positions)

    def is_blacklisted(self, symbol: str) -> bool:
        """Fast O(1) check — call this in the hot trading loop."""
        return symbol in self._blacklist

    def add_to_blacklist(self, symbol: str, usd_value: float, reason: str = "") -> None:
        """Manually add a symbol — e.g. after a failed sell attempt."""
        self._blacklist.add(symbol)
        if self._persistent_blacklist and not self.dry_run:
            try:
                self._persistent_blacklist.add_to_blacklist(
                    symbol=symbol,
                    usd_value=usd_value,
                    reason=reason or f"manual dust block (${usd_value:.4f})",
                )
            except Exception as exc:
                logger.debug("Persistent blacklist update skipped: %s", exc)

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run(self, broker: Any, positions: List[Dict]) -> SweepResult:
        now_ts = datetime.now(timezone.utc).isoformat()
        result = SweepResult(
            run_timestamp=now_ts,
            positions_scanned=len(positions),
            dust_found=0,
            newly_blacklisted=0,
            already_blacklisted=0,
            consolidation_attempted=False,
            consolidation_success=False,
        )

        if not positions:
            return result

        # Step 1 — find dust
        dust = self._identify_dust(positions)
        result.dust_found = len(dust)

        if not dust:
            logger.debug("🧹 DustSweeperV2: no dust found in %d positions", len(positions))
            return result

        logger.warning(
            "🧹 DustSweeperV2: found %d dust position(s) (threshold=$%.2f)",
            len(dust), self.dust_threshold_usd,
        )

        # Step 2 — blacklist all dust, track which are new
        consolidation_candidate: Optional[Dict] = None
        best_candidate_usd: float = 0.0

        processed_symbols: Set[str] = set()  # dedup guard — never process same symbol twice

        for pos in dust:
            symbol = pos["symbol"]

            # DEDUP GUARD: skip if we've already processed this symbol this sweep
            if symbol in processed_symbols:
                logger.debug("   ⏭️ %s already processed this sweep — skipping", symbol)
                continue
            processed_symbols.add(symbol)

            size_usd = pos["size_usd"]

            if symbol in self._blacklist:
                # Already blacklisted — no-op
                action = SweepAction(
                    symbol=symbol,
                    size_usd=size_usd,
                    action="ALREADY_BLACKLISTED",
                    success=True,
                    reason="Previously blacklisted — permanently ignored",
                )
                result.already_blacklisted += 1
                result.actions.append(action)
                logger.debug("   ⏭️ %s already blacklisted — skipping", symbol)
                continue

            # New dust — blacklist now
            logger.warning(
                "   🚫 PERMANENT DUST IGNORE: %s ($%.4f) — blacklisted forever",
                symbol, size_usd,
            )
            self._blacklist.add(symbol)
            if self._persistent_blacklist and not self.dry_run:
                try:
                    self._persistent_blacklist.add_to_blacklist(
                        symbol=symbol,
                        usd_value=size_usd,
                        reason=f"dust sweep v2 (${size_usd:.4f} < ${self.dust_threshold_usd:.2f})",
                    )
                except Exception as exc:
                    logger.debug("Persistent blacklist write failed for %s: %s", symbol, exc)

            action = SweepAction(
                symbol=symbol,
                size_usd=size_usd,
                action="BLACKLISTED",
                success=True,
                reason=f"Dust position ${size_usd:.4f} < ${self.dust_threshold_usd:.2f} — permanently ignored",
            )
            result.newly_blacklisted += 1
            result.actions.append(action)

            # Track the *largest* dust as consolidation candidate
            # (largest = most likely to be above exchange floor and actually fill)
            if size_usd > best_candidate_usd:
                best_candidate_usd = size_usd
                consolidation_candidate = pos

        # Step 3 — attempt to consolidate the largest dust position into USDT
        # Only bother if it is above the exchange hard floor
        if consolidation_candidate and best_candidate_usd >= EXCHANGE_MIN_SELL_USD:
            result.consolidation_attempted = True
            sym = consolidation_candidate["symbol"]
            qty = consolidation_candidate.get("quantity", 0)

            if self.dry_run:
                logger.info(
                    "   [DRY RUN] Would consolidate %s ($%.4f) → USDT", sym, best_candidate_usd
                )
                action = SweepAction(
                    symbol=sym,
                    size_usd=best_candidate_usd,
                    action="CONSOLIDATE_SKIP",
                    success=True,
                    reason="dry_run — no broker call",
                )
                result.consolidation_success = True
                result.actions.append(action)
            elif qty and qty > 0:
                try:
                    logger.warning(
                        "   🔁 Consolidating %s ($%.4f, qty=%.8f) → USDT",
                        sym, best_candidate_usd, qty,
                    )
                    if submit_market_order_via_pipeline is None:
                        raise RuntimeError("ExecutionPipeline submit helper unavailable")

                    sell_result = submit_market_order_via_pipeline(
                        broker=broker,
                        symbol=sym,
                        side="sell",
                        quantity=qty,
                        size_type="base",
                        strategy="DustSweeperV2",
                    )
                    ok = (
                        sell_result is not None
                        and sell_result.get("status") not in ("error", "unfilled", None)
                    )
                    action = SweepAction(
                        symbol=sym,
                        size_usd=best_candidate_usd,
                        action="CONSOLIDATE_OK" if ok else "CONSOLIDATE_SKIP",
                        success=ok,
                        reason=(
                            f"Sold {qty:.8f} → USDT"
                            if ok
                            else f"Sell failed: {sell_result}"
                        ),
                    )
                    result.consolidation_success = ok
                    result.actions.append(action)
                    if ok:
                        logger.warning("   ✅ Consolidation sold %s → USDT", sym)
                    else:
                        logger.warning("   ⚠️  Consolidation sell failed for %s — still blacklisted", sym)
                except Exception as exc:
                    logger.warning("   ⚠️  Consolidation exception for %s: %s", sym, exc)
                    action = SweepAction(
                        symbol=sym,
                        size_usd=best_candidate_usd,
                        action="CONSOLIDATE_SKIP",
                        success=False,
                        reason=f"Exception: {exc}",
                    )
                    result.actions.append(action)
            else:
                logger.warning(
                    "   ⚠️  %s has no valid quantity — skipping consolidation sell", sym
                )
                action = SweepAction(
                    symbol=sym,
                    size_usd=best_candidate_usd,
                    action="CONSOLIDATE_SKIP",
                    success=False,
                    reason="quantity missing or zero",
                )
                result.actions.append(action)
        else:
            logger.debug(
                "   ℹ️  No consolidation candidate above $%.2f exchange floor",
                EXCHANGE_MIN_SELL_USD,
            )

        logger.warning("🧹 DustSweeperV2 DONE | %s", result.summary())
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _identify_dust(self, positions: List[Dict]) -> List[Dict]:
        """Return positions whose USD value is <= dust_threshold_usd."""
        dust = []
        for pos in positions:
            symbol = pos.get("symbol")
            if not symbol:
                continue
            size_usd = pos.get("size_usd") or pos.get("usd_value") or 0.0
            if 0 < size_usd <= self.dust_threshold_usd:
                dust.append({
                    "symbol": symbol,
                    "size_usd": size_usd,
                    "quantity": (
                        pos.get("quantity")
                        or pos.get("base_size")
                        or pos.get("size")
                        or pos.get("balance")
                        or 0.0
                    ),
                })
        return dust

    @staticmethod
    def _load_persistent_blacklist():
        """Load DustBlacklist singleton — returns None on import failure."""
        try:
            from bot.dust_blacklist import get_dust_blacklist
            return get_dust_blacklist()
        except ImportError:
            try:
                from dust_blacklist import get_dust_blacklist  # type: ignore
                return get_dust_blacklist()
            except ImportError:
                logger.debug("DustBlacklist module not available — using in-memory only")
                return None


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[DustSweeperV2] = None
_instance_lock = threading.Lock()


def get_dust_sweeper_v2(
    dust_threshold_usd: float = DUST_BLACKLIST_USD,
    dry_run: bool = False,
) -> DustSweeperV2:
    """Return the process-wide singleton DustSweeperV2."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = DustSweeperV2(
                dust_threshold_usd=dust_threshold_usd,
                dry_run=dry_run,
            )
        return _instance
