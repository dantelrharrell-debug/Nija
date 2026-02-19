"""
Portfolio-Level VaR Monitor
============================
Real-time Value at Risk (VaR) monitoring across the entire portfolio.

Provides two complementary VaR methods:

1. **Parametric VaR** – fast, assumes normal returns; used for intraday
   real-time estimates.
2. **Historical Simulation VaR** – non-parametric; uses rolling window of
   observed P&L scenarios; more accurate for fat-tailed crypto returns.

Both methods produce:
- VaR at 95 % confidence (1-day horizon)
- VaR at 99 % confidence (1-day horizon)
- Conditional VaR / Expected Shortfall (CVaR) at 95 % and 99 %
- Breach detection and callback notifications
- Continuous background monitoring thread

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.portfolio_var_monitor")

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------
DEFAULT_VAR_LIMIT_95_PCT: float = 0.05   # 5 % of portfolio value
DEFAULT_VAR_LIMIT_99_PCT: float = 0.08   # 8 % of portfolio value
DEFAULT_MAX_HISTORY: int = 500            # P&L snapshots retained
DEFAULT_MONITOR_INTERVAL: int = 60        # seconds between monitor cycles


def _to_json_safe(obj):
    """Recursively convert numpy scalars to plain Python types for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    return obj


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class VaRSnapshot:
    """Point-in-time VaR measurement for the portfolio."""
    timestamp: str
    portfolio_value: float

    # Parametric (normal-distribution) VaR
    parametric_var_95: float
    parametric_var_99: float
    parametric_cvar_95: float
    parametric_cvar_99: float

    # Historical-simulation VaR
    historical_var_95: float
    historical_var_99: float
    historical_cvar_95: float
    historical_cvar_99: float

    # Breaches
    var_95_breached: bool = False
    var_99_breached: bool = False

    # Supporting data
    num_positions: int = 0
    total_exposure_usd: float = 0.0
    scenario_count: int = 0

    def to_dict(self) -> Dict:
        return _to_json_safe(asdict(self))


@dataclass
class VaRBreach:
    """Record of a VaR limit breach."""
    timestamp: str
    confidence_level: str          # '95%' or '99%'
    var_value: float               # Actual VaR in USD
    var_limit: float               # Configured limit in USD
    portfolio_value: float
    method: str                    # 'parametric' or 'historical'
    acknowledged: bool = False

    def to_dict(self) -> Dict:
        return _to_json_safe(asdict(self))


# ---------------------------------------------------------------------------
# Core VaR Monitor
# ---------------------------------------------------------------------------

