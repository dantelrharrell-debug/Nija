"""
NIJA Profit Compounding Visual Dashboard
=========================================

Flask Blueprint that exposes a real-time, visual dashboard for tracking
profit compounding, auto-reinvestment, and withdrawal activity.

Endpoints
---------
GET /compounding/dashboard          — full HTML visual dashboard
GET /api/compounding/summary        — JSON summary for API consumers
GET /api/compounding/history        — JSON trade-by-trade compounding history
GET /api/compounding/reinvest       — trigger a manual reinvest cycle (POST)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, jsonify, render_template_string

logger = logging.getLogger("nija.compounding_dashboard")

# ---------------------------------------------------------------------------
# Optional integration imports (fail-safe)
# ---------------------------------------------------------------------------
try:
    from portfolio_profit_engine import get_portfolio_profit_engine  # type: ignore
    _PPE_AVAILABLE = True
except ImportError:
    _PPE_AVAILABLE = False
    get_portfolio_profit_engine = None

try:
    from profit_compounding_engine import ProfitCompoundingEngine  # type: ignore
    _PCE_AVAILABLE = True
except ImportError:
    _PCE_AVAILABLE = False
    ProfitCompoundingEngine = None

try:
    from auto_reinvest_engine import get_auto_reinvest_engine  # type: ignore
    _ARE_AVAILABLE = True
except ImportError:
    _ARE_AVAILABLE = False
    get_auto_reinvest_engine = None

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
_DATA_DIR = Path(os.environ.get("NIJA_DATA_DIR", "/tmp/nija_monitoring"))
_STATE_FILE = _DATA_DIR / "compounding_dashboard_state.json"


def _load_state() -> Dict[str, Any]:
    """Load persisted compounding state or return empty defaults."""
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception as exc:
        logger.warning("Could not load compounding state: %s", exc)
    return {
        "base_capital": 0.0,
        "total_profit": 0.0,
        "reinvested": 0.0,
        "withdrawn": 0.0,
        "trade_count": 0,
        "win_count": 0,
        "history": [],
        "last_updated": None,
    }


def _save_state(state: Dict[str, Any]) -> None:
    """Persist compounding state to disk."""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as exc:
        logger.warning("Could not save compounding state: %s", exc)


# ---------------------------------------------------------------------------
# Dashboard Blueprint factory
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta http-equiv="refresh" content="15" />
<title>NIJA — Profit Compounding Dashboard</title>
<style>
  :root{--green:#00d97e;--red:#f03a4f;--gold:#f5c518;--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;margin:0;padding:1rem}
  h1{color:var(--gold);margin-bottom:0.25rem}
  .subtitle{color:var(--muted);font-size:0.85rem;margin-bottom:1.5rem}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.5rem}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:1rem}
  .card .label{color:var(--muted);font-size:0.75rem;text-transform:uppercase;letter-spacing:.05em}
  .card .value{font-size:1.6rem;font-weight:700;margin-top:.25rem}
  .green{color:var(--green)}.red{color:var(--red)}.gold{color:var(--gold)}
  table{width:100%;border-collapse:collapse;background:var(--card);border-radius:8px;overflow:hidden}
  th{background:#1c2128;color:var(--muted);font-size:0.75rem;text-transform:uppercase;padding:0.6rem 1rem;text-align:left}
  td{padding:0.55rem 1rem;border-top:1px solid var(--border);font-size:0.85rem}
  tr.win td{border-left:3px solid var(--green)}
  tr.loss td{border-left:3px solid var(--red)}
  .bar-wrap{height:8px;background:#21262d;border-radius:4px;margin-top:6px}
  .bar{height:8px;border-radius:4px;background:var(--green);transition:width .4s}
  footer{color:var(--muted);font-size:.75rem;text-align:center;margin-top:1.5rem}
</style>
</head>
<body>
<h1>💰 NIJA Profit Compounding Dashboard</h1>
<p class="subtitle">Auto-refreshes every 15 s · Last updated: {{ last_updated }}</p>

<div class="grid">
  <div class="card">
    <div class="label">Base Capital</div>
    <div class="value gold">${{ "%.2f"|format(base_capital) }}</div>
  </div>
  <div class="card">
    <div class="label">Total Profit</div>
    <div class="value {{ 'green' if total_profit >= 0 else 'red' }}">${{ "%.2f"|format(total_profit) }}</div>
  </div>
  <div class="card">
    <div class="label">Reinvested</div>
    <div class="value green">${{ "%.2f"|format(reinvested) }}</div>
    <div class="bar-wrap"><div class="bar" style="width:{{ reinvest_pct }}%"></div></div>
    <div style="font-size:.75rem;color:var(--muted);margin-top:3px">{{ "%.1f"|format(reinvest_pct) }}% of profit</div>
  </div>
  <div class="card">
    <div class="label">Withdrawn</div>
    <div class="value gold">${{ "%.2f"|format(withdrawn) }}</div>
    <div class="bar-wrap"><div class="bar" style="width:{{ withdraw_pct }}%;background:var(--gold)"></div></div>
    <div style="font-size:.75rem;color:var(--muted);margin-top:3px">{{ "%.1f"|format(withdraw_pct) }}% of profit</div>
  </div>
  <div class="card">
    <div class="label">Trades</div>
    <div class="value">{{ trade_count }}</div>
  </div>
  <div class="card">
    <div class="label">Win Rate</div>
    <div class="value {{ 'green' if win_rate >= 50 else 'red' }}">{{ "%.1f"|format(win_rate) }}%</div>
  </div>
  <div class="card">
    <div class="label">Net Capital</div>
    <div class="value {{ 'green' if net_capital >= base_capital else 'red' }}">${{ "%.2f"|format(net_capital) }}</div>
  </div>
</div>

<h2 style="color:var(--text);font-size:1rem;margin-bottom:.5rem">Recent Compounding Events</h2>
{% if history %}
<table>
  <thead>
    <tr>
      <th>Time</th><th>Symbol</th><th>Gross P&L</th><th>Reinvested</th><th>Withdrawn</th><th>Result</th>
    </tr>
  </thead>
  <tbody>
  {% for row in history[-30:]|reverse %}
    <tr class="{{ 'win' if row.is_win else 'loss' }}">
      <td>{{ row.ts }}</td>
      <td>{{ row.symbol }}</td>
      <td class="{{ 'green' if row.pnl >= 0 else 'red' }}">${{ "%.4f"|format(row.pnl) }}</td>
      <td class="green">${{ "%.4f"|format(row.reinvested) }}</td>
      <td class="gold">${{ "%.4f"|format(row.withdrawn) }}</td>
      <td>{{ "✅ WIN" if row.is_win else "❌ LOSS" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
  <p style="color:var(--muted)">No compounding events recorded yet.</p>
{% endif %}

<footer>NIJA Trading Systems · Profit Compounding Dashboard v1.0</footer>
</body>
</html>"""


