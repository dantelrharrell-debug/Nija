"""
NIJA Portfolio Profit Engine
==============================

Tracks TOTAL PORTFOLIO PROFIT across all closed trades, supports profit
harvesting (withdrawing accumulated profits), portfolio reset, and automatic
profit compounding back into the trading capital pool.

Key Features:
- Persistent TOTAL PORTFOLIO PROFIT ledger (survives restarts)
- Profit harvesting: extract realised gains while preserving base capital
- Portfolio reset: start a fresh profit-tracking epoch
- Auto-compounding: configurable portion of each profit is reinvested
- Thread-safe singleton via get_portfolio_profit_engine()
- Lightweight JSON persistence; no external dependencies

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nija.portfolio_profit")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """Single closed trade captured by the profit engine."""
    timestamp: str
    symbol: str
    pnl_usd: float          # net P&L in USD (positive = profit, negative = loss)
    is_win: bool
    epoch: int              # which reset epoch this trade belongs to


@dataclass
class HarvestRecord:
    """A single profit-harvest event."""
    timestamp: str
    amount_usd: float       # amount harvested
    epoch: int
    note: str = ""


@dataclass
class PortfolioProfitState:
    """
    Persisted state of the portfolio profit engine.

    Fields are reset on each call to reset_portfolio() but the epoch counter
    advances so historical epochs can be distinguished in the log.
    """
    epoch: int = 0                              # increments on every reset
    base_capital: float = 0.0                  # capital at start of epoch
    total_gross_profit: float = 0.0            # sum of winning trade PnL
    total_gross_loss: float = 0.0              # sum of losing trade PnL (positive value)
    total_fees: float = 0.0                    # fees recorded separately
    total_trades: int = 0
    winning_trades: int = 0
    harvested_profit: float = 0.0              # cumulative amount harvested
    compounded_profit: float = 0.0             # cumulative amount compounded
    epoch_started: str = ""                    # ISO timestamp of epoch start
    last_updated: str = ""
    trades: List[Dict] = field(default_factory=list)
    harvest_log: List[Dict] = field(default_factory=list)

    # ---------- computed properties ----------

    @property
    def net_profit(self) -> float:
        """Total realised P&L since epoch start (gross profit - gross loss)."""
        return self.total_gross_profit - self.total_gross_loss

    @property
    def available_to_harvest(self) -> float:
        """Profit that has not yet been harvested or compounded."""
        return max(0.0, self.net_profit - self.harvested_profit - self.compounded_profit)

    @property
    def roi_pct(self) -> float:
        if self.base_capital > 0:
            return (self.net_profit / self.base_capital) * 100
        return 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades > 0:
            return (self.winning_trades / self.total_trades) * 100
        return 0.0

    @property
    def profit_factor(self) -> float:
        if self.total_gross_loss > 0:
            return round(self.total_gross_profit / self.total_gross_loss, 4)
        return 999.99 if self.total_gross_profit > 0 else 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        # computed properties aren't in asdict — add them manually
        d['net_profit'] = self.net_profit
        d['available_to_harvest'] = self.available_to_harvest
        d['roi_pct'] = self.roi_pct
        d['win_rate'] = self.win_rate
        d['profit_factor'] = self.profit_factor
        return d


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class PortfolioProfitEngine:
    """
    Central ledger for portfolio-level profit tracking.

    Usage:
        engine = get_portfolio_profit_engine()
        engine.record_trade("BTC-USD", pnl_usd=42.50, is_win=True)
        summary = engine.get_summary()
        harvested = engine.harvest_profits(amount=100.0)
        engine.reset_portfolio(new_base_capital=5000.0)
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "portfolio_profit_state.json"

    # Compounding: fraction of each profitable trade to reinvest automatically.
    # 0.0 = no compounding, 1.0 = full compounding.
    DEFAULT_COMPOUND_RATE = 0.75

    def __init__(self, base_capital: float = 0.0, compound_rate: float = DEFAULT_COMPOUND_RATE):
        self._lock = threading.RLock()
        self.compound_rate = max(0.0, min(1.0, compound_rate))
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not self._load_state():
            self._state = PortfolioProfitState(
                base_capital=base_capital,
                epoch_started=datetime.now().isoformat(),
                last_updated=datetime.now().isoformat(),
            )
            self._save_state()

        logger.info("=" * 70)
        logger.info("💼 Portfolio Profit Engine initialised")
        logger.info(f"   Epoch     : {self._state.epoch}")
        logger.info(f"   Net Profit: ${self._state.net_profit:.2f}")
        logger.info(f"   Compound  : {self.compound_rate * 100:.0f}%")
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        symbol: str,
        pnl_usd: float,
        is_win: bool,
        fees_usd: float = 0.0,
    ) -> None:
        """
        Record a completed trade and update the portfolio profit ledger.

        Args:
            symbol:    Trading pair, e.g. "BTC-USD"
            pnl_usd:   Net P&L in USD (negative for losses)
            is_win:    True if the trade was profitable
            fees_usd:  Exchange fees (optional; for tracking only)
        """
        with self._lock:
            s = self._state
            s.total_trades += 1
            s.total_fees += fees_usd

            if pnl_usd > 0:
                s.total_gross_profit += pnl_usd
                s.winning_trades += 1
                # Auto-compound a portion of the profit
                compound_amount = pnl_usd * self.compound_rate
                s.compounded_profit += compound_amount
                logger.info(
                    f"💰 Profit recorded: {symbol} +${pnl_usd:.2f}  "
                    f"compounded=${compound_amount:.2f}  "
                    f"TOTAL NET=${s.net_profit:.2f}"
                )
            else:
                s.total_gross_loss += abs(pnl_usd)
                logger.info(
                    f"📉 Loss recorded: {symbol} ${pnl_usd:.2f}  "
                    f"TOTAL NET=${s.net_profit:.2f}"
                )

            s.trades.append(
                TradeRecord(
                    timestamp=datetime.now().isoformat(),
                    symbol=symbol,
                    pnl_usd=pnl_usd,
                    is_win=is_win,
                    epoch=s.epoch,
                ).__dict__
            )
            s.last_updated = datetime.now().isoformat()
            self._save_state()

    def harvest_profits(self, amount: Optional[float] = None, note: str = "") -> float:
        """
        Harvest (withdraw) accumulated profits.

        Args:
            amount: USD amount to harvest. If None, harvest all available profit.
            note:   Optional annotation stored in the harvest log.

        Returns:
            Actual amount harvested (may be less than requested if insufficient).
        """
        with self._lock:
            s = self._state
            available = s.available_to_harvest
            if available <= 0:
                logger.warning("⚠️  No profit available to harvest.")
                return 0.0

            harvest_amount = amount if amount is not None else available
            harvest_amount = min(harvest_amount, available)

            if harvest_amount <= 0:
                logger.warning(f"⚠️  Requested harvest amount ${amount:.2f} <= 0. Skipping.")
                return 0.0

            s.harvested_profit += harvest_amount
            record = HarvestRecord(
                timestamp=datetime.now().isoformat(),
                amount_usd=harvest_amount,
                epoch=s.epoch,
                note=note,
            )
            s.harvest_log.append(record.__dict__)
            s.last_updated = datetime.now().isoformat()
            self._save_state()

            logger.info(
                f"🏦 Profit harvested: ${harvest_amount:.2f}  "
                f"| Total harvested this epoch: ${s.harvested_profit:.2f}  "
                f"| Available: ${s.available_to_harvest:.2f}"
            )
            return harvest_amount

    def reset_portfolio(self, new_base_capital: float = 0.0) -> Dict:
        """
        Reset the portfolio profit tracker to a fresh epoch.

        The previous epoch's summary is returned for audit purposes.
        Persistent state is overwritten with a new epoch.

        Args:
            new_base_capital: Starting capital for the new epoch.

        Returns:
            Summary dict of the completed (old) epoch.
        """
        with self._lock:
            old_summary = self._state.to_dict()
            old_epoch = self._state.epoch

            self._state = PortfolioProfitState(
                epoch=old_epoch + 1,
                base_capital=new_base_capital,
                epoch_started=datetime.now().isoformat(),
                last_updated=datetime.now().isoformat(),
            )
            self._save_state()

            logger.info("=" * 70)
            logger.info(f"🔄 Portfolio reset — new epoch {self._state.epoch} started")
            logger.info(f"   Previous net profit : ${old_summary['net_profit']:.2f}")
            logger.info(f"   Previous ROI        : {old_summary['roi_pct']:.2f}%")
            logger.info(f"   New base capital    : ${new_base_capital:.2f}")
            logger.info("=" * 70)

            return old_summary

    def get_summary(self) -> Dict:
        """Return a snapshot of the current portfolio profit state."""
        with self._lock:
            return self._state.to_dict()

    def get_harvest_log(self) -> List[Dict]:
        """Return all harvest events for the current epoch."""
        with self._lock:
            return list(self._state.harvest_log)

    def get_trade_log(self, limit: int = 50) -> List[Dict]:
        """Return the most recent trade records (newest first)."""
        with self._lock:
            return list(reversed(self._state.trades[-limit:]))

    def update_base_capital(self, capital: float) -> None:
        """Update the base capital for the current epoch (call on account sync)."""
        with self._lock:
            self._state.base_capital = capital
            self._state.last_updated = datetime.now().isoformat()
            self._save_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            with open(self.STATE_FILE, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as exc:
            logger.error(f"Failed to save portfolio profit state: {exc}")

    def _load_state(self) -> bool:
        if not self.STATE_FILE.exists():
            return False
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)

            # Strip computed properties that are not fields of PortfolioProfitState
            computed = {"net_profit", "available_to_harvest", "roi_pct", "win_rate", "profit_factor"}
            clean = {k: v for k, v in data.items() if k not in computed}

            self._state = PortfolioProfitState(**clean)
            logger.info(f"✅ Portfolio profit state loaded (epoch {self._state.epoch})")
            return True
        except Exception as exc:
            logger.warning(f"Failed to load portfolio profit state: {exc}")
            return False

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Generate a human-readable portfolio profit report."""
        s = self._state
        lines = [
            "",
            "=" * 80,
            "  NIJA PORTFOLIO PROFIT ENGINE — TOTAL PORTFOLIO PROFIT REPORT",
            "=" * 80,
            f"  Epoch              : {s.epoch}",
            f"  Epoch Started      : {s.epoch_started}",
            f"  Last Updated       : {s.last_updated}",
            "",
            "  💰 PROFIT SUMMARY",
            "-" * 80,
            f"  Base Capital       : ${s.base_capital:>14,.2f}",
            f"  Gross Profit       : ${s.total_gross_profit:>14,.2f}",
            f"  Gross Loss         : ${s.total_gross_loss:>14,.2f}",
            f"  ───────────────────────────────────────────",
            f"  NET PROFIT (TOTAL) : ${s.net_profit:>14,.2f}",
            f"  ROI                : {s.roi_pct:>14.2f} %",
            f"  Profit Factor      : {s.profit_factor:>14.2f}",
            "",
            "  🏦 HARVEST & COMPOUND",
            "-" * 80,
            f"  Harvested Profit   : ${s.harvested_profit:>14,.2f}",
            f"  Compounded Profit  : ${s.compounded_profit:>14,.2f}",
            f"  Available to Harvest: ${s.available_to_harvest:>13,.2f}",
            "",
            "  📊 TRADING PERFORMANCE",
            "-" * 80,
            f"  Total Trades       : {s.total_trades:>14,}",
            f"  Winning Trades     : {s.winning_trades:>14,}",
            f"  Win Rate           : {s.win_rate:>14.1f} %",
            f"  Total Fees Tracked : ${s.total_fees:>14,.2f}",
            "=" * 80,
            "",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[PortfolioProfitEngine] = None
_engine_lock = threading.Lock()


def get_portfolio_profit_engine(
    base_capital: float = 0.0,
    compound_rate: float = PortfolioProfitEngine.DEFAULT_COMPOUND_RATE,
) -> PortfolioProfitEngine:
    """
    Return the global PortfolioProfitEngine singleton.

    Creates one on first call; subsequent calls ignore constructor arguments
    (the persisted state is authoritative).
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = PortfolioProfitEngine(
                    base_capital=base_capital,
                    compound_rate=compound_rate,
                )
    return _engine_instance


# ---------------------------------------------------------------------------
# Quick demo / smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    engine = get_portfolio_profit_engine(base_capital=5000.0)

    engine.record_trade("BTC-USD", pnl_usd=120.50, is_win=True)
    engine.record_trade("ETH-USD", pnl_usd=-35.00, is_win=False)
    engine.record_trade("SOL-USD", pnl_usd=75.00, is_win=True)
    engine.record_trade("XRP-USD", pnl_usd=-10.00, is_win=False)
    engine.record_trade("DOGE-USD", pnl_usd=55.25, is_win=True)

    print(engine.get_report())

    harvested = engine.harvest_profits(amount=50.0, note="manual test harvest")
    print(f"\nHarvested: ${harvested:.2f}")
    print(f"Available after harvest: ${engine.get_summary()['available_to_harvest']:.2f}")

    old_epoch = engine.reset_portfolio(new_base_capital=5200.0)
    print(f"\nReset complete — previous epoch net profit was ${old_epoch['net_profit']:.2f}")
    print(engine.get_report())
