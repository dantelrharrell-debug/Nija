"""
Real-Time Risk Dashboard
=========================
Aggregates all risk signals into a single, unified real-time dashboard.

Combines:
- Portfolio-level VaR (95 % and 99 %) from PortfolioVaRMonitor
- Portfolio exposure and drawdown metrics from PortfolioRiskEngine
- Active risk alarms from RiskAlarmSystem
- Continuous background refresh with configurable interval

Exposes:
- ``RiskDashboard`` class for in-process use
- ``register_risk_dashboard_routes(app)`` to add REST endpoints to an
  existing Flask application

REST endpoints added:
  GET  /api/v1/risk/dashboard       – complete real-time snapshot
  GET  /api/v1/risk/var             – VaR metrics only
  GET  /api/v1/risk/var/history     – VaR history (query param: limit)
  GET  /api/v1/risk/var/breaches    – recent VaR breaches
  GET  /api/v1/risk/exposure        – portfolio exposure metrics
  GET  /api/v1/risk/alarms          – active risk alarms

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nija.risk_dashboard")

# ---------------------------------------------------------------------------
# Lazy-import helpers
# ---------------------------------------------------------------------------

def _import_var_monitor():
    try:
        from portfolio_var_monitor import get_portfolio_var_monitor, PortfolioVaRMonitor
        return get_portfolio_var_monitor, PortfolioVaRMonitor
    except ImportError:
        from bot.portfolio_var_monitor import get_portfolio_var_monitor, PortfolioVaRMonitor
        return get_portfolio_var_monitor, PortfolioVaRMonitor


def _import_portfolio_risk_engine():
    try:
        from portfolio_risk_engine import get_portfolio_risk_engine, PortfolioRiskEngine
        return get_portfolio_risk_engine, PortfolioRiskEngine
    except ImportError:
        try:
            from bot.portfolio_risk_engine import get_portfolio_risk_engine, PortfolioRiskEngine
            return get_portfolio_risk_engine, PortfolioRiskEngine
        except ImportError:
            return None, None


def _import_risk_alarm_system():
    try:
        from risk_alarm_system import get_risk_alarm_system
        return get_risk_alarm_system
    except ImportError:
        try:
            from bot.risk_alarm_system import get_risk_alarm_system
            return get_risk_alarm_system
        except ImportError:
            return None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

def _to_json_safe(obj):
    """Recursively convert numpy scalars to plain Python types for JSON serialisation."""
    try:
        import numpy as np
        np_bool = np.bool_
        np_int = np.integer
        np_float = np.floating
    except ImportError:
        np_bool = np_int = np_float = type(None)  # no numpy – nothing to convert

    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, np_bool):
        return bool(obj)
    if isinstance(obj, np_int):
        return int(obj)
    if isinstance(obj, np_float):
        return float(obj)
    return obj


@dataclass
class RiskDashboardSnapshot:
    """A complete point-in-time risk dashboard snapshot."""
    timestamp: str

    # --- VaR section ---
    var_available: bool
    parametric_var_95_usd: float
    parametric_var_99_usd: float
    historical_var_95_usd: float
    historical_var_99_usd: float
    cvar_95_usd: float
    cvar_99_usd: float
    var_95_breached: bool
    var_99_breached: bool
    var_95_limit_usd: float
    var_99_limit_usd: float
    pnl_scenario_count: int

    # --- Exposure / portfolio section ---
    portfolio_value_usd: float
    total_exposure_usd: float
    total_exposure_pct: float
    num_open_positions: int
    long_exposure_usd: float
    short_exposure_usd: float
    net_exposure_usd: float
    correlation_risk_score: float       # 0–1, higher = worse
    diversification_ratio: float
    max_sector_exposure_pct: float

    # --- Drawdown section ---
    current_drawdown_pct: float

    # --- Alarm section ---
    active_alarm_count: int
    critical_alarm_count: int
    alarms_summary: List[Dict]

    # --- Overall health ---
    risk_level: str   # 'GREEN', 'YELLOW', 'ORANGE', 'RED'
    risk_score: float  # 0–100 (0 = no risk, 100 = maximum risk)

    def to_dict(self) -> Dict:
        return _to_json_safe(asdict(self))


# ---------------------------------------------------------------------------
# Core dashboard class
# ---------------------------------------------------------------------------

class RiskDashboard:
    """
    Real-time risk dashboard that aggregates VaR, exposure, and alarm data.

    Usage
    -----
    dashboard = RiskDashboard()

    # Supply live data via callbacks
    dashboard.set_portfolio_callbacks(
        portfolio_value_fn=lambda: broker.get_total_value(),
        positions_fn=lambda: broker.get_open_positions(),
        drawdown_fn=lambda: risk_manager.get_current_drawdown_pct(),
    )

    dashboard.start()              # background auto-refresh
    snapshot = dashboard.get_snapshot()
    dashboard.stop()
    """

    def __init__(
        self,
        refresh_interval: int = 60,
        var_limit_95_pct: float = 0.05,
        var_limit_99_pct: float = 0.08,
    ):
        """
        Parameters
        ----------
        refresh_interval : int
            Seconds between automatic dashboard refreshes (default 60).
        var_limit_95_pct : float
            VaR limit at 95 % confidence as a fraction of portfolio value.
        var_limit_99_pct : float
            VaR limit at 99 % confidence as a fraction of portfolio value.
        """
        self.refresh_interval = refresh_interval
        self.var_limit_95_pct = var_limit_95_pct
        self.var_limit_99_pct = var_limit_99_pct

        # Data callbacks
        self._portfolio_value_fn: Optional[Callable[[], float]] = None
        self._positions_fn: Optional[Callable[[], List[Dict]]] = None
        self._drawdown_fn: Optional[Callable[[], float]] = None

        # VaR monitor (lazy-init)
        self._var_monitor = None
        self._portfolio_risk_engine = None
        self._alarm_system = None

        # State
        self._latest_snapshot: Optional[RiskDashboardSnapshot] = None
        self._snapshot_history: List[RiskDashboardSnapshot] = []
        self._lock = threading.Lock()

        # Background thread
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._init_subsystems()
        logger.info("✅ RiskDashboard initialised (refresh=%ds)", refresh_interval)

    def _init_subsystems(self) -> None:
        """Lazily initialise integrated subsystems."""
        try:
            get_var_monitor, _ = _import_var_monitor()
            self._var_monitor = get_var_monitor(
                var_limit_95_pct=self.var_limit_95_pct,
                var_limit_99_pct=self.var_limit_99_pct,
            )
        except Exception as exc:
            logger.warning("VaR monitor unavailable: %s", exc)

        try:
            get_engine, _ = _import_portfolio_risk_engine()
            if get_engine:
                self._portfolio_risk_engine = get_engine()
        except Exception as exc:
            logger.warning("PortfolioRiskEngine unavailable: %s", exc)

        try:
            get_alarms = _import_risk_alarm_system()
            if get_alarms:
                self._alarm_system = get_alarms()
        except Exception as exc:
            logger.warning("RiskAlarmSystem unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def set_portfolio_callbacks(
        self,
        portfolio_value_fn: Callable[[], float],
        positions_fn: Callable[[], List[Dict]],
        drawdown_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        """
        Register callables that supply live portfolio data.

        Parameters
        ----------
        portfolio_value_fn : () -> float
            Returns current total portfolio value in USD.
        positions_fn : () -> list[dict]
            Returns open positions as list of dicts with at minimum
            ``{'symbol': str, 'size_usd': float}``.
        drawdown_fn : () -> float, optional
            Returns current portfolio drawdown as a percentage (0-100).
        """
        self._portfolio_value_fn = portfolio_value_fn
        self._positions_fn = positions_fn
        self._drawdown_fn = drawdown_fn

        # Pass callbacks to the VaR monitor as well
        if self._var_monitor is not None:
            self._var_monitor.set_portfolio_callbacks(
                portfolio_value_fn=portfolio_value_fn,
                positions_fn=positions_fn,
            )

    # ------------------------------------------------------------------
    # Snapshot computation
    # ------------------------------------------------------------------

    def compute_snapshot(self) -> RiskDashboardSnapshot:
        """
        Compute a real-time risk dashboard snapshot synchronously.

        Returns
        -------
        RiskDashboardSnapshot
        """
        # Gather live data
        portfolio_value = 0.0
        positions: List[Dict] = []
        drawdown_pct = 0.0

        if self._portfolio_value_fn:
            try:
                portfolio_value = float(self._portfolio_value_fn())
            except Exception as exc:
                logger.error("portfolio_value_fn error: %s", exc)

        if self._positions_fn:
            try:
                positions = list(self._positions_fn())
            except Exception as exc:
                logger.error("positions_fn error: %s", exc)

        if self._drawdown_fn:
            try:
                drawdown_pct = float(self._drawdown_fn())
            except Exception as exc:
                logger.error("drawdown_fn error: %s", exc)

        # --- VaR ---
        var_snap = None
        if self._var_monitor is not None:
            try:
                var_snap = self._var_monitor.compute_snapshot(portfolio_value, positions)
            except Exception as exc:
                logger.error("VaR compute error: %s", exc)

        p_var95 = var_snap.parametric_var_95 if var_snap else 0.0
        p_var99 = var_snap.parametric_var_99 if var_snap else 0.0
        h_var95 = var_snap.historical_var_95 if var_snap else 0.0
        h_var99 = var_snap.historical_var_99 if var_snap else 0.0
        p_cvar95 = var_snap.parametric_cvar_95 if var_snap else 0.0
        p_cvar99 = var_snap.parametric_cvar_99 if var_snap else 0.0
        var_95_breached = var_snap.var_95_breached if var_snap else False
        var_99_breached = var_snap.var_99_breached if var_snap else False
        scenario_count = var_snap.scenario_count if var_snap else 0

        var_95_limit = portfolio_value * self.var_limit_95_pct
        var_99_limit = portfolio_value * self.var_limit_99_pct

        # --- Portfolio exposure ---
        total_exposure = sum(float(p.get("size_usd", 0.0)) for p in positions)
        long_exposure = sum(
            float(p.get("size_usd", 0.0))
            for p in positions
            if p.get("direction", "long") == "long"
        )
        short_exposure = sum(
            float(p.get("size_usd", 0.0))
            for p in positions
            if p.get("direction") == "short"
        )
        net_exposure = long_exposure - short_exposure
        exposure_pct = total_exposure / portfolio_value if portfolio_value > 0 else 0.0

        # Pull richer metrics from PortfolioRiskEngine if available
        corr_risk = 0.0
        div_ratio = 0.0
        max_sector_exp = 0.0
        if self._portfolio_risk_engine is not None:
            try:
                metrics = self._portfolio_risk_engine.calculate_portfolio_metrics(portfolio_value)
                corr_risk = metrics.correlation_risk
                div_ratio = metrics.diversification_ratio
                max_sector_exp = metrics.max_correlated_exposure
            except Exception as exc:
                logger.debug("PortfolioRiskEngine metrics error: %s", exc)

        # --- Alarms ---
        active_alarms: List[Any] = []
        if self._alarm_system is not None:
            try:
                active_alarms = self._alarm_system.get_active_alarms()
            except Exception as exc:
                logger.debug("AlarmSystem error: %s", exc)

        critical_count = sum(
            1 for a in active_alarms
            if getattr(a, "severity", getattr(a, "level", "")).upper() in ("CRITICAL", "EMERGENCY")
        )

        alarms_summary = []
        for alarm in active_alarms[:20]:
            try:
                alarms_summary.append(alarm.to_dict())
            except AttributeError:
                pass

        # --- Overall risk score ---
        risk_score, risk_level = self._compute_risk_level(
            drawdown_pct=drawdown_pct,
            exposure_pct=exposure_pct,
            var_breached_95=var_95_breached,
            var_breached_99=var_99_breached,
            critical_alarms=critical_count,
            total_alarms=len(active_alarms),
            corr_risk=corr_risk,
        )

        snapshot = RiskDashboardSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            var_available=var_snap is not None,
            parametric_var_95_usd=p_var95,
            parametric_var_99_usd=p_var99,
            historical_var_95_usd=h_var95,
            historical_var_99_usd=h_var99,
            cvar_95_usd=p_cvar95,
            cvar_99_usd=p_cvar99,
            var_95_breached=var_95_breached,
            var_99_breached=var_99_breached,
            var_95_limit_usd=var_95_limit,
            var_99_limit_usd=var_99_limit,
            pnl_scenario_count=scenario_count,
            portfolio_value_usd=portfolio_value,
            total_exposure_usd=total_exposure,
            total_exposure_pct=round(exposure_pct * 100, 2),
            num_open_positions=len(positions),
            long_exposure_usd=long_exposure,
            short_exposure_usd=short_exposure,
            net_exposure_usd=net_exposure,
            correlation_risk_score=round(corr_risk, 4),
            diversification_ratio=round(div_ratio, 4),
            max_sector_exposure_pct=round(max_sector_exp * 100, 2),
            current_drawdown_pct=round(drawdown_pct, 2),
            active_alarm_count=len(active_alarms),
            critical_alarm_count=critical_count,
            alarms_summary=alarms_summary,
            risk_level=risk_level,
            risk_score=round(risk_score, 1),
        )

        with self._lock:
            self._latest_snapshot = snapshot
            self._snapshot_history.append(snapshot)
            if len(self._snapshot_history) > 1000:
                self._snapshot_history = self._snapshot_history[-1000:]

        return snapshot

    @staticmethod
    def _compute_risk_level(
        drawdown_pct: float,
        exposure_pct: float,
        var_breached_95: bool,
        var_breached_99: bool,
        critical_alarms: int,
        total_alarms: int,
        corr_risk: float,
    ) -> tuple:
        """
        Compute a 0-100 risk score and categorical level.

        Returns (risk_score, risk_level_str)
        """
        score = 0.0

        # Drawdown contribution (0-40 pts)
        score += min(drawdown_pct * 2.0, 40.0)

        # VaR breach contribution (0-30 pts)
        if var_breached_99:
            score += 30.0
        elif var_breached_95:
            score += 15.0

        # Exposure contribution (0-15 pts)
        score += min(exposure_pct * 15.0, 15.0)

        # Alarm contribution (0-15 pts)
        score += min(critical_alarms * 10.0 + total_alarms * 1.0, 15.0)

        score = min(score, 100.0)

        if score >= 75:
            level = "RED"
        elif score >= 50:
            level = "ORANGE"
        elif score >= 25:
            level = "YELLOW"
        else:
            level = "GREEN"

        return score, level

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_snapshot(self) -> Optional[RiskDashboardSnapshot]:
        """Return the latest cached snapshot (or compute one if none available)."""
        with self._lock:
            snap = self._latest_snapshot
        if snap is None:
            snap = self.compute_snapshot()
        return snap

    def get_history(self, limit: int = 50) -> List[RiskDashboardSnapshot]:
        """Return up to *limit* most recent dashboard snapshots."""
        with self._lock:
            return list(self._snapshot_history[-limit:])

    def get_var_summary(self) -> Dict:
        """Return VaR-focused summary from the VaR monitor."""
        if self._var_monitor is None:
            return {"available": False, "reason": "VaR monitor not initialised"}
        return self._var_monitor.get_summary()

    # ------------------------------------------------------------------
    # Background monitoring
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background dashboard refresh thread."""
        if self._running:
            logger.warning("RiskDashboard already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._refresh_loop, name="RiskDashboard", daemon=True
        )
        self._thread.start()
        logger.info("🔄 RiskDashboard started (refresh=%ds)", self.refresh_interval)

    def stop(self) -> None:
        """Stop the background refresh thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(self.refresh_interval + 5, 15))
        logger.info("🛑 RiskDashboard stopped")

    def _refresh_loop(self) -> None:
        while self._running:
            try:
                self.compute_snapshot()
            except Exception as exc:
                logger.error("Dashboard refresh error: %s", exc, exc_info=True)
            time.sleep(self.refresh_interval)

    @property
    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_dashboard_instance: Optional[RiskDashboard] = None
_dashboard_lock = threading.Lock()


def get_risk_dashboard(
    refresh_interval: int = 60,
    var_limit_95_pct: float = 0.05,
    var_limit_99_pct: float = 0.08,
    reset: bool = False,
) -> RiskDashboard:
    """
    Return (or create) the global RiskDashboard singleton.

    Parameters
    ----------
    refresh_interval : int
        Seconds between automatic refreshes.
    var_limit_95_pct : float
        VaR 95 % limit as fraction of portfolio value.
    var_limit_99_pct : float
        VaR 99 % limit as fraction of portfolio value.
    reset : bool
        Stop any existing instance and create a fresh one.
    """
    global _dashboard_instance

    with _dashboard_lock:
        if reset and _dashboard_instance is not None:
            _dashboard_instance.stop()
            _dashboard_instance = None

        if _dashboard_instance is None:
            _dashboard_instance = RiskDashboard(
                refresh_interval=refresh_interval,
                var_limit_95_pct=var_limit_95_pct,
                var_limit_99_pct=var_limit_99_pct,
            )

    return _dashboard_instance


# ---------------------------------------------------------------------------
# Flask route registration
# ---------------------------------------------------------------------------

def register_risk_dashboard_routes(app) -> None:
    """
    Register real-time risk dashboard REST endpoints on a Flask app.

    Endpoints
    ---------
    GET /api/v1/risk/dashboard       – full real-time risk snapshot
    GET /api/v1/risk/var             – VaR metrics only
    GET /api/v1/risk/var/history     – VaR history  (?limit=N)
    GET /api/v1/risk/var/breaches    – recent VaR breaches  (?limit=N)
    GET /api/v1/risk/exposure        – portfolio exposure metrics
    GET /api/v1/risk/alarms          – active alarms from alarm system
    """
    from flask import jsonify, request as flask_request

    dashboard = get_risk_dashboard()

    @app.route("/api/v1/risk/dashboard", methods=["GET"])
    def get_risk_dashboard_endpoint():
        """Full real-time risk dashboard snapshot."""
        try:
            snap = dashboard.compute_snapshot()
            return jsonify({"success": True, "data": snap.to_dict()})
        except Exception as exc:
            logger.error("Risk dashboard endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/risk/var", methods=["GET"])
    def get_var_metrics():
        """Current VaR metrics."""
        try:
            summary = dashboard.get_var_summary()
            return jsonify({"success": True, "data": summary})
        except Exception as exc:
            logger.error("VaR metrics endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/risk/var/history", methods=["GET"])
    def get_var_history():
        """VaR history snapshots."""
        try:
            limit = flask_request.args.get("limit", default=50, type=int)
            if limit < 1 or limit > 500:
                return jsonify({"success": False, "error": "limit must be 1-500"}), 400
            var_mon = dashboard._var_monitor
            if var_mon is None:
                return jsonify({"success": False, "error": "VaR monitor not available"}), 503
            history = var_mon.get_history(limit=limit)
            return jsonify({
                "success": True,
                "data": {"count": len(history), "snapshots": [s.to_dict() for s in history]},
            })
        except Exception as exc:
            logger.error("VaR history endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/risk/var/breaches", methods=["GET"])
    def get_var_breaches():
        """Recent VaR limit breaches."""
        try:
            limit = flask_request.args.get("limit", default=20, type=int)
            if limit < 1 or limit > 200:
                return jsonify({"success": False, "error": "limit must be 1-200"}), 400
            var_mon = dashboard._var_monitor
            if var_mon is None:
                return jsonify({"success": False, "error": "VaR monitor not available"}), 503
            breaches = var_mon.get_breaches(limit=limit)
            return jsonify({
                "success": True,
                "data": {"count": len(breaches), "breaches": [b.to_dict() for b in breaches]},
            })
        except Exception as exc:
            logger.error("VaR breaches endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/risk/exposure", methods=["GET"])
    def get_exposure_metrics():
        """Portfolio exposure metrics from the latest dashboard snapshot."""
        try:
            snap = dashboard.get_snapshot()
            if snap is None:
                return jsonify({"success": False, "error": "No data yet"}), 503
            data = {
                "timestamp": snap.timestamp,
                "portfolio_value_usd": snap.portfolio_value_usd,
                "total_exposure_usd": snap.total_exposure_usd,
                "total_exposure_pct": snap.total_exposure_pct,
                "num_open_positions": snap.num_open_positions,
                "long_exposure_usd": snap.long_exposure_usd,
                "short_exposure_usd": snap.short_exposure_usd,
                "net_exposure_usd": snap.net_exposure_usd,
                "correlation_risk_score": snap.correlation_risk_score,
                "diversification_ratio": snap.diversification_ratio,
                "max_sector_exposure_pct": snap.max_sector_exposure_pct,
                "current_drawdown_pct": snap.current_drawdown_pct,
            }
            return jsonify({"success": True, "data": data})
        except Exception as exc:
            logger.error("Exposure metrics endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/risk/alarms", methods=["GET"])
    def get_risk_alarms():
        """Active risk alarms from the alarm system."""
        try:
            snap = dashboard.get_snapshot()
            if snap is None:
                return jsonify({"success": False, "error": "No data yet"}), 503
            return jsonify({
                "success": True,
                "data": {
                    "timestamp": snap.timestamp,
                    "active_count": snap.active_alarm_count,
                    "critical_count": snap.critical_alarm_count,
                    "risk_level": snap.risk_level,
                    "risk_score": snap.risk_score,
                    "alarms": snap.alarms_summary,
                },
            })
        except Exception as exc:
            logger.error("Risk alarms endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    logger.info("✅ Real-Time Risk Dashboard routes registered")
