"""
NIJA Owner Dashboard API
=========================

Lightweight Flask REST API that exposes the Accounting Verification Layer,
Owner Control Layer, Text Alert System, and related subsystems to the
phone-friendly owner dashboard (owner_dashboard.html).

Endpoints
---------
GET  /api/owner/status          — owner control status + accounting summary
GET  /api/owner/alerts          — recent text-alert history
GET  /api/owner/ledger          — recent ledger entries
GET  /api/owner/reconcile       — run ledger reconciliation
POST /api/owner/control         — execute owner control action (PIN required)
POST /api/owner/check-profit    — test big-profit-day threshold

All state-changing control actions require a ``pin`` field in the JSON body.

Running standalone
------------------
::

    python owner_dashboard_api.py

The server starts on port 5050 by default.  Set ``OWNER_DASHBOARD_PORT``
environment variable to override.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from flask import Flask, jsonify, request, send_from_directory, Response

# ---------------------------------------------------------------------------
# NIJA subsystem imports (graceful degradation if running standalone)
# ---------------------------------------------------------------------------

try:
    from bot.owner_control_layer import get_owner_control_layer, OwnerConfig
    _OWNER_AVAILABLE = True
except ImportError:
    try:
        from owner_control_layer import get_owner_control_layer, OwnerConfig  # type: ignore
        _OWNER_AVAILABLE = True
    except ImportError:
        get_owner_control_layer = None  # type: ignore
        OwnerConfig = None  # type: ignore
        _OWNER_AVAILABLE = False

try:
    from bot.accounting_verification import get_accounting_layer
    _ACCOUNTING_AVAILABLE = True
except ImportError:
    try:
        from accounting_verification import get_accounting_layer  # type: ignore
        _ACCOUNTING_AVAILABLE = True
    except ImportError:
        get_accounting_layer = None  # type: ignore
        _ACCOUNTING_AVAILABLE = False

try:
    from bot.text_alert_system import get_text_alert_system
    _ALERTS_AVAILABLE = True
except ImportError:
    try:
        from text_alert_system import get_text_alert_system  # type: ignore
        _ALERTS_AVAILABLE = True
    except ImportError:
        get_text_alert_system = None  # type: ignore
        _ALERTS_AVAILABLE = False

try:
    from bot.weekly_salary_mode import get_weekly_salary_mode
    _SALARY_AVAILABLE = True
except ImportError:
    try:
        from weekly_salary_mode import get_weekly_salary_mode  # type: ignore
        _SALARY_AVAILABLE = True
    except ImportError:
        get_weekly_salary_mode = None  # type: ignore
        _SALARY_AVAILABLE = False

try:
    from bot.emergency_capital_protection import get_emergency_capital_protection
    _ECP_AVAILABLE = True
except ImportError:
    try:
        from emergency_capital_protection import get_emergency_capital_protection  # type: ignore
        _ECP_AVAILABLE = True
    except ImportError:
        get_emergency_capital_protection = None  # type: ignore
        _ECP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.owner_dashboard_api")

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=".", static_url_path="")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner():
    if _OWNER_AVAILABLE:
        return get_owner_control_layer()
    return None


def _accounting():
    if _ACCOUNTING_AVAILABLE:
        return get_accounting_layer()
    return None


def _alerts():
    if _ALERTS_AVAILABLE:
        return get_text_alert_system()
    return None


def _salary():
    if _SALARY_AVAILABLE:
        return get_weekly_salary_mode()
    return None


def _ecp():
    if _ECP_AVAILABLE:
        return get_emergency_capital_protection()
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def serve_dashboard():
    """Serve the phone-friendly owner dashboard HTML."""
    return send_from_directory(".", "owner_dashboard.html")


@app.route("/api/owner/status", methods=["GET"])
def get_status():
    """
    Return a combined status object:
    - owner control state
    - accounting summary
    - salary engine state
    - emergency capital protection level
    """
    payload: Dict[str, Any] = {"timestamp": _ts()}

    owner = _owner()
    if owner:
        payload["owner_control"] = owner.get_status()
    else:
        payload["owner_control"] = {"error": "OwnerControlLayer not available"}

    acct = _accounting()
    if acct:
        payload["accounting"] = acct.get_summary()
    else:
        payload["accounting"] = {"error": "AccountingVerificationLayer not available"}

    salary = _salary()
    if salary:
        payload["salary"] = {
            "pool_usd": round(salary.pool_usd, 2),
            "weekly_profit_usd": round(salary.weekly_profit_usd, 2),
            "total_salary_paid_usd": round(salary.total_salary_paid_usd, 2),
            "weekly_target_usd": salary.config.weekly_salary_usd,
            "enabled": salary.config.enabled,
        }
    else:
        payload["salary"] = {"error": "WeeklySalaryMode not available"}

    ecp = _ecp()
    if ecp:
        payload["emergency_protection"] = {
            "level": ecp.current_level().value,
            "is_active": ecp.is_active(),
        }
    else:
        payload["emergency_protection"] = {"error": "EmergencyCapitalProtection not available"}

    return jsonify(payload)


@app.route("/api/owner/alerts", methods=["GET"])
def get_alerts():
    """Return recent text-alert history."""
    limit = min(int(request.args.get("limit", 50)), 200)
    alerts_sys = _alerts()
    if alerts_sys:
        history = alerts_sys.get_history(limit=limit)
    else:
        history = []
    return jsonify({"timestamp": _ts(), "alerts": history})


@app.route("/api/owner/ledger", methods=["GET"])
def get_ledger():
    """Return recent accounting ledger entries."""
    limit = min(int(request.args.get("limit", 50)), 200)
    acct = _accounting()
    if acct:
        entries = acct.get_ledger(limit=limit)
    else:
        entries = []
    return jsonify({"timestamp": _ts(), "entries": entries})


@app.route("/api/owner/reconcile", methods=["GET"])
def run_reconcile():
    """Run ledger reconciliation and return the report."""
    acct = _accounting()
    if not acct:
        return jsonify({"error": "AccountingVerificationLayer not available"}), 503
    report = acct.reconcile()
    return jsonify({"timestamp": _ts(), "reconciliation": report.to_dict()})


@app.route("/api/owner/control", methods=["POST"])
def owner_control():
    """
    Execute an owner control action.

    JSON body fields
    ----------------
    action : str   — one of: emergency_stop, clear_emergency_stop,
                      pause_trading, resume_trading, disable_salary, enable_salary
    pin    : str   — owner PIN
    """
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")
    pin = data.get("pin", "")

    owner = _owner()
    if not owner:
        return jsonify({"success": False, "message": "OwnerControlLayer not available"}), 503

    action_map = {
        "emergency_stop": owner.emergency_stop,
        "clear_emergency_stop": owner.clear_emergency_stop,
        "pause_trading": owner.pause_trading,
        "resume_trading": owner.resume_trading,
        "disable_salary": owner.disable_salary,
        "enable_salary": owner.enable_salary,
    }

    fn = action_map.get(action)
    if not fn:
        return jsonify({
            "success": False,
            "message": f"Unknown action '{action}'. Valid: {list(action_map.keys())}",
        }), 400

    ip = request.remote_addr or ""
    result = fn(pin=pin, ip=ip)

    # Fire a text alert for critical actions
    alerts_sys = _alerts()
    if alerts_sys and result.success and action == "emergency_stop":
        alerts_sys.emergency_mode_triggered(
            level="EMERGENCY",
            drawdown_pct=0.0,
            extra="Manually triggered by owner via dashboard",
        )

    return jsonify(result.to_dict()), 200 if result.success else 403


@app.route("/api/owner/check-profit", methods=["POST"])
def check_profit():
    """
    Test whether a daily profit amount qualifies as a 'big profit day'.

    JSON body fields
    ----------------
    daily_profit_usd : float
    """
    data = request.get_json(force=True, silent=True) or {}
    daily_profit_usd = float(data.get("daily_profit_usd", 0.0))

    owner = _owner()
    threshold = owner._config.big_profit_threshold_usd if owner else 200.0
    is_big = owner.check_big_profit_day(daily_profit_usd) if owner else (daily_profit_usd >= 200.0)

    return jsonify({
        "daily_profit_usd": daily_profit_usd,
        "threshold_usd": threshold,
        "is_big_profit_day": is_big,
        "timestamp": _ts(),
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("OWNER_DASHBOARD_PORT", 5050))
    logger.info("Starting Owner Dashboard API on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=False)
