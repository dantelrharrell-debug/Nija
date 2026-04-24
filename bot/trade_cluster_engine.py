"""
NIJA Trade Cluster Engine
==========================

💎 Phase 2 Enhancement — Trade Clustering: Stack Wins in Strong Trends

Detects when the market is in a sustained trending phase and increases
position size to "stack" capital into consecutive winning setups.

Strategy
--------
A *cluster* is active when:
  - The bot has accumulated ``min_cluster_wins`` consecutive wins, AND
  - The current regime is BULL (or STRONG_TREND from any regime engine), AND
  - The trend-strength indicator (ADX) is above ``adx_threshold``.

When a cluster is active the engine returns a ``cluster_multiplier > 1.0``
(default range 1.0 – 1.5).  The multiplier ramps smoothly as consecutive
wins accumulate so that a long winning streak concentrates more capital into
the trend without a sudden jump.

Safety guards
-------------
- ``max_cluster_multiplier`` caps the boost (default 1.5×).
- Any single loss resets the consecutive-win counter to zero and deactivates
  the cluster immediately.
- An optional ``max_cluster_trades`` limits how many clustered trades can be
  stacked before forcing a cooldown period.
- Cooldown (``cooldown_trades``) is a minimum number of neutral trades that
  must pass before a new cluster can form after the previous one ends.

Integration
-----------
::

    from bot.trade_cluster_engine import get_trade_cluster_engine

    engine = get_trade_cluster_engine()

    # Before placing a trade — get sizing multiplier:
    mult = engine.get_cluster_multiplier(adx=38.5, regime="BULL")
    position_size *= mult

    # After a trade is closed — update state:
    engine.record_outcome(is_win=True, pnl_usd=45.20)

Author: NIJA Trading Systems
Version: 1.0 — Phase 2 Edition
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.trade_cluster")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DATA_DIR = Path("data")
_AUDIT_FILE = "trade_cluster_engine.jsonl"


class ClusterState(str, Enum):
    """Current clustering state."""
    IDLE = "idle"          # not enough wins yet
    BUILDING = "building"  # accumulating wins, multiplier ramping up
    ACTIVE = "active"      # fully active cluster — max multiplier applied
    COOLDOWN = "cooldown"  # post-cluster cooldown period


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ClusterConfig:
    """Configuration parameters for the Trade Cluster Engine."""

    # Minimum consecutive wins required before cluster becomes BUILDING
    min_cluster_wins: int = 3

    # Minimum consecutive wins to reach ACTIVE (full multiplier)
    full_cluster_wins: int = 5

    # Maximum position-size multiplier at peak cluster
    max_cluster_multiplier: float = 1.50

    # ADX threshold: trend must be this strong to allow clustering
    adx_threshold: float = 25.0

    # Regimes that qualify for clustering (case-insensitive)
    qualifying_regimes: tuple = ("BULL", "STRONG_TREND", "TRENDING")

    # Maximum consecutive clustered trades before forced cooldown
    max_cluster_trades: int = 10

    # Number of neutral trades required before a new cluster can start
    cooldown_trades: int = 2

    # If True, the engine checks both win streak AND ADX/regime
    require_regime_confirmation: bool = True


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

@dataclass
class ClusterStatus:
    """Snapshot of the current cluster state."""
    state: str
    consecutive_wins: int
    cluster_multiplier: float
    cooldown_remaining: int
    cluster_trades_this_run: int
    last_updated: str


class TradeClusterEngine:
    """
    Detects strong-trend clustering conditions and boosts position size.

    Thread-safe via ``threading.Lock``.
    """

    def __init__(
        self,
        config: Optional[ClusterConfig] = None,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._config = config or ClusterConfig()
        self._lock = threading.Lock()

        # State
        self._consecutive_wins: int = 0
        self._state: ClusterState = ClusterState.IDLE
        self._cooldown_remaining: int = 0
        self._cluster_trades_this_run: int = 0
        self._total_trades: int = 0

        # Audit log
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path = self._data_dir / _AUDIT_FILE

        logger.info(
            "🎯 TradeClusterEngine initialised — "
            "min_wins=%d full_wins=%d max_mult=%.2f× adx_thr=%.1f",
            self._config.min_cluster_wins,
            self._config.full_cluster_wins,
            self._config.max_cluster_multiplier,
            self._config.adx_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cluster_multiplier(
        self,
        adx: float = 0.0,
        regime: str = "UNKNOWN",
    ) -> float:
        """
        Return the position-size multiplier for the current cluster state.

        Parameters
        ----------
        adx:
            Current ADX value (directional movement strength).
        regime:
            Current market regime label (e.g. ``"BULL"``, ``"CHOP"``).

        Returns
        -------
        float
            Multiplier ≥ 1.0.  Returns 1.0 when the cluster is not active.
        """
        with self._lock:
            # Cooldown gate
            if self._state == ClusterState.COOLDOWN:
                return 1.0

            # Trend confirmation gate (optional)
            if self._config.require_regime_confirmation:
                regime_ok = regime.upper() in (
                    r.upper() for r in self._config.qualifying_regimes
                )
                adx_ok = adx >= self._config.adx_threshold
                if not (regime_ok and adx_ok):
                    return 1.0

            # Compute ramp-up multiplier
            wins = self._consecutive_wins
            if wins < self._config.min_cluster_wins:
                return 1.0

            # Linear ramp from 1.0 at min_wins to max_mult at full_wins
            ramp_range = max(
                1, self._config.full_cluster_wins - self._config.min_cluster_wins
            )
            ramp_position = min(
                wins - self._config.min_cluster_wins, ramp_range
            )
            multiplier = 1.0 + (
                (self._config.max_cluster_multiplier - 1.0)
                * ramp_position
                / ramp_range
            )
            multiplier = min(multiplier, self._config.max_cluster_multiplier)

            if multiplier > 1.0:
                logger.info(
                    "🔗 Trade Cluster (%s) — consecutive_wins=%d mult=%.2f× "
                    "[adx=%.1f regime=%s]",
                    self._state.value, wins, multiplier, adx, regime,
                )
            return round(multiplier, 4)

    def record_outcome(self, is_win: bool, pnl_usd: float = 0.0) -> None:
        """
        Update the cluster state after a trade closes.

        Parameters
        ----------
        is_win:
            Whether the trade was profitable.
        pnl_usd:
            Dollar P&L (used for audit logging only).
        """
        with self._lock:
            self._total_trades += 1
            cfg = self._config

            if self._state == ClusterState.COOLDOWN:
                self._cooldown_remaining = max(0, self._cooldown_remaining - 1)
                if self._cooldown_remaining == 0:
                    self._state = ClusterState.IDLE
                    logger.info("🔓 Trade Cluster cooldown complete — ready for new cluster")
                self._audit(is_win, pnl_usd)
                return

            if is_win:
                self._consecutive_wins += 1
                self._cluster_trades_this_run += 1

                # State transitions
                if self._consecutive_wins >= cfg.full_cluster_wins:
                    self._state = ClusterState.ACTIVE
                elif self._consecutive_wins >= cfg.min_cluster_wins:
                    self._state = ClusterState.BUILDING

                # Max cluster trades guard
                if (
                    self._state in (ClusterState.BUILDING, ClusterState.ACTIVE)
                    and self._cluster_trades_this_run >= cfg.max_cluster_trades
                ):
                    logger.info(
                        "⏸️  Trade Cluster cap reached (%d trades) — entering cooldown",
                        cfg.max_cluster_trades,
                    )
                    self._enter_cooldown()
            else:
                # Any loss resets the cluster immediately
                if self._state != ClusterState.IDLE:
                    logger.info(
                        "💔 Trade Cluster broken (loss after %d wins) — resetting",
                        self._consecutive_wins,
                    )
                self._consecutive_wins = 0
                self._cluster_trades_this_run = 0
                self._state = ClusterState.IDLE

            self._audit(is_win, pnl_usd)

    def get_status(self) -> ClusterStatus:
        """Return a snapshot of the current cluster status."""
        with self._lock:
            return ClusterStatus(
                state=self._state.value,
                consecutive_wins=self._consecutive_wins,
                cluster_multiplier=self._config.max_cluster_multiplier
                if self._state == ClusterState.ACTIVE
                else 1.0,
                cooldown_remaining=self._cooldown_remaining,
                cluster_trades_this_run=self._cluster_trades_this_run,
                last_updated=datetime.now(timezone.utc).isoformat(),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enter_cooldown(self) -> None:
        """Transition to COOLDOWN state."""
        self._state = ClusterState.COOLDOWN
        self._cooldown_remaining = self._config.cooldown_trades
        self._consecutive_wins = 0
        self._cluster_trades_this_run = 0

    def _audit(self, is_win: bool, pnl_usd: float) -> None:
        """Append a JSONL record to the audit log."""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "state": self._state.value,
            "consecutive_wins": self._consecutive_wins,
            "cluster_trades_this_run": self._cluster_trades_this_run,
            "cooldown_remaining": self._cooldown_remaining,
            "is_win": is_win,
            "pnl_usd": round(pnl_usd, 4),
            "total_trades": self._total_trades,
        }
        try:
            with self._audit_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[TradeClusterEngine] = None
_engine_lock = threading.Lock()


def get_trade_cluster_engine(
    config: Optional[ClusterConfig] = None,
    data_dir: Optional[Path] = None,
) -> TradeClusterEngine:
    """
    Return (or create) the module-level ``TradeClusterEngine`` singleton.

    Parameters are only used on the **first** call.
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = TradeClusterEngine(config=config, data_dir=data_dir)
    return _engine


__all__ = [
    "TradeClusterEngine",
    "ClusterConfig",
    "ClusterState",
    "ClusterStatus",
    "get_trade_cluster_engine",
]
