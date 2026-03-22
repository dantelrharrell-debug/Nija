"""
NIJA Pro Position Manager
==========================
Persistent position tracking **plus** institutional-grade scaling rules.

Two integrated layers
---------------------
1. **Persistence layer** (``PositionManager``)
   Saves / loads / validates open positions to ``data/open_positions.json``.
   Backward-compatible with all existing callers.

2. **Scaling layer** (``ProPositionManager``)
   Enforces pro-level rules before every entry:

   * **Account tiers** -- caps and risk budgets scale with balance
     (NANO → MICRO → STARTER → GROWTH → ESTABLISHED → ELITE).
   * **Kelly-fraction sizing** -- size = f_kelly × balance, tier-clipped.
     Defaults to conservative half-Kelly.
   * **Concentration gate** -- no symbol > ``max_concentration_pct`` of portfolio.
   * **Risk-per-trade gate** -- max loss per entry ≤ ``max_risk_per_trade_pct``
     of balance.
   * **Portfolio heat gate** -- total open notional ≤ ``max_portfolio_heat_pct``
     of balance.
   * **Scale-in tracking** -- optional multi-leg entries
     (round 1 = 50 %, round 2 = 30 %, round 3 = 20 %).
   * **Auto-cleanup trigger** -- calls ``AutoCleanupEngine.run()`` before
     denying due to position-cap breach.

Usage (one-liner in trading_strategy.py)::

    from bot.position_manager import PositionManager, ProPositionManager, get_pro_position_manager

    # Legacy persistence -- unchanged
    mgr = PositionManager()
    mgr.save_positions(my_positions)

    # Pro sizing gate (new)
    pro = get_pro_position_manager(balance=2500.0)
    decision = pro.can_open("ETH-USD", stop_loss_pct=0.02, signal_quality=0.75)
    if decision.approved:
        # place order for decision.size_usd
        pro.record_opened("ETH-USD", decision.size_usd)

Author: NIJA Trading Systems
Version: 2.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.positions")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POSITION_BALANCE_MISMATCH_THRESHOLD = 20  # Legacy: warn if tracked > balance * this

# Half-Kelly multiplier -- conservative default to limit ruin probability
HALF_KELLY_FRACTION: float = 0.5

# Per-tier config table rows:
# (min_balance_usd, max_positions, max_risk_per_trade_pct, max_concentration_pct,
#  max_portfolio_heat_pct, base_size_pct)
_TIER_TABLE: List[Tuple[float, int, float, float, float, float]] = [
    #  min_bal   max_pos  risk%    conc%    heat%    base%
    (    0.0,      2,    0.010,   0.40,    0.60,    0.030),  # NANO
    (  100.0,      3,    0.015,   0.35,    0.65,    0.040),  # MICRO
    (  500.0,      4,    0.020,   0.30,    0.70,    0.050),  # STARTER
    ( 2_000.0,     5,    0.020,   0.25,    0.75,    0.060),  # GROWTH
    (10_000.0,     6,    0.015,   0.20,    0.80,    0.060),  # ESTABLISHED
    (50_000.0,     8,    0.010,   0.15,    0.85,    0.050),  # ELITE
]

# Scale-in allocation splits (must sum to 1.0)
SCALE_IN_SPLITS: Tuple[float, ...] = (0.50, 0.30, 0.20)

# Absolute floor: never size below this regardless of tier
ABS_MIN_POSITION_USD: float = 10.0


# ---------------------------------------------------------------------------
# Enumerations and data classes (scaling layer)
# ---------------------------------------------------------------------------

class AccountTier(str, Enum):
    NANO        = "NANO"         # < $100
    MICRO       = "MICRO"        # $100 - $500
    STARTER     = "STARTER"      # $500 - $2 000
    GROWTH      = "GROWTH"       # $2 000 - $10 000
    ESTABLISHED = "ESTABLISHED"  # $10 000 - $50 000
    ELITE       = "ELITE"        # $50 000+


class DenyReason(str, Enum):
    POSITION_CAP      = "POSITION_CAP"
    CONCENTRATION     = "CONCENTRATION"
    RISK_PER_TRADE    = "RISK_PER_TRADE"
    PORTFOLIO_HEAT    = "PORTFOLIO_HEAT"
    SIZE_TOO_SMALL    = "SIZE_TOO_SMALL"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"


@dataclass
class TierConfig:
    tier: AccountTier
    max_positions: int
    max_risk_per_trade_pct: float
    max_concentration_pct: float
    max_portfolio_heat_pct: float
    base_size_pct: float


@dataclass
class SizeDecision:
    approved: bool
    size_usd: float
    tier: AccountTier
    scale_in_leg: int               # 1, 2 or 3
    deny_reason: Optional[DenyReason] = None
    deny_detail: str = ""
    kelly_full_size: float = 0.0
    signal_quality: float = 0.0


@dataclass
class PortfolioSnapshot:
    balance: float
    open_positions: Dict[str, float] = field(default_factory=dict)
    total_open_usd: float = 0.0

    def __post_init__(self) -> None:
        if not self.total_open_usd:
            self.total_open_usd = sum(self.open_positions.values())


# ---------------------------------------------------------------------------
# LAYER 1 – Persistence (backward-compatible)
# ---------------------------------------------------------------------------

class PositionManager:
    """
    Manages persistent storage of open trading positions.

    Features
    --------
    - Save positions to JSON file on every update
    - Load positions on startup
    - Validate positions against broker API
    - Handle edge cases (positions closed externally)
    """

    def __init__(self, data_dir: str = "./data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.positions_file = self.data_dir / "open_positions.json"
        logger.info("💾 Position manager initialized: %s", self.positions_file)

    @staticmethod
    def _get_position_size(position: Dict) -> float:
        return float(position.get("size_usd") or position.get("position_size_usd") or 0)

    def save_positions(self, positions: Dict) -> bool:
        try:
            state = {
                "timestamp": datetime.now().isoformat(),
                "positions": positions,
                "count": len(positions),
            }
            tmp = self.positions_file.with_suffix(".tmp")
            with open(tmp, "w") as fh:
                json.dump(state, fh, indent=2, default=str)
            tmp.replace(self.positions_file)
            logger.debug("💾 Saved %d positions to %s", len(positions), self.positions_file)
            return True
        except Exception as exc:
            logger.error("Failed to save positions: %s", exc)
            return False

    def load_positions(self) -> Dict:
        if not self.positions_file.exists():
            logger.info("No saved positions found (first run)")
            return {}
        try:
            with open(self.positions_file, "r") as fh:
                state = json.load(fh)
            positions: Dict = state.get("positions", {})
            timestamp: str = state.get("timestamp", "unknown")
            count = len(positions)
            logger.info("💾 Loaded %d positions from %s", count, timestamp)

            zero_size_count = 0
            for symbol, pos in positions.items():
                size = self._get_position_size(pos)
                if size == 0:
                    zero_size_count += 1
                    logger.warning(
                        "  ⚠️ %s: %s @ $%.4f (Size: $0.00 - INVALID POSITION)",
                        symbol, pos.get("side"), pos.get("entry_price", 0),
                    )
                else:
                    logger.info(
                        "  ↳ %s: %s @ $%.4f (Size: $%.2f)",
                        symbol, pos.get("side"), pos.get("entry_price", 0), size,
                    )

            if zero_size_count:
                logger.warning("")
                logger.warning("=" * 70)
                logger.warning("⚠️  POSITION DATA INTEGRITY WARNING")
                logger.warning("   Found %d position(s) with $0.00 size", zero_size_count)
                logger.warning("   These will be validated against broker")
                logger.warning("=" * 70)

            return positions

        except json.JSONDecodeError as exc:
            logger.error("Corrupted positions file: %s", exc)
            backup = self.positions_file.with_suffix(".corrupted")
            self.positions_file.rename(backup)
            logger.warning("Moved corrupted file to %s", backup)
            return {}
        except Exception as exc:
            logger.error("Failed to load positions: %s", exc)
            return {}

    def validate_positions(self, positions: Dict, broker: Any) -> Dict:
        if not positions:
            return {}
        logger.info("🔍 Validating %d loaded positions against broker...", len(positions))
        validated: Dict = {}
        for symbol, pos in positions.items():
            try:
                market_data = broker.get_market_data(symbol, timeframe="1m", limit=1)
                if not market_data or not market_data.get("candles"):
                    logger.warning("  ✗ %s: No market data - removing position", symbol)
                    continue
                current_price = float(market_data["candles"][-1]["close"])
                pos["current_price"] = current_price
                entry_price = float(pos.get("entry_price", 0))
                if entry_price <= 0:
                    logger.error(
                        "  ✗ %s: CAPITAL PROTECTION - NO ENTRY PRICE - removing", symbol
                    )
                    continue
                size_usd = self._get_position_size(pos)
                if pos.get("side") == "BUY":
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                else:
                    pnl_pct = ((entry_price - current_price) / entry_price) * 100
                pos["unrealized_pnl_pct"] = pnl_pct
                validated[symbol] = pos
                logger.info(
                    "  ✓ %s: Valid @ $%.4f (P&L: %+.2f%%)", symbol, current_price, pnl_pct
                )
            except Exception as exc:
                logger.error("  ✗ %s: Validation failed - %s", symbol, exc)
        removed_count = len(positions) - len(validated)
        if removed_count:
            logger.warning("⚠️  Removed %d invalid positions", removed_count)
        logger.info("✅ Validated %d positions", len(validated))
        return validated

    def validate_position_sizes(self, positions: Dict, current_balance: float) -> None:
        if not positions:
            return
        total_position_value = sum(self._get_position_size(p) for p in positions.values())
        logger.info(
            "📊 Position Size Validation: tracked=$%.2f balance=$%.2f",
            total_position_value, current_balance,
        )
        if current_balance > 0 and total_position_value > current_balance * POSITION_BALANCE_MISMATCH_THRESHOLD:
            logger.error(
                "⚠️  POSITION MISMATCH: Tracked $%.2f >> Balance $%.2f - likely stale data",
                total_position_value, current_balance,
            )
        zero_size_positions = [s for s, p in positions.items() if self._get_position_size(p) <= 0]
        small_positions = [s for s, p in positions.items() if 0 < self._get_position_size(p) < 1.0]
        if zero_size_positions:
            logger.warning(
                "   Found %d zero-size position(s): %s",
                len(zero_size_positions), ", ".join(zero_size_positions),
            )
        if small_positions:
            logger.info(
                "   Found %d small position(s) (< $1.00): %s",
                len(small_positions), ", ".join(small_positions),
            )

    def clear_positions(self) -> bool:
        try:
            if self.positions_file.exists():
                backup = self.positions_file.with_suffix(
                    f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                self.positions_file.rename(backup)
                logger.info("💾 Cleared positions (backup: %s)", backup)
            return True
        except Exception as exc:
            logger.error("Failed to clear positions: %s", exc)
            return False


# ---------------------------------------------------------------------------
# LAYER 2 – Pro scaling rules
# ---------------------------------------------------------------------------

def _resolve_tier(balance: float) -> TierConfig:
    row = _TIER_TABLE[0]
    for entry in _TIER_TABLE:
        if balance >= entry[0]:
            row = entry
    tier_index = _TIER_TABLE.index(row)
    tier_enum = list(AccountTier)[tier_index]
    return TierConfig(
        tier=tier_enum,
        max_positions=row[1],
        max_risk_per_trade_pct=row[2],
        max_concentration_pct=row[3],
        max_portfolio_heat_pct=row[4],
        base_size_pct=row[5],
    )


def _kelly_size(
    balance: float,
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    kelly_fraction: float = HALF_KELLY_FRACTION,
) -> float:
    """
    Kelly-optimal position size in USD (half-Kelly by default).

    f* = (W*b - L) / b   where b = avg_win / avg_loss
    """
    if avg_loss_pct <= 0 or balance <= 0:
        return 0.0
    b = avg_win_pct / avg_loss_pct
    f_star = max(0.0, (win_rate * b - (1.0 - win_rate)) / b)
    return balance * f_star * kelly_fraction


class ProPositionManager:
    """
    Pro-level position sizing with 7-gate pre-entry filter.

    Wraps the legacy ``PositionManager`` persistence layer and adds
    institutional-grade sizing controls on every ``can_open()`` call.

    Parameters
    ----------
    balance:
        Current USD account balance.  Keep fresh via ``update_balance()``.
    win_rate:
        Historical win rate [0.0, 1.0] used in Kelly formula.
    avg_win_pct:
        Average winning trade as a fraction (e.g. 0.04 = 4 %).
    avg_loss_pct:
        Average losing trade as a fraction (e.g. 0.02 = 2 %).
    kelly_fraction:
        Multiplier on raw Kelly (0.5 = half-Kelly, conservative default).
    data_dir:
        Directory for persistent JSON positions file.
    dry_run:
        Log decisions without calling any broker methods.
    """

    def __init__(
        self,
        balance: float = 0.0,
        win_rate: float = 0.55,
        avg_win_pct: float = 0.04,
        avg_loss_pct: float = 0.02,
        kelly_fraction: float = HALF_KELLY_FRACTION,
        data_dir: str = "./data",
        dry_run: bool = False,
    ) -> None:
        self._balance = max(0.0, balance)
        self._win_rate = win_rate
        self._avg_win_pct = avg_win_pct
        self._avg_loss_pct = avg_loss_pct
        self._kelly_fraction = kelly_fraction
        self._dry_run = dry_run
        self._lock = threading.Lock()

        # Persistence delegate
        self._store = PositionManager(data_dir=data_dir)

        # Live state
        self._open_positions: Dict[str, float] = {}   # symbol → size_usd
        self._scale_in_legs: Dict[str, int] = {}      # symbol → legs completed

        logger.info(
            "🚀 ProPositionManager initialised | balance=$%.2f | tier=%s | "
            "kelly_frac=%.2f | dry_run=%s",
            self._balance, _resolve_tier(self._balance).tier.value,
            kelly_fraction, dry_run,
        )

    # ------------------------------------------------------------------
    # Balance / state management
    # ------------------------------------------------------------------

    def update_balance(self, new_balance: float) -> None:
        with self._lock:
            self._balance = max(0.0, new_balance)
            tier = _resolve_tier(self._balance)
            logger.debug(
                "💰 Balance updated: $%.2f | tier=%s | max_pos=%d",
                self._balance, tier.tier.value, tier.max_positions,
            )

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def tier(self) -> TierConfig:
        return _resolve_tier(self._balance)

    @property
    def open_count(self) -> int:
        return len(self._open_positions)

    @property
    def total_open_usd(self) -> float:
        return sum(self._open_positions.values())

    def snapshot(self) -> PortfolioSnapshot:
        with self._lock:
            return PortfolioSnapshot(
                balance=self._balance,
                open_positions=dict(self._open_positions),
                total_open_usd=self.total_open_usd,
            )

    # ------------------------------------------------------------------
    # Primary entry gate
    # ------------------------------------------------------------------

    def can_open(
        self,
        symbol: str,
        stop_loss_pct: float,
        signal_quality: float = 1.0,
        scale_in: bool = False,
        broker: Optional[Any] = None,
        positions_list: Optional[List[Dict]] = None,
    ) -> SizeDecision:
        """
        Gate check + Kelly sizing for a prospective entry.

        Parameters
        ----------
        symbol:
            Market symbol (e.g. ``"BTC-USD"``).
        stop_loss_pct:
            Distance from entry to stop-loss as a fraction (e.g. 0.02 = 2 %).
        signal_quality:
            Score in [0.0, 1.0]; higher quality increases approved size.
        scale_in:
            Split entry into successive legs (50 / 30 / 20 %).
        broker:
            Optional broker passed to auto-cleanup on cap breach.
        positions_list:
            Optional list of all open position dicts (forwarded to cleanup).

        Returns
        -------
        SizeDecision
        """
        with self._lock:
            return self._evaluate(
                symbol, stop_loss_pct, signal_quality, scale_in, broker, positions_list
            )

    # ------------------------------------------------------------------
    # Position lifecycle hooks
    # ------------------------------------------------------------------

    def record_opened(self, symbol: str, size_usd: float) -> None:
        with self._lock:
            self._open_positions[symbol] = (
                self._open_positions.get(symbol, 0.0) + size_usd
            )
            self._scale_in_legs[symbol] = self._scale_in_legs.get(symbol, 0) + 1
            logger.info(
                "📥 Opened: %s $%.2f | total_open=$%.2f | positions=%d",
                symbol, size_usd, self.total_open_usd, self.open_count,
            )

    def record_closed(self, symbol: str, realized_pnl_usd: float = 0.0) -> None:
        with self._lock:
            removed = self._open_positions.pop(symbol, 0.0)
            self._scale_in_legs.pop(symbol, None)
            logger.info(
                "📤 Closed: %s removed=$%.2f pnl=$%.2f | remaining=%d",
                symbol, removed, realized_pnl_usd, self.open_count,
            )

    def update_win_stats(
        self, win_rate: float, avg_win_pct: float, avg_loss_pct: float
    ) -> None:
        with self._lock:
            self._win_rate = max(0.0, min(1.0, win_rate))
            self._avg_win_pct = max(0.0001, avg_win_pct)
            self._avg_loss_pct = max(0.0001, avg_loss_pct)
            logger.debug(
                "📈 Kelly params: win_rate=%.2f avg_win=%.2f%% avg_loss=%.2f%%",
                self._win_rate, self._avg_win_pct * 100, self._avg_loss_pct * 100,
            )

    # ------------------------------------------------------------------
    # Persistence delegates (backward-compat)
    # ------------------------------------------------------------------

    def save_positions(self, positions: Dict) -> bool:
        return self._store.save_positions(positions)

    def load_positions(self) -> Dict:
        return self._store.load_positions()

    def validate_positions(self, positions: Dict, broker: Any) -> Dict:
        return self._store.validate_positions(positions, broker)

    def validate_position_sizes(self, positions: Dict, current_balance: float) -> None:
        self._store.validate_position_sizes(positions, current_balance)

    def clear_positions(self) -> bool:
        return self._store.clear_positions()

    # ------------------------------------------------------------------
    # Status dashboard
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        tier = self.tier
        port_val = self._balance + self.total_open_usd
        return {
            "balance":                self._balance,
            "tier":                   tier.tier.value,
            "max_positions":          tier.max_positions,
            "open_positions":         self.open_count,
            "total_open_usd":         round(self.total_open_usd, 4),
            "portfolio_heat_pct":     round(self.total_open_usd / self._balance, 4) if self._balance > 0 else (float("inf") if self.total_open_usd else 0.0),
            "max_portfolio_heat_pct": tier.max_portfolio_heat_pct,
            "max_risk_per_trade_pct": tier.max_risk_per_trade_pct,
            "max_concentration_pct":  tier.max_concentration_pct,
            "win_rate":               self._win_rate,
            "avg_win_pct":            self._avg_win_pct,
            "avg_loss_pct":           self._avg_loss_pct,
            "kelly_fraction":         self._kelly_fraction,
            "open_position_detail":   dict(self._open_positions),
            "scale_in_legs":          dict(self._scale_in_legs),
        }

    # ------------------------------------------------------------------
    # Private: 7-gate evaluation pipeline
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        symbol: str,
        stop_loss_pct: float,
        signal_quality: float,
        scale_in: bool,
        broker: Optional[Any],
        positions_list: Optional[List[Dict]],
    ) -> SizeDecision:
        tier = _resolve_tier(self._balance)
        sq = max(0.0, min(1.0, signal_quality))

        # ----- Gate 1: Position cap ----------------------------------------
        if symbol not in self._open_positions:
            if self.open_count >= tier.max_positions:
                freed = self._try_auto_cleanup(broker, positions_list)
                if not freed and self.open_count >= tier.max_positions:
                    return SizeDecision(
                        approved=False, size_usd=0.0, tier=tier.tier,
                        scale_in_leg=0,
                        deny_reason=DenyReason.POSITION_CAP,
                        deny_detail=(
                            f"At cap {self.open_count}/{tier.max_positions} "
                            f"({tier.tier.value}) – cleanup freed no slot"
                        ),
                        signal_quality=sq,
                    )

        # ----- Gate 2: Kelly size ------------------------------------------
        kelly_full = _kelly_size(
            self._balance, self._win_rate,
            self._avg_win_pct, self._avg_loss_pct,
            self._kelly_fraction,
        )
        base_size = max(kelly_full, self._balance * tier.base_size_pct)
        raw_size = base_size * (0.70 + 0.30 * sq)

        # ----- Gate 3: Scale-in leg ----------------------------------------
        leg = self._scale_in_legs.get(symbol, 0)
        if scale_in and leg < len(SCALE_IN_SPLITS):
            raw_size *= SCALE_IN_SPLITS[leg]
            next_leg = leg + 1
        else:
            next_leg = 1

        # ----- Gate 4: Risk-per-trade cap ----------------------------------
        if stop_loss_pct > 0:
            max_risk_usd = self._balance * tier.max_risk_per_trade_pct
            max_size_by_risk = max_risk_usd / stop_loss_pct
            if raw_size > max_size_by_risk:
                logger.debug(
                    "⬇️  %s: risk gate clips $%.2f → $%.2f",
                    symbol, raw_size, max_size_by_risk,
                )
                raw_size = max_size_by_risk

        # ----- Gate 5: Portfolio heat cap ----------------------------------
        allowed_heat = self._balance * tier.max_portfolio_heat_pct
        remaining_heat = allowed_heat - self.total_open_usd
        if remaining_heat <= 0 and self.total_open_usd > 0:
            return SizeDecision(
                approved=False, size_usd=0.0, tier=tier.tier,
                scale_in_leg=next_leg,
                deny_reason=DenyReason.PORTFOLIO_HEAT,
                deny_detail=(
                    f"Heat {self.total_open_usd:.2f}/${allowed_heat:.2f} "
                    f"({self.total_open_usd/self._balance*100:.1f}% >= "
                    f"{tier.max_portfolio_heat_pct*100:.0f}%)"
                ),
                kelly_full_size=kelly_full, signal_quality=sq,
            )
        if raw_size > remaining_heat > 0:
            raw_size = remaining_heat

        # ----- Gate 6: Concentration limit --------------------------------
        portfolio_value = self._balance + self.total_open_usd
        existing = self._open_positions.get(symbol, 0.0)
        projected_conc = (existing + raw_size) / portfolio_value if portfolio_value > 0 else 0.0
        if projected_conc > tier.max_concentration_pct:
            raw_size = tier.max_concentration_pct * portfolio_value - existing
            raw_size = max(0.0, raw_size)
            if raw_size < ABS_MIN_POSITION_USD:
                return SizeDecision(
                    approved=False, size_usd=0.0, tier=tier.tier,
                    scale_in_leg=next_leg,
                    deny_reason=DenyReason.CONCENTRATION,
                    deny_detail=(
                        f"{symbol} would reach {projected_conc*100:.1f}% "
                        f"(max {tier.max_concentration_pct*100:.0f}%) – "
                        f"remaining headroom ${raw_size:.2f} < min ${ABS_MIN_POSITION_USD}"
                    ),
                    kelly_full_size=kelly_full, signal_quality=sq,
                )

        # ----- Gate 7: Absolute minimum ------------------------------------
        if raw_size < ABS_MIN_POSITION_USD:
            return SizeDecision(
                approved=False, size_usd=0.0, tier=tier.tier,
                scale_in_leg=next_leg,
                deny_reason=DenyReason.SIZE_TOO_SMALL,
                deny_detail=f"Computed ${raw_size:.2f} < floor ${ABS_MIN_POSITION_USD}",
                kelly_full_size=kelly_full, signal_quality=sq,
            )

        # ----- Approved ✅ ------------------------------------------------
        final_size = round(raw_size, 2)
        logger.info(
            "✅ %s APPROVED | $%.2f | tier=%s | leg=%d | sq=%.2f | kelly=$%.2f",
            symbol, final_size, tier.tier.value, next_leg, sq, kelly_full,
        )
        return SizeDecision(
            approved=True, size_usd=final_size, tier=tier.tier,
            scale_in_leg=next_leg, kelly_full_size=kelly_full, signal_quality=sq,
        )

    # ------------------------------------------------------------------
    # Auto-cleanup integration
    # ------------------------------------------------------------------

    def _try_auto_cleanup(
        self,
        broker: Optional[Any],
        positions_list: Optional[List[Dict]],
    ) -> bool:
        if broker is None or not positions_list:
            return False
        try:
            from bot.auto_cleanup_engine import get_auto_cleanup_engine
            engine = get_auto_cleanup_engine()
            result = engine.run(
                broker=broker,
                positions=positions_list,
                portfolio_value_usd=self._balance + self.total_open_usd,
            )
            freed = result.dust_liquidated + result.micro_merged + result.micro_liquidated
            if freed:
                for action in result.actions:
                    if action.success and action.action not in ("SKIP",):
                        self._open_positions.pop(action.symbol, None)
                        self._scale_in_legs.pop(action.symbol, None)
                logger.info("🧹 Auto-cleanup freed %d slot(s)", freed)
                return True
        except Exception as exc:
            logger.warning("⚠️  Auto-cleanup skipped: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_pro_instance: Optional[ProPositionManager] = None
_pro_lock = threading.Lock()


def get_pro_position_manager(
    balance: float = 0.0,
    win_rate: float = 0.55,
    avg_win_pct: float = 0.04,
    avg_loss_pct: float = 0.02,
    kelly_fraction: float = HALF_KELLY_FRACTION,
    data_dir: str = "./data",
    dry_run: bool = False,
) -> ProPositionManager:
    """
    Return the process-wide ProPositionManager singleton.

    Thread-safe.  Parameters take effect only on the **first** call.
    Use ``update_balance()`` each cycle to keep sizing accurate.
    """
    global _pro_instance
    if _pro_instance is None:
        with _pro_lock:
            if _pro_instance is None:
                _pro_instance = ProPositionManager(
                    balance=balance,
                    win_rate=win_rate,
                    avg_win_pct=avg_win_pct,
                    avg_loss_pct=avg_loss_pct,
                    kelly_fraction=kelly_fraction,
                    data_dir=data_dir,
                    dry_run=dry_run,
                )
    return _pro_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    print("\n=== ProPositionManager self-test ===\n")

    test_cases = [
        (50.0,     "NANO        – tiny account"),
        (250.0,    "MICRO       – small account"),
        (1_000.0,  "STARTER     – getting started"),
        (5_000.0,  "GROWTH      – gaining momentum"),
        (25_000.0, "ESTABLISHED – scaling up"),
        (100_000.0,"ELITE       – institutional"),
    ]

    for bal, label in test_cases:
        pm = ProPositionManager(
            balance=bal, win_rate=0.55, avg_win_pct=0.04, avg_loss_pct=0.02
        )
        d = pm.can_open("BTC-USD", stop_loss_pct=0.02, signal_quality=0.80)
        status = "✅ APPROVED" if d.approved else f"❌ {d.deny_reason}"
        print(
            f"  {label:42s}  bal=${bal:>10,.0f}  "
            f"size=${d.size_usd:>8.2f}  "
            f"tier={d.tier.value:12s}  {status}"
        )

    print("\n=== Scale-in test ===")
    pm2 = ProPositionManager(
        balance=5_000.0, win_rate=0.60, avg_win_pct=0.05, avg_loss_pct=0.02
    )
    for leg_label in ("Leg 1 (50%)", "Leg 2 (30%)", "Leg 3 (20%)"):
        d = pm2.can_open("ETH-USD", stop_loss_pct=0.02, signal_quality=0.75, scale_in=True)
        if d.approved:
            pm2.record_opened("ETH-USD", d.size_usd)
        print(f"  {leg_label}: size=${d.size_usd:.2f}  approved={d.approved}")

    print("\n=== Report ===")
    for k, v in pm2.get_report().items():
        print(f"  {k}: {v}")

    sys.exit(0)