def create_compounding_dashboard_blueprint() -> Blueprint:
    """
    Create and return the compounding dashboard Flask Blueprint.

    Register it with::

        app.register_blueprint(create_compounding_dashboard_blueprint())
    """
    bp = Blueprint("compounding_dashboard", __name__)

    # ------------------------------------------------------------------
    # Helper: build summary dict from all available sources
    # ------------------------------------------------------------------
    def _build_summary() -> Dict[str, Any]:
        state = _load_state()

        # Pull live data from PortfolioProfitEngine if available
        if _PPE_AVAILABLE and get_portfolio_profit_engine:
            try:
                ppe = get_portfolio_profit_engine()
                summary = ppe.get_summary()
                state["base_capital"] = summary.get("base_capital", state["base_capital"])
                state["total_profit"] = summary.get("total_profit", state["total_profit"])
                state["reinvested"] = summary.get("reinvested_amount", state["reinvested"])
                state["trade_count"] = summary.get("total_trades", state["trade_count"])
                state["win_count"] = summary.get("winning_trades", state["win_count"])
                history: List[Dict] = summary.get("trade_history", [])
                if history:
                    state["history"] = [
                        {
                            "ts": t.get("timestamp", "")[:19],
                            "symbol": t.get("symbol", "?"),
                            "pnl": t.get("net_pnl", 0.0),
                            "reinvested": t.get("reinvested", 0.0),
                            "withdrawn": t.get("withdrawn", 0.0),
                            "is_win": t.get("is_win", False),
                        }
                        for t in history
                    ]
            except Exception as exc:
                logger.debug("PortfolioProfitEngine unavailable: %s", exc)

        # Pull withdrawal data from AutoReinvestEngine if available
        if _ARE_AVAILABLE and get_auto_reinvest_engine:
            try:
                are = get_auto_reinvest_engine()
                are_state = are.get_state()
                state["withdrawn"] = are_state.get("total_withdrawn", state["withdrawn"])
            except Exception as exc:
                logger.debug("AutoReinvestEngine unavailable: %s", exc)

        total_profit = state.get("total_profit", 0.0)
        reinvested = state.get("reinvested", 0.0)
        withdrawn = state.get("withdrawn", 0.0)

        reinvest_pct = (reinvested / total_profit * 100.0) if total_profit > 0 else 0.0
        withdraw_pct = (withdrawn / total_profit * 100.0) if total_profit > 0 else 0.0

        trade_count = state.get("trade_count", 0)
        win_count = state.get("win_count", 0)
        win_rate = (win_count / trade_count * 100.0) if trade_count > 0 else 0.0

        return {
            "base_capital": state.get("base_capital", 0.0),
            "total_profit": total_profit,
            "reinvested": reinvested,
            "reinvest_pct": min(reinvest_pct, 100.0),
            "withdrawn": withdrawn,
            "withdraw_pct": min(withdraw_pct, 100.0),
            "trade_count": trade_count,
            "win_count": win_count,
            "win_rate": win_rate,
            "net_capital": state.get("base_capital", 0.0) + total_profit,
            "history": state.get("history", []),
            "last_updated": state.get(
                "last_updated", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            ),
        }

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @bp.route("/compounding/dashboard")
    def compounding_dashboard():  # type: ignore[return]
        """Return the full HTML visual dashboard for profit compounding."""
        data = _build_summary()
        return render_template_string(_DASHBOARD_HTML, **data)

    @bp.route("/api/compounding/summary")
    def compounding_summary():  # type: ignore[return]
        """Return a JSON summary of compounding metrics (excludes trade history)."""
        data = _build_summary()
        data.pop("history", None)  # Omit large list from summary
        return jsonify(data)

    @bp.route("/api/compounding/history")
    def compounding_history():  # type: ignore[return]
        """Return the JSON trade-by-trade compounding history."""
        data = _build_summary()
        return jsonify({"history": data.get("history", [])})

    return bp


def register_compounding_dashboard(app: "Flask") -> None:  # type: ignore[name-defined]
    """
    Convenience function to register the compounding dashboard Blueprint with
    an existing Flask app instance.

        register_compounding_dashboard(app)
    """
    try:
        bp = create_compounding_dashboard_blueprint()
        app.register_blueprint(bp)
        logger.info(
            "✅ Profit Compounding Dashboard registered "
            "(/compounding/dashboard, /api/compounding/summary, /api/compounding/history)"
        )
    except Exception as exc:
        logger.warning("⚠️ Could not register compounding dashboard: %s", exc)
