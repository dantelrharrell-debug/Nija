"""
NIJA Auto-Reinvest Engine
==========================

Automatically splits realised profits into:
  1. **Reinvest bucket** — returned to trading capital for compounding
  2. **Withdraw bucket** — extracted as safe profit (configurable fraction)

Key behaviours:
- Configurable reinvest / withdraw split (default 75% / 25%)
- Minimum profit threshold before any action is taken (default $5)
- Per-trade and cumulative tracking with JSON persistence
- Thread-safe singleton via ``get_auto_reinvest_engine()``
- Integrates with ``PortfolioProfitEngine`` when available

Usage
-----
    from auto_reinvest_engine import get_auto_reinvest_engine

    engine = get_auto_reinvest_engine()
    decision = engine.process_profit(symbol="BTC-USD", gross_profit=50.0, fees=0.75)
    # decision.reinvest_usd  → added back to capital
    # decision.withdraw_usd  → scheduled for withdrawal

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("nija.auto_reinvest")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ReinvestConfig:
    """
    Configuration for the Auto-Reinvest Engine.

    Attributes
    ----------
    reinvest_fraction : float
        Fraction of net profit to reinvest (0–1). Default 0.75 (75%).
    withdraw_fraction : float
        Fraction of net profit to withdraw/preserve. Default 0.25 (25%).
    min_profit_threshold : float
        Minimum net profit (USD) before processing a split. Trades below
        this threshold are tracked but no split is applied.
    max_withdraw_per_cycle : float
        Maximum USD to withdraw in a single call (guards against huge
        windfall events draining capital unexpectedly). 0 = no cap.
    """

    reinvest_fraction: float = 0.75
    withdraw_fraction: float = 0.25
    min_profit_threshold: float = 5.0
    max_withdraw_per_cycle: float = 0.0  # 0 = unlimited


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ReinvestDecision:
    """Result of a single profit-processing call."""
    symbol: str
    gross_profit: float
    fees: float
    net_profit: float
    reinvest_usd: float
    withdraw_usd: float
    skipped: bool  # True when net_profit < min_profit_threshold
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class EngineState:
    """Persistent state for the Auto-Reinvest Engine."""
    total_processed: float = 0.0
    total_reinvested: float = 0.0
    total_withdrawn: float = 0.0
    total_fees: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    history: List[dict] = field(default_factory=list)
    last_updated: Optional[str] = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AutoReinvestEngine:
    """
    Auto-withdraw + reinvest strategy engine.

    Splits every profitable trade closure into a reinvest portion (goes back
    into trading capital) and a withdrawal portion (locked profit reserve).
    """

    DATA_DIR = Path(os.environ.get("NIJA_DATA_DIR", "/tmp/nija_monitoring"))
    STATE_FILE = DATA_DIR / "auto_reinvest_state.json"
    MAX_HISTORY = 500  # Rolling history window

    def __init__(self, config: Optional[ReinvestConfig] = None) -> None:
        self.config = config or ReinvestConfig()
        self._lock = threading.Lock()
        self._state = self._load_state()
        logger.info(
            "💰 AutoReinvestEngine initialised — reinvest=%.0f%% withdraw=%.0f%% "
            "min_threshold=$%.2f",
            self.config.reinvest_fraction * 100,
            self.config.withdraw_fraction * 100,
            self.config.min_profit_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_profit(
        self,
        symbol: str,
        gross_profit: float,
        fees: float = 0.0,
        is_win: bool = True,
    ) -> ReinvestDecision:
        """
        Process realised profit from a closed trade.

        Parameters
        ----------
        symbol : str
            Trading pair (e.g. "BTC-USD").
        gross_profit : float
            Pre-fee profit in USD (may be negative for a loss).
        fees : float
            Transaction fees in USD (always positive).
        is_win : bool
            Whether this trade was profitable overall.

        Returns
        -------
        ReinvestDecision
            Contains the split amounts and metadata.
        """
        net_profit = gross_profit - fees

        with self._lock:
            self._state.trade_count += 1
            self._state.total_fees += fees
            if is_win:
                self._state.win_count += 1

            # Only split if net profit exceeds the threshold
            if net_profit < self.config.min_profit_threshold:
                decision = ReinvestDecision(
                    symbol=symbol,
                    gross_profit=gross_profit,
                    fees=fees,
                    net_profit=net_profit,
                    reinvest_usd=0.0,
                    withdraw_usd=0.0,
                    skipped=True,
                    reason=(
                        f"net_profit ${net_profit:.4f} < "
                        f"threshold ${self.config.min_profit_threshold:.2f}"
                    ),
                )
            else:
                reinvest_usd = net_profit * self.config.reinvest_fraction
                withdraw_usd = net_profit * self.config.withdraw_fraction

                # Apply per-cycle withdrawal cap if configured
                if self.config.max_withdraw_per_cycle > 0:
                    withdraw_usd = min(withdraw_usd, self.config.max_withdraw_per_cycle)
                    # Re-allocate capped remainder to reinvest
                    reinvest_usd = net_profit - withdraw_usd

                self._state.total_processed += net_profit
                self._state.total_reinvested += reinvest_usd
                self._state.total_withdrawn += withdraw_usd

                decision = ReinvestDecision(
                    symbol=symbol,
                    gross_profit=gross_profit,
                    fees=fees,
                    net_profit=net_profit,
                    reinvest_usd=reinvest_usd,
                    withdraw_usd=withdraw_usd,
                    skipped=False,
                    reason="profit split applied",
                )

                logger.info(
                    "📈 AutoReinvest [%s] net=$%.4f → reinvest=$%.4f withdraw=$%.4f",
                    symbol,
                    net_profit,
                    reinvest_usd,
                    withdraw_usd,
                )

            # Record in rolling history
            self._state.history.append(asdict(decision))
            if len(self._state.history) > self.MAX_HISTORY:
                self._state.history = self._state.history[-self.MAX_HISTORY:]

            self._state.last_updated = datetime.utcnow().isoformat()
            self._save_state()

        return decision

    def get_state(self) -> dict:
        """Return a copy of the current engine state as a plain dict."""
        with self._lock:
            return {
                "total_processed": self._state.total_processed,
                "total_reinvested": self._state.total_reinvested,
                "total_withdrawn": self._state.total_withdrawn,
                "total_fees": self._state.total_fees,
                "trade_count": self._state.trade_count,
                "win_count": self._state.win_count,
                "win_rate": (
                    self._state.win_count / self._state.trade_count * 100.0
                    if self._state.trade_count > 0 else 0.0
                ),
                "reinvest_fraction": self.config.reinvest_fraction,
                "withdraw_fraction": self.config.withdraw_fraction,
                "last_updated": self._state.last_updated,
                "history": list(self._state.history),
            }

    def get_summary_text(self) -> str:
        """Human-readable one-line summary for logs / banners."""
        s = self._state
        win_rate = (s.win_count / s.trade_count * 100.0) if s.trade_count > 0 else 0.0
        return (
            f"AutoReinvest | trades={s.trade_count} win={win_rate:.1f}% "
            f"processed=${s.total_processed:.2f} "
            f"reinvested=${s.total_reinvested:.2f} "
            f"withdrawn=${s.total_withdrawn:.2f}"
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_state(self) -> EngineState:
        try:
            self.DATA_DIR.mkdir(parents=True, exist_ok=True)
            if self.STATE_FILE.exists():
                raw = json.loads(self.STATE_FILE.read_text())
                return EngineState(
                    total_processed=raw.get("total_processed", 0.0),
                    total_reinvested=raw.get("total_reinvested", 0.0),
                    total_withdrawn=raw.get("total_withdrawn", 0.0),
                    total_fees=raw.get("total_fees", 0.0),
                    trade_count=raw.get("trade_count", 0),
                    win_count=raw.get("win_count", 0),
                    history=raw.get("history", []),
                    last_updated=raw.get("last_updated"),
                )
        except Exception as exc:
            logger.warning("Could not load AutoReinvest state: %s", exc)
        return EngineState()

    def _save_state(self) -> None:
        try:
            data = {
                "total_processed": self._state.total_processed,
                "total_reinvested": self._state.total_reinvested,
                "total_withdrawn": self._state.total_withdrawn,
                "total_fees": self._state.total_fees,
                "trade_count": self._state.trade_count,
                "win_count": self._state.win_count,
                "history": self._state.history,
                "last_updated": self._state.last_updated,
            }
            self.STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning("Could not save AutoReinvest state: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[AutoReinvestEngine] = None
_engine_lock = threading.Lock()


def get_auto_reinvest_engine(config: Optional[ReinvestConfig] = None) -> AutoReinvestEngine:
    """
    Return the singleton AutoReinvestEngine instance.

    Parameters
    ----------
    config : ReinvestConfig, optional
        Passed only on first call; ignored on subsequent calls.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = AutoReinvestEngine(config)
    return _engine_instance
