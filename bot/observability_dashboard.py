"""
NIJA Observability Dashboard
=============================

Central observability dashboard that aggregates metrics from all NIJA
subsystems and exposes them through:

  1. A Flask JSON API  (``/api/v1/…``)
  2. A lightweight HTML dashboard (``/dashboard``)
  3. Server-Sent Events stream (``/api/v1/stream``) for real-time updates

Metrics aggregated
------------------
- Global risk engine: exposure, drawdown, position limits
- Kill-switch status
- Strategy health scores
- Capital recycling pool
- Profit lock state
- Stress-test survival rates (last run)
- Broker health (error rates, latency)
- Alert counters

Usage (standalone)
------------------
    python bot/observability_dashboard.py            # starts on port 9090
    python bot/observability_dashboard.py --port 8080

Usage (embedded in existing Flask app)
---------------------------------------
    from bot.observability_dashboard import get_observability_dashboard
    dashboard = get_observability_dashboard()
    app.register_blueprint(dashboard.blueprint)

Environment variables
---------------------
    OBS_DASHBOARD_PORT : TCP port (default 9090)
    OBS_DASHBOARD_HOST : bind host (default 0.0.0.0)
    OBS_ALERT_WEBHOOK  : optional Slack/Discord webhook URL for critical alerts

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger("nija.observability_dashboard")


# ---------------------------------------------------------------------------
# Metric collector
# ---------------------------------------------------------------------------

class MetricCollector:
    """
    Periodically polls all available NIJA singletons and builds a consolidated
    metrics snapshot.  Missing/unavailable modules are silently skipped so the
    dashboard works even in a partially configured environment.
    """

    def __init__(self, poll_interval_sec: float = 5.0) -> None:
        self._interval = poll_interval_sec
        self._snapshot: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._alert_queue: queue.Queue = queue.Queue(maxsize=500)

    # ------------------------------------------------------------------
    # Background poller
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="obs-collector")
        self._thread.start()
        logger.info("[ObsDashboard] Metric collector started (interval=%.1fs)", self._interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)

    def _poll_loop(self) -> None:
        while self._running:
            try:
                snapshot = self._collect()
                with self._lock:
                    self._snapshot = snapshot
                self._check_alerts(snapshot)
            except Exception as exc:
                logger.error("[ObsDashboard] Poll error: %s", exc)
            time.sleep(self._interval)

    # ------------------------------------------------------------------
    # Public snapshot access
    # ------------------------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._snapshot)

    def get_alerts(self, limit: int = 50) -> List[Dict]:
        alerts = []
        while not self._alert_queue.empty() and len(alerts) < limit:
            try:
                alerts.append(self._alert_queue.get_nowait())
            except queue.Empty:
                break
        return alerts

    # ------------------------------------------------------------------
    # Metric collection
    # ------------------------------------------------------------------

    def _collect(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        snap: Dict[str, Any] = {
            "collected_at": now,
            "modules": {},
        }

        # 1. Global Risk Engine
        snap["modules"]["global_risk_engine"] = self._collect_global_risk()

        # 2. Kill Switch
        snap["modules"]["kill_switch"] = self._collect_kill_switch()

        # 3. Strategy Health Monitor
        snap["modules"]["strategy_health"] = self._collect_strategy_health()

        # 4. Capital Recycling Engine
        snap["modules"]["capital_recycling"] = self._collect_capital_recycling()

        # 5. Profit Lock Engine
        snap["modules"]["profit_lock"] = self._collect_profit_lock()

        # 6. Exchange Kill Switch
        snap["modules"]["exchange_kill_switch"] = self._collect_exchange_kill_switch()

        # 7. Correlation Risk Engine
        snap["modules"]["correlation_risk"] = self._collect_correlation_risk()

        # 8. Volatility Shock Detector
        snap["modules"]["volatility_shock"] = self._collect_volatility_shock()

        # 9. Global Risk Governor
        snap["modules"]["global_risk_governor"] = self._collect_risk_governor()

        # 10. Multi-Asset Executor
        snap["modules"]["multi_asset_executor"] = self._collect_multi_asset()

        # 11. Broker health (from multi_account_broker_manager if available)
        snap["modules"]["broker_health"] = self._collect_broker_health()

        # 12. Capital Growth Throttle (drawdown/size-multiplier)
        snap["modules"]["capital_throttle"] = self._collect_capital_throttle()

        # Derived top-level fields for quick status bar
        snap["status"] = self._compute_top_level_status(snap["modules"])

        return snap

    # ------------------------------------------------------------------
    # Per-module collectors
    # ------------------------------------------------------------------

    def _collect_global_risk(self) -> Dict:
        try:
            from bot.global_risk_engine import get_global_risk_engine
            engine = get_global_risk_engine()
            exposure = engine.get_portfolio_exposure() if hasattr(engine, "get_portfolio_exposure") else {}
            return {"available": True, "exposure": exposure}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_kill_switch(self) -> Dict:
        try:
            from bot.kill_switch import get_kill_switch  # type: ignore
            ks = get_kill_switch()
            return {
                "available": True,
                "is_triggered": getattr(ks, "is_triggered", False),
                "reason": getattr(ks, "trigger_reason", None),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_strategy_health(self) -> Dict:
        try:
            from bot.strategy_health_monitor import get_strategy_health_monitor
            monitor = get_strategy_health_monitor()
            all_health = {}
            if hasattr(monitor, "_strategies"):
                for name in monitor._strategies:
                    h = monitor.get_health(name)
                    all_health[name] = {
                        "level": h.level.value if hasattr(h, "level") else str(h),
                        "score": getattr(h, "composite_score", None),
                    }
            return {"available": True, "strategies": all_health}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_capital_recycling(self) -> Dict:
        try:
            from bot.capital_recycling_engine import get_capital_recycling_engine
            engine = get_capital_recycling_engine()
            status = engine.get_status()
            return {
                "available": True,
                "pool_usd": status.get("pool_usd"),
                "allocation_pcts": status.get("allocation_pcts", {}),
                "last_allocations": status.get("last_allocations", {}),
                "last_allocation_regime": status.get("last_allocation_regime", ""),
                "last_allocation_ts": status.get("last_allocation_ts", ""),
                "rebalance_interval_hours": status.get("rebalance_interval_hours"),
                "weights_computed_at": status.get("weights_computed_at", ""),
                "next_rebalance_ts": status.get("next_rebalance_ts", ""),
                "throttle_multiplier": status.get("throttle_multiplier", 1.0),
                "throttle_label": status.get("throttle_label", "UNRESTRICTED"),
                "throttle_drawdown_pct": status.get("throttle_drawdown_pct", 0.0),
                "strategy_health_factors": status.get("strategy_health_factors", {}),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_capital_throttle(self) -> Dict:
        try:
            from bot.capital_growth_throttle import get_capital_growth_throttle
            throttle = get_capital_growth_throttle()
            # Use get_status() if available (growth-velocity implementation)
            if hasattr(throttle, "get_status"):
                status = throttle.get_status()
                return {"available": True, **status}
            # Fallback for drawdown-based implementation
            state = throttle.state
            return {
                "available": True,
                "throttle_level": getattr(state, "label", "UNKNOWN"),
                "current_multiplier": getattr(state, "multiplier", 1.0),
                "short_growth_pct": getattr(state, "drawdown_pct", 0.0),
                "long_growth_pct": 0.0,
                "throttle_reason": getattr(state, "label", ""),
                "last_updated": state.last_updated.isoformat() if state.last_updated else None,
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_profit_lock(self) -> Dict:
        try:
            from bot.profit_lock_engine import get_profit_lock_engine
            engine = get_profit_lock_engine()
            positions = getattr(engine, "_positions", {})
            return {
                "available": True,
                "tracked_positions": len(positions),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_exchange_kill_switch(self) -> Dict:
        try:
            from bot.exchange_kill_switch import get_exchange_kill_switch_protector
            eks = get_exchange_kill_switch_protector()
            gates = {}
            if hasattr(eks, "_gates"):
                for name, gate in eks._gates.items():
                    gates[name] = {
                        "status": getattr(gate, "status", "unknown"),
                        "value": getattr(gate, "current_value", None),
                    }
            return {"available": True, "gates": gates}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_correlation_risk(self) -> Dict:
        try:
            from bot.correlation_risk_engine import get_correlation_risk_engine
            engine = get_correlation_risk_engine()
            clusters = len(getattr(engine, "_clusters", {}))
            return {"available": True, "active_clusters": clusters}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_volatility_shock(self) -> Dict:
        try:
            from bot.volatility_shock_detector import get_volatility_shock_detector
            detector = get_volatility_shock_detector()
            shock = detector.get_portfolio_shock() if hasattr(detector, "get_portfolio_shock") else {}
            return {"available": True, "portfolio_shock": shock}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_risk_governor(self) -> Dict:
        try:
            from bot.global_risk_governor import get_global_risk_governor
            gov = get_global_risk_governor()
            # Use public approve_entry API with a neutral probe signal to check gate status.
            # Falls back to private _check_all_gates if the public method is unavailable.
            if hasattr(gov, "approve_entry"):
                try:
                    probe_result = gov.approve_entry({"symbol": "_probe", "size_usd": 0.0})
                    gates_ok = bool(probe_result)
                except Exception:
                    gates_ok = None
            elif hasattr(gov, "_check_all_gates"):
                gates_ok = gov._check_all_gates()
            else:
                gates_ok = None
            return {
                "available": True,
                "all_gates_ok": gates_ok,
                "daily_loss": getattr(gov, "_daily_loss", None),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_multi_asset(self) -> Dict:
        try:
            from bot.multi_asset_executor import get_multi_asset_executor
            executor = get_multi_asset_executor()
            snap = executor.portfolio_snapshot()
            return {"available": True, **snap}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_broker_health(self) -> Dict:
        try:
            from bot.multi_account_broker_manager import multi_account_broker_manager as mgr
            result = mgr.verify_account_hierarchy() if hasattr(mgr, "verify_account_hierarchy") else {}
            return {"available": True, "hierarchy": result}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Alert logic
    # ------------------------------------------------------------------

    def _compute_top_level_status(self, modules: Dict) -> Dict:
        kill_triggered = modules.get("kill_switch", {}).get("is_triggered", False)
        all_gates = modules.get("global_risk_governor", {}).get("all_gates_ok")

        if kill_triggered:
            level = "CRITICAL"
            message = "Kill switch is ACTIVE — trading halted"
        elif all_gates is False:
            level = "WARNING"
            message = "Risk governor gate(s) tripped"
        else:
            level = "OK"
            message = "All systems nominal"

        return {
            "level": level,
            "message": message,
            "kill_switch_active": kill_triggered,
            "risk_gates_ok": all_gates,
        }

    def _check_alerts(self, snapshot: Dict) -> None:
        status = snapshot.get("status", {})
        level = status.get("level", "OK")

        if level in ("CRITICAL", "WARNING"):
            alert = {
                "timestamp": snapshot.get("collected_at"),
                "level": level,
                "message": status.get("message", ""),
            }
            try:
                self._alert_queue.put_nowait(alert)
            except queue.Full:
                pass

            if level == "CRITICAL":
                self._send_webhook_alert(alert)

    def _send_webhook_alert(self, alert: Dict) -> None:
        url = os.getenv("OBS_ALERT_WEBHOOK", "")
        if not url:
            return
        try:
            import urllib.request
            payload = json.dumps({
                "text": f"🚨 NIJA CRITICAL: {alert['message']} at {alert['timestamp']}"
            }).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:
            logger.warning("[ObsDashboard] Webhook delivery failed: %s", exc)


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NIJA Observability Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; min-height: 100vh; }
  header { background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 24px;
           display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 1.3rem; font-weight: 700; color: #58a6ff; }
  #status-banner { padding: 10px 24px; font-weight: 600; font-size: 0.9rem; text-align: center; }
  .ok     { background: #1a4a2e; color: #3fb950; }
  .warn   { background: #4a3800; color: #d29922; }
  .crit   { background: #4a1a1a; color: #f85149; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; padding: 20px 24px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
  .card h2 { font-size: 0.85rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }
  .metric { display: flex; justify-content: space-between; margin: 6px 0; font-size: 0.9rem; }
  .metric .label { color: #8b949e; }
  .metric .value { color: #e6edf3; font-family: monospace; }
  .badge { display: inline-block; border-radius: 4px; padding: 2px 8px; font-size: 0.78rem; font-weight: 600; }
  .badge-ok   { background: #1a4a2e; color: #3fb950; }
  .badge-warn { background: #4a3800; color: #d29922; }
  .badge-crit { background: #4a1a1a; color: #f85149; }
  .badge-na   { background: #1c2128; color: #6e7681; }
  #last-updated { color: #6e7681; font-size: 0.78rem; margin-left: auto; }
  #alerts-section { padding: 0 24px 24px; }
  #alerts-list { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                 max-height: 200px; overflow-y: auto; }
  .alert-row { padding: 8px 12px; border-bottom: 1px solid #21262d; font-size: 0.85rem; }
  .alert-row:last-child { border-bottom: none; }
  .alert-crit { color: #f85149; } .alert-warn { color: #d29922; }
</style>
</head>
<body>
<header>
  <h1>🚀 NIJA Observability Dashboard</h1>
  <span id="last-updated">loading…</span>
</header>
<div id="status-banner" class="ok">⟳ Loading metrics…</div>
<div class="grid" id="cards-container"></div>
<div id="alerts-section">
  <h2 style="color:#8b949e;font-size:0.85rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">
    Recent Alerts
  </h2>
  <div id="alerts-list"><div class="alert-row" style="color:#6e7681">No alerts yet.</div></div>
</div>

<script>
const API = '/api/v1';
let alertBuffer = [];

function badge(val, ok_val='OK', warn_val='WARNING', na_val='N/A') {
  if (val === null || val === undefined) return `<span class="badge badge-na">${na_val}</span>`;
  const s = String(val).toUpperCase();
  if (s === ok_val.toUpperCase() || s === 'TRUE' || s === 'OK' || s === 'HEALTHY')
    return `<span class="badge badge-ok">${val}</span>`;
  if (s === warn_val.toUpperCase() || s === 'WARNING' || s === 'WATCHING')
    return `<span class="badge badge-warn">${val}</span>`;
  return `<span class="badge badge-crit">${val}</span>`;
}

function metricRow(label, value) {
  return `<div class="metric"><span class="label">${label}</span><span class="value">${value ?? '—'}</span></div>`;
}

function buildCard(title, rows) {
  return `<div class="card"><h2>${title}</h2>${rows.join('')}</div>`;
}

async function refresh() {
  try {
    const [snapResp, alertResp] = await Promise.all([
      fetch(API + '/metrics'),
      fetch(API + '/alerts'),
    ]);
    const snap = await snapResp.json();
    const alerts = await alertResp.json();

    // Status banner
    const st = snap.status || {};
    const banner = document.getElementById('status-banner');
    banner.textContent = st.message || 'Unknown';
    banner.className = '';
    if (st.level === 'CRITICAL') banner.classList.add('crit');
    else if (st.level === 'WARNING') banner.classList.add('warn');
    else banner.classList.add('ok');

    // Last updated
    document.getElementById('last-updated').textContent =
      'Updated: ' + new Date(snap.collected_at).toLocaleTimeString();

    const mods = snap.modules || {};
    const cards = [];

    // Global Risk Engine
    const gre = mods.global_risk_engine || {};
    if (gre.available) {
      const exp = gre.exposure || {};
      cards.push(buildCard('Global Risk Engine', [
        metricRow('Status', badge(gre.available ? 'OK' : 'ERROR')),
        metricRow('Total Exposure', exp.total_exposure_usd != null ? '$' + exp.total_exposure_usd.toLocaleString() : '—'),
        metricRow('Net Exposure', exp.net_exposure_usd != null ? '$' + exp.net_exposure_usd.toLocaleString() : '—'),
      ]));
    }

    // Kill Switch
    const ks = mods.kill_switch || {};
    cards.push(buildCard('Kill Switch', [
      metricRow('Available', badge(ks.available ? 'OK' : null)),
      metricRow('Triggered', ks.is_triggered
        ? `<span class="badge badge-crit">YES — ${ks.reason || 'unknown'}</span>`
        : `<span class="badge badge-ok">NO</span>`),
    ]));

    // Strategy Health
    const sh = mods.strategy_health || {};
    const stratRows = [];
    for (const [name, info] of Object.entries(sh.strategies || {})) {
      stratRows.push(metricRow(name, badge(info.level)));
    }
    if (stratRows.length === 0) stratRows.push(metricRow('No strategies tracked', '—'));
    cards.push(buildCard('Strategy Health', stratRows));

    // Capital Recycling — allocation plan + throttle
    const cr = mods.capital_recycling || {};
    if (cr.available) {
      const crRows = [
        metricRow('Pool (USD)', cr.pool_usd != null ? '$' + cr.pool_usd.toLocaleString() : '—'),
        metricRow('Throttle', badge(cr.throttle_label, 'UNRESTRICTED', 'CONSERVATIVE', 'N/A')),
        metricRow('Drawdown', cr.throttle_drawdown_pct != null ? cr.throttle_drawdown_pct.toFixed(2) + ' %' : '—'),
        metricRow('Size Multiplier', cr.throttle_multiplier != null ? (cr.throttle_multiplier * 100).toFixed(0) + ' %' : '—'),
        metricRow('Last Regime', cr.last_allocation_regime || '—'),
        metricRow('Next Rebalance', cr.next_rebalance_ts ? new Date(cr.next_rebalance_ts).toLocaleTimeString() : '—'),
      ];
      // Strategy allocation plan
      const pcts = cr.allocation_pcts || {};
      const hfs = cr.strategy_health_factors || {};
      for (const [strat, pct] of Object.entries(pcts).sort((a, b) => b[1] - a[1])) {
        const hf = hfs[strat] ?? 1.0;
        const hfStr = hf < 1.0 ? ` <span class="badge badge-warn">health ${(hf*100).toFixed(0)}%</span>` : '';
        crRows.push(`<div class="metric"><span class="label" style="font-size:0.82rem">${strat}</span><span class="value">${Number(pct).toFixed(1)} %${hfStr}</span></div>`);
      }
      cards.push(buildCard('Capital Recycling & Allocation Plan', crRows));
    } else {
      cards.push(buildCard('Capital Recycling', [
        metricRow('Available', badge(null)),
      ]));
    }

    // Capital Growth Throttle (standalone card)
    const ct = mods.capital_throttle || {};
    if (ct.available) {
      cards.push(buildCard('Capital Growth Throttle', [
        metricRow('Throttle Level', badge(ct.throttle_level, 'FREE', 'CAUTION', 'N/A')),
        metricRow('Size Multiplier', ct.current_multiplier != null ? (ct.current_multiplier * 100).toFixed(0) + ' %' : '—'),
        metricRow('7d Growth', ct.short_growth_pct != null ? ct.short_growth_pct.toFixed(2) + ' %' : '—'),
        metricRow('30d Growth', ct.long_growth_pct != null ? ct.long_growth_pct.toFixed(2) + ' %' : '—'),
        metricRow('Reason', ct.throttle_reason || '—'),
      ]));
    }

    // Multi-Asset Executor
    const mae = mods.multi_asset_executor || {};
    cards.push(buildCard('Multi-Asset Executor', [
      metricRow('Available', badge(mae.available ? 'OK' : null)),
      metricRow('Open Positions', mae.open_positions ?? '—'),
      metricRow('Deployed USD', mae.total_deployed_usd != null ? '$' + mae.total_deployed_usd.toLocaleString() : '—'),
      metricRow('Cash USD', mae.cash_usd != null ? '$' + mae.cash_usd.toLocaleString() : '—'),
      metricRow('Unrealised PnL', mae.total_unrealised_pnl != null ? '$' + mae.total_unrealised_pnl.toLocaleString() : '—'),
    ]));

    // Exchange Kill Switch
    const eks = mods.exchange_kill_switch || {};
    const gateRows = [];
    for (const [name, gate] of Object.entries(eks.gates || {})) {
      const st_val = (gate.status || '').toUpperCase();
      const cls = st_val === 'GREEN' ? 'badge-ok' : st_val === 'YELLOW' ? 'badge-warn' : 'badge-crit';
      gateRows.push(`<div class="metric"><span class="label">${name}</span>
        <span class="badge ${cls}">${gate.status}</span></div>`);
    }
    if (gateRows.length === 0) gateRows.push(metricRow('—', '—'));
    cards.push(buildCard('Exchange Kill Switch Gates', gateRows));

    // Volatility Shock
    const vs = mods.volatility_shock || {};
    const shock = vs.portfolio_shock || {};
    cards.push(buildCard('Volatility Shock Detector', [
      metricRow('Available', badge(vs.available ? 'OK' : null)),
      metricRow('Severity', badge(shock.severity || '—')),
      metricRow('Size Scale', shock.size_scale ?? '—'),
    ]));

    // Risk Governor
    const rg = mods.global_risk_governor || {};
    cards.push(buildCard('Risk Governor', [
      metricRow('Available', badge(rg.available ? 'OK' : null)),
      metricRow('All Gates OK', rg.all_gates_ok != null
        ? badge(rg.all_gates_ok ? 'OK' : 'TRIPPED', 'OK', 'TRIPPED', 'UNKNOWN')
        : '—'),
      metricRow('Daily Loss', rg.daily_loss != null ? '$' + rg.daily_loss.toLocaleString() : '—'),
    ]));

    document.getElementById('cards-container').innerHTML = cards.join('');

    // Alerts
    alertBuffer = [...(alerts.alerts || []), ...alertBuffer].slice(0, 100);
    const alertsEl = document.getElementById('alerts-list');
    if (alertBuffer.length === 0) {
      alertsEl.innerHTML = '<div class="alert-row" style="color:#6e7681">No alerts.</div>';
    } else {
      alertsEl.innerHTML = alertBuffer.map(a =>
        `<div class="alert-row alert-${a.level === 'CRITICAL' ? 'crit' : 'warn'}">
          [${a.level}] ${new Date(a.timestamp).toLocaleString()} — ${a.message}
        </div>`
      ).join('');
    }

  } catch(e) {
    console.error('Dashboard refresh error:', e);
  }
}

// Refresh every 5 seconds
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


class ObservabilityDashboard:
    """
    Central observability dashboard.  Wraps a MetricCollector and exposes
    a Flask Blueprint with JSON API routes and an HTML UI.
    """

    def __init__(self, poll_interval_sec: float = 5.0) -> None:
        self._collector = MetricCollector(poll_interval_sec=poll_interval_sec)
        self._collector.start()
        self._blueprint = self._build_blueprint()

    @property
    def blueprint(self):
        return self._blueprint

    def get_snapshot(self) -> Dict:
        return self._collector.get_snapshot()

    def _build_blueprint(self):
        try:
            from flask import Blueprint, Response, jsonify, stream_with_context
        except ImportError:
            logger.warning("[ObsDashboard] Flask not installed — blueprint unavailable")
            return None

        bp = Blueprint("observability", __name__, url_prefix="")

        @bp.route("/dashboard")
        def dashboard_ui():
            return Response(_DASHBOARD_HTML, mimetype="text/html")

        @bp.route("/api/v1/metrics")
        def metrics():
            return jsonify(self._collector.get_snapshot())

        @bp.route("/api/v1/alerts")
        def alerts():
            return jsonify({"alerts": self._collector.get_alerts(limit=100)})

        @bp.route("/api/v1/health")
        def health():
            snap = self._collector.get_snapshot()
            status = snap.get("status", {})
            return jsonify({
                "healthy": status.get("level") not in ("CRITICAL",),
                "level": status.get("level", "UNKNOWN"),
                "message": status.get("message", ""),
                "collected_at": snap.get("collected_at"),
            })

        @bp.route("/api/v1/stream")
        def stream():
            """Server-Sent Events endpoint for real-time metric streaming."""
            def _generate() -> Generator:
                while True:
                    snap = self._collector.get_snapshot()
                    data = json.dumps(snap)
                    yield f"data: {data}\n\n"
                    time.sleep(5)

            return Response(
                stream_with_context(_generate()),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        return bp


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_dashboard_instance: Optional[ObservabilityDashboard] = None
_dashboard_lock = threading.Lock()


def get_observability_dashboard(poll_interval_sec: float = 5.0) -> ObservabilityDashboard:
    """Return module-level singleton ObservabilityDashboard."""
    global _dashboard_instance
    with _dashboard_lock:
        if _dashboard_instance is None:
            _dashboard_instance = ObservabilityDashboard(poll_interval_sec=poll_interval_sec)
    return _dashboard_instance


# ---------------------------------------------------------------------------
# Standalone server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    )

    parser = argparse.ArgumentParser(description="NIJA Observability Dashboard")
    parser.add_argument("--port", type=int, default=int(os.getenv("OBS_DASHBOARD_PORT", "9090")))
    parser.add_argument("--host", default=os.getenv("OBS_DASHBOARD_HOST", "0.0.0.0"))
    parser.add_argument("--interval", type=float, default=5.0, help="Metric poll interval (seconds)")
    args = parser.parse_args()

    try:
        from flask import Flask
    except ImportError:
        print("Flask is required: pip install flask", file=sys.stderr)
        sys.exit(1)

    app = Flask(__name__)
    dashboard = get_observability_dashboard(poll_interval_sec=args.interval)
    app.register_blueprint(dashboard.blueprint)

    print(f"\n🚀 NIJA Observability Dashboard")
    print(f"   URL  : http://{args.host}:{args.port}/dashboard")
    print(f"   API  : http://{args.host}:{args.port}/api/v1/metrics")
    print(f"   SSE  : http://{args.host}:{args.port}/api/v1/stream")
    print(f"   Poll : {args.interval}s\n")

    app.run(host=args.host, port=args.port, threaded=True)