class PortfolioVaRMonitor:
    """
    Continuous, portfolio-level Value at Risk monitor.

    Usage
    -----
    monitor = PortfolioVaRMonitor()

    # Register callbacks that supply live data
    monitor.set_portfolio_callbacks(
        portfolio_value_fn=lambda: broker.get_total_value(),
        positions_fn=lambda: broker.get_open_positions(),   # [{'symbol', 'size_usd', 'pnl'}]
    )

    monitor.start()                  # background thread
    snapshot = monitor.get_latest()  # latest VaR snapshot
    monitor.stop()
    """

    def __init__(
        self,
        var_limit_95_pct: float = DEFAULT_VAR_LIMIT_95_PCT,
        var_limit_99_pct: float = DEFAULT_VAR_LIMIT_99_PCT,
        monitor_interval: int = DEFAULT_MONITOR_INTERVAL,
        max_pnl_history: int = DEFAULT_MAX_HISTORY,
        daily_volatility_assumption: float = 0.02,   # 2 % per position per day
    ):
        """
        Parameters
        ----------
        var_limit_95_pct : float
            VaR limit at 95 % confidence as a fraction of portfolio value (default 0.05 = 5 %).
        var_limit_99_pct : float
            VaR limit at 99 % confidence as a fraction of portfolio value (default 0.08 = 8 %).
        monitor_interval : int
            Seconds between VaR recalculation cycles (default 60).
        max_pnl_history : int
            Number of P&L return observations retained for historical simulation (default 500).
        daily_volatility_assumption : float
            Assumed daily return volatility per position when no price history is available (default 0.02).
        """
        self.var_limit_95_pct = var_limit_95_pct
        self.var_limit_99_pct = var_limit_99_pct
        self.monitor_interval = monitor_interval
        self.max_pnl_history = max_pnl_history
        self.daily_volatility_assumption = daily_volatility_assumption

        # Callbacks
        self._portfolio_value_fn: Optional[Callable[[], float]] = None
        self._positions_fn: Optional[Callable[[], List[Dict]]] = None

        # History buffers
        self._portfolio_pnl_returns: deque = deque(maxlen=max_pnl_history)
        self._last_portfolio_value: Optional[float] = None
        self._snapshots: List[VaRSnapshot] = []
        self._breaches: List[VaRBreach] = []

        # Notification callbacks
        self._breach_callbacks: List[Callable[[VaRBreach], None]] = []

        # Threading
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._latest_snapshot: Optional[VaRSnapshot] = None

        logger.info("✅ PortfolioVaRMonitor initialised")

    # ------------------------------------------------------------------
    # Public configuration API
    # ------------------------------------------------------------------

    def set_portfolio_callbacks(
        self,
        portfolio_value_fn: Callable[[], float],
        positions_fn: Callable[[], List[Dict]],
    ) -> None:
        """
        Register callables that supply live portfolio data.

        Parameters
        ----------
        portfolio_value_fn : () -> float
            Returns current total portfolio value in USD.
        positions_fn : () -> list[dict]
            Returns list of open positions, each as a dict with keys:
            ``{'symbol': str, 'size_usd': float, 'pnl': float}``
        """
        self._portfolio_value_fn = portfolio_value_fn
        self._positions_fn = positions_fn

    def add_breach_callback(self, callback: Callable[[VaRBreach], None]) -> None:
        """Register a callback to be invoked on every VaR breach."""
        self._breach_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Direct data ingestion (alternative to callbacks)
    # ------------------------------------------------------------------

    def record_portfolio_return(self, portfolio_value: float) -> None:
        """
        Record a portfolio value observation, deriving the period return.

        Call this regularly (e.g., every minute) to build the historical
        P&L return series used by the historical simulation method.
        """
        with self._lock:
            if self._last_portfolio_value is not None and self._last_portfolio_value > 0:
                ret = (portfolio_value - self._last_portfolio_value) / self._last_portfolio_value
                self._portfolio_pnl_returns.append(ret)
            self._last_portfolio_value = portfolio_value

    # ------------------------------------------------------------------
    # VaR calculation methods
    # ------------------------------------------------------------------

    def calculate_parametric_var(
        self,
        portfolio_value: float,
        positions: List[Dict],
    ) -> Tuple[float, float, float, float]:
        """
        Parametric (normal distribution) VaR calculation.

        Parameters
        ----------
        portfolio_value : float
            Total portfolio value in USD.
        positions : list[dict]
            Open positions with ``size_usd`` key.

        Returns
        -------
        (var_95, var_99, cvar_95, cvar_99) – all in USD.
        """
        if not positions or portfolio_value <= 0:
            return 0.0, 0.0, 0.0, 0.0

        total_exposure = sum(float(p.get("size_usd", 0.0)) for p in positions)
        n = len(positions)

        # Portfolio daily volatility: independent positions → σ_p = σ × √n
        portfolio_vol = self.daily_volatility_assumption * np.sqrt(max(n, 1))

        # VaR = exposure × σ_p × z  (one-tailed, in USD)
        var_95 = total_exposure * portfolio_vol * 1.6449   # z_{0.95}
        var_99 = total_exposure * portfolio_vol * 2.3263   # z_{0.99}

        # CVaR for normal distribution: CVaR = σ × φ(z) / (1-α)
        # φ is the standard normal PDF; φ(1.645) ≈ 0.103, φ(2.326) ≈ 0.027
        cvar_95 = total_exposure * portfolio_vol * 0.103 / 0.05   # ≈ var_95 × 1.252
        cvar_99 = total_exposure * portfolio_vol * 0.027 / 0.01   # ≈ var_99 × 1.159

        return var_95, var_99, cvar_95, cvar_99

    def calculate_historical_var(
        self,
        portfolio_value: float,
    ) -> Tuple[float, float, float, float]:
        """
        Historical simulation VaR.

        Uses the rolling P&L return series recorded via
        ``record_portfolio_return`` (or the monitoring thread).

        Parameters
        ----------
        portfolio_value : float
            Current portfolio value (used to convert returns → USD P&L).

        Returns
        -------
        (var_95, var_99, cvar_95, cvar_99) – all in USD.
        Returns zeros when fewer than 30 observations are available.
        """
        with self._lock:
            returns = list(self._portfolio_pnl_returns)

        if len(returns) < 30 or portfolio_value <= 0:
            return 0.0, 0.0, 0.0, 0.0

        arr = np.array(returns, dtype=float)
        losses = -arr * portfolio_value   # positive = loss

        # Sort losses descending
        losses_sorted = np.sort(losses)[::-1]
        n = len(losses_sorted)

        idx_95 = int(np.ceil(0.05 * n)) - 1
        idx_99 = int(np.ceil(0.01 * n)) - 1

        idx_95 = max(0, min(idx_95, n - 1))
        idx_99 = max(0, min(idx_99, n - 1))

        var_95 = float(losses_sorted[idx_95])
        var_99 = float(losses_sorted[idx_99])

        cvar_95 = float(np.mean(losses_sorted[:idx_95 + 1])) if idx_95 >= 0 else var_95
        cvar_99 = float(np.mean(losses_sorted[:idx_99 + 1])) if idx_99 >= 0 else var_99

        # Clamp to non-negative (losses can't be negative VaR)
        var_95 = max(var_95, 0.0)
        var_99 = max(var_99, 0.0)
        cvar_95 = max(cvar_95, var_95)
        cvar_99 = max(cvar_99, var_99)

        return var_95, var_99, cvar_95, cvar_99

    def compute_snapshot(
        self,
        portfolio_value: float,
        positions: List[Dict],
    ) -> VaRSnapshot:
        """
        Compute a full VaR snapshot synchronously.

        Parameters
        ----------
        portfolio_value : float
            Total portfolio value in USD.
        positions : list[dict]
            Open positions list.

        Returns
        -------
        VaRSnapshot
        """
        p_var95, p_var99, p_cvar95, p_cvar99 = self.calculate_parametric_var(
            portfolio_value, positions
        )
        h_var95, h_var99, h_cvar95, h_cvar99 = self.calculate_historical_var(
            portfolio_value
        )

        limit_95 = portfolio_value * self.var_limit_95_pct
        limit_99 = portfolio_value * self.var_limit_99_pct

        # Use parametric as primary when insufficient history, else historical
        with self._lock:
            history_len = len(self._portfolio_pnl_returns)

        if history_len >= 30:
            primary_var95 = h_var95
            primary_var99 = h_var99
            method_used = "historical"
        else:
            primary_var95 = p_var95
            primary_var99 = p_var99
            method_used = "parametric"

        breach_95 = bool(primary_var95 > limit_95 and portfolio_value > 0)
        breach_99 = bool(primary_var99 > limit_99 and portfolio_value > 0)

        total_exposure = sum(float(p.get("size_usd", 0.0)) for p in positions)

        snapshot = VaRSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            portfolio_value=float(portfolio_value),
            parametric_var_95=float(p_var95),
            parametric_var_99=float(p_var99),
            parametric_cvar_95=float(p_cvar95),
            parametric_cvar_99=float(p_cvar99),
            historical_var_95=float(h_var95),
            historical_var_99=float(h_var99),
            historical_cvar_95=float(h_cvar95),
            historical_cvar_99=float(h_cvar99),
            var_95_breached=breach_95,
            var_99_breached=breach_99,
            num_positions=len(positions),
            total_exposure_usd=float(total_exposure),
            scenario_count=history_len,
        )

        # Persist & notify
        with self._lock:
            self._latest_snapshot = snapshot
            self._snapshots.append(snapshot)
            if len(self._snapshots) > 1000:
                self._snapshots = self._snapshots[-1000:]

        if breach_95:
            self._handle_breach(primary_var95, limit_95, portfolio_value, "95%", method_used)
        if breach_99:
            self._handle_breach(primary_var99, limit_99, portfolio_value, "99%", method_used)

        return snapshot

    # ------------------------------------------------------------------
    # Breach handling
    # ------------------------------------------------------------------

    def _handle_breach(
        self,
        var_value: float,
        var_limit: float,
        portfolio_value: float,
        confidence: str,
        method: str,
    ) -> None:
        breach = VaRBreach(
            timestamp=datetime.now(timezone.utc).isoformat(),
            confidence_level=confidence,
            var_value=var_value,
            var_limit=var_limit,
            portfolio_value=portfolio_value,
            method=method,
        )
        with self._lock:
            self._breaches.append(breach)
            if len(self._breaches) > 500:
                self._breaches = self._breaches[-500:]

        logger.warning(
            "⚠️  VaR BREACH [%s] – VaR: $%.2f  Limit: $%.2f  (%.1f%% of portfolio)  Method: %s",
            confidence,
            var_value,
            var_limit,
            100.0 * var_value / portfolio_value if portfolio_value else 0,
            method,
        )

        for cb in self._breach_callbacks:
            try:
                cb(breach)
            except Exception as exc:
                logger.error("Breach callback error: %s", exc)

    # ------------------------------------------------------------------
    # Background monitoring thread
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background VaR monitoring thread."""
        if self._running:
            logger.warning("PortfolioVaRMonitor already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, name="VaRMonitor", daemon=True
        )
        self._thread.start()
        logger.info("🔄 PortfolioVaRMonitor started (interval=%ds)", self.monitor_interval)

    def stop(self) -> None:
        """Stop the background monitoring thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(self.monitor_interval + 5, 15))
        logger.info("🛑 PortfolioVaRMonitor stopped")

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._do_monitor_cycle()
            except Exception as exc:
                logger.error("VaR monitor cycle error: %s", exc, exc_info=True)
            time.sleep(self.monitor_interval)

    def _do_monitor_cycle(self) -> None:
        if self._portfolio_value_fn is None or self._positions_fn is None:
            return

        portfolio_value = self._portfolio_value_fn()
        positions = self._positions_fn()

        # Record the return for historical simulation
        self.record_portfolio_return(portfolio_value)

        # Compute and store snapshot
        snapshot = self.compute_snapshot(portfolio_value, positions)

        logger.debug(
            "VaR cycle – p_var95=$%.2f h_var95=$%.2f positions=%d history=%d",
            snapshot.parametric_var_95,
            snapshot.historical_var_95,
            snapshot.num_positions,
            snapshot.scenario_count,
        )

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_latest(self) -> Optional[VaRSnapshot]:
        """Return the most recent VaR snapshot (or None if not yet computed)."""
        with self._lock:
            return self._latest_snapshot

    def get_history(self, limit: int = 100) -> List[VaRSnapshot]:
        """Return up to *limit* most recent VaR snapshots."""
        with self._lock:
            return list(self._snapshots[-limit:])

    def get_breaches(self, limit: int = 50) -> List[VaRBreach]:
        """Return up to *limit* most recent VaR breaches."""
        with self._lock:
            return list(self._breaches[-limit:])

    def get_summary(self) -> Dict:
        """Return a JSON-serialisable summary of current VaR state."""
        latest = self.get_latest()
        breaches = self.get_breaches(10)
        with self._lock:
            history_len = len(self._portfolio_pnl_returns)

        return {
            "status": "active" if self._running else "stopped",
            "monitor_interval_seconds": self.monitor_interval,
            "var_limits": {
                "var_95_pct": self.var_limit_95_pct,
                "var_99_pct": self.var_limit_99_pct,
            },
            "pnl_history_count": history_len,
            "latest_snapshot": latest.to_dict() if latest else None,
            "recent_breaches": [b.to_dict() for b in breaches],
            "breach_count_total": len(self._breaches),
        }

    @property
    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_var_monitor_instance: Optional[PortfolioVaRMonitor] = None
_var_monitor_lock = threading.Lock()


def get_portfolio_var_monitor(
    var_limit_95_pct: float = DEFAULT_VAR_LIMIT_95_PCT,
    var_limit_99_pct: float = DEFAULT_VAR_LIMIT_99_PCT,
    monitor_interval: int = DEFAULT_MONITOR_INTERVAL,
    reset: bool = False,
) -> PortfolioVaRMonitor:
    """
    Return (or create) the global PortfolioVaRMonitor singleton.

    Parameters
    ----------
    var_limit_95_pct : float
        VaR limit at 95 % confidence as fraction of portfolio (e.g. 0.05).
    var_limit_99_pct : float
        VaR limit at 99 % confidence as fraction of portfolio (e.g. 0.08).
    monitor_interval : int
        Background thread cycle interval in seconds.
    reset : bool
        If True, stops any existing instance and creates a fresh one.
    """
    global _var_monitor_instance

    with _var_monitor_lock:
        if reset and _var_monitor_instance is not None:
            _var_monitor_instance.stop()
            _var_monitor_instance = None

        if _var_monitor_instance is None:
            _var_monitor_instance = PortfolioVaRMonitor(
                var_limit_95_pct=var_limit_95_pct,
                var_limit_99_pct=var_limit_99_pct,
                monitor_interval=monitor_interval,
            )

    return _var_monitor_instance
