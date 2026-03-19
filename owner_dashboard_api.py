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

try:
    from bot.minimum_daily_target import get_minimum_daily_target
    _MDT_AVAILABLE = True
except ImportError:
    try:
        from minimum_daily_target import get_minimum_daily_target  # type: ignore
        _MDT_AVAILABLE = True
    except ImportError:
        get_minimum_daily_target = None  # type: ignore
        _MDT_AVAILABLE = False

try:
    from bot.user_registry import get_user_registry
    _USER_REGISTRY_AVAILABLE = True
except ImportError:
    try:
        from user_registry import get_user_registry  # type: ignore
        _USER_REGISTRY_AVAILABLE = True
    except ImportError:
        get_user_registry = None  # type: ignore
        _USER_REGISTRY_AVAILABLE = False

try:
    from bot.kill_switch import KillSwitch
    _KILL_SWITCH_AVAILABLE = True
except ImportError:
    try:
        from kill_switch import KillSwitch  # type: ignore
        _KILL_SWITCH_AVAILABLE = True
    except ImportError:
        KillSwitch = None  # type: ignore
        _KILL_SWITCH_AVAILABLE = False

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


def _mdt():
    if _MDT_AVAILABLE:
        return get_minimum_daily_target()
    return None


def _user_registry():
    if _USER_REGISTRY_AVAILABLE:
        return get_user_registry()
    return None


_global_kill_switch: Any = None


def _get_kill_switch():
    global _global_kill_switch
    if not _KILL_SWITCH_AVAILABLE:
        return None
    if _global_kill_switch is None:
        _global_kill_switch = KillSwitch()
    return _global_kill_switch


def _validate_owner_pin(pin: str) -> bool:
    """
    Validate the owner PIN.

    Checks against OWNER_PIN environment variable first, then falls back to
    the OwnerControlLayer's configured PIN if available.

    Returns True if the PIN is valid (or no PIN is configured).
    """
    expected = os.environ.get("OWNER_PIN", "")
    if not expected:
        # No PIN configured — check owner control layer
        owner = _owner()
        if owner and hasattr(owner, "_config") and hasattr(owner._config, "pin"):
            expected = owner._config.pin
    if expected and pin != expected:
        return False
    return True


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
# Kill Switch endpoints
# ---------------------------------------------------------------------------

@app.route("/api/owner/kill-switch", methods=["GET"])
def kill_switch_status():
    """Return current kill switch status."""
    ks = _get_kill_switch()
    if ks:
        status = ks.get_status()
    else:
        # Fallback: read from owner control layer
        owner = _owner()
        if owner:
            oc_status = owner.get_status()
            status = {
                "is_active": oc_status.get("emergency_stop_active", False),
                "source": "owner_control_layer",
            }
        else:
            status = {"is_active": False, "source": "unavailable"}
    return jsonify({"timestamp": _ts(), "kill_switch": status})


@app.route("/api/owner/kill-switch/activate", methods=["POST"])
def kill_switch_activate():
    """
    Activate the global kill switch (immediate halt).

    JSON body fields
    ----------------
    pin    : str   — owner PIN
    reason : str   — optional reason
    """
    data = request.get_json(force=True, silent=True) or {}
    pin = data.get("pin", "")
    reason = data.get("reason", "Mobile kill switch triggered")

    # Validate PIN via owner control layer
    owner = _owner()
    if owner:
        result = owner.emergency_stop(pin=pin, ip=request.remote_addr or "")
        if not result.success:
            return jsonify({"success": False, "message": result.message}), 403
    else:
        # If owner control unavailable, use kill switch directly with env PIN
        expected = os.environ.get("OWNER_PIN", "")
        if expected and pin != expected:
            return jsonify({"success": False, "message": "Invalid PIN"}), 403

    ks = _get_kill_switch()
    if ks:
        ks.activate(reason=reason, source="MOBILE_DASHBOARD")

    alerts_sys = _alerts()
    if alerts_sys:
        try:
            alerts_sys.emergency_mode_triggered(
                level="EMERGENCY",
                drawdown_pct=0.0,
                extra=f"Kill switch activated: {reason}",
            )
        except Exception:
            pass

    logger.critical("🚨 KILL SWITCH ACTIVATED via dashboard: %s", reason)
    return jsonify({"success": True, "message": "Kill switch activated", "timestamp": _ts()})


@app.route("/api/owner/kill-switch/deactivate", methods=["POST"])
def kill_switch_deactivate():
    """
    Deactivate the global kill switch.

    JSON body fields
    ----------------
    pin    : str   — owner PIN
    reason : str   — optional reason
    """
    data = request.get_json(force=True, silent=True) or {}
    pin = data.get("pin", "")
    reason = data.get("reason", "Manual deactivation via dashboard")

    owner = _owner()
    if owner:
        result = owner.clear_emergency_stop(pin=pin, ip=request.remote_addr or "")
        if not result.success:
            return jsonify({"success": False, "message": result.message}), 403

    ks = _get_kill_switch()
    if ks:
        ks.deactivate(reason=reason)

    logger.info("✅ Kill switch deactivated via dashboard: %s", reason)
    return jsonify({"success": True, "message": "Kill switch deactivated", "timestamp": _ts()})


# ---------------------------------------------------------------------------
# PnL + Salary dashboard endpoint
# ---------------------------------------------------------------------------

@app.route("/api/owner/pnl", methods=["GET"])
def get_pnl_dashboard():
    """
    Return a combined real-time PnL + salary dashboard payload.

    Pulls from:
    - AccountingVerificationLayer (balance, net P&L, trade history)
    - WeeklySalaryMode (salary pool, weekly profit, target)
    - MinimumDailyTarget (daily goal progress, lock status)
    """
    payload: Dict[str, Any] = {"timestamp": _ts()}

    # Accounting / balance
    acct = _accounting()
    if acct:
        summary = acct.get_summary()
        payload["balance_usd"] = summary.get("balance_usd", 0.0)
        payload["net_pnl_usd"] = summary.get("net_pnl_usd", 0.0)
        payload["total_profit_usd"] = summary.get("total_profit_usd", 0.0)
        payload["total_loss_usd"] = summary.get("total_loss_usd", 0.0)
        payload["total_trades"] = summary.get("total_entries", 0)
    else:
        payload["balance_usd"] = None
        payload["net_pnl_usd"] = None
        payload["total_profit_usd"] = None
        payload["total_loss_usd"] = None
        payload["total_trades"] = None

    # Weekly salary
    salary = _salary()
    if salary:
        payload["salary"] = {
            "enabled": salary.config.enabled,
            "pool_usd": round(salary.pool_usd, 2),
            "weekly_profit_usd": round(salary.weekly_profit_usd, 2),
            "total_salary_paid_usd": round(salary.total_salary_paid_usd, 2),
            "weekly_target_usd": salary.config.weekly_salary_usd,
            "weekly_progress_pct": round(
                min(
                    salary.weekly_profit_usd / salary.config.weekly_salary_usd * 100
                    if salary.config.weekly_salary_usd > 0
                    else 0,
                    100,
                ),
                1,
            ),
        }
    else:
        payload["salary"] = {"error": "WeeklySalaryMode not available"}

    # Daily target
    mdt = _mdt()
    if mdt:
        payload["daily_target"] = mdt.get_status()
    else:
        payload["daily_target"] = {"error": "MinimumDailyTarget not available"}

    return jsonify(payload)


# ---------------------------------------------------------------------------
# Daily target management endpoints
# ---------------------------------------------------------------------------

@app.route("/api/owner/daily-target", methods=["GET"])
def get_daily_target():
    """Return current daily target status."""
    mdt = _mdt()
    if not mdt:
        return jsonify({"error": "MinimumDailyTarget not available"}), 503
    return jsonify({"timestamp": _ts(), "daily_target": mdt.get_status()})


@app.route("/api/owner/daily-target/set", methods=["POST"])
def set_daily_target():
    """
    Update the daily profit target.

    JSON body fields
    ----------------
    target_usd : float  — new daily target in USD
    pin        : str    — owner PIN
    """
    data = request.get_json(force=True, silent=True) or {}
    target_usd = float(data.get("target_usd", 0.0))
    pin = data.get("pin", "")

    mdt = _mdt()
    if not mdt:
        return jsonify({"success": False, "message": "MinimumDailyTarget not available"}), 503

    ok = mdt.set_target(target_usd=target_usd, pin=pin)
    if ok:
        return jsonify({"success": True, "message": f"Daily target set to ${target_usd:.2f}", "timestamp": _ts()})
    return jsonify({"success": False, "message": "Invalid PIN or bad target value"}), 403


@app.route("/api/owner/daily-target/unlock", methods=["POST"])
def unlock_daily_target():
    """
    Unlock the bot after the daily target lock.

    JSON body fields
    ----------------
    pin    : str  — owner PIN
    reason : str  — optional reason
    """
    data = request.get_json(force=True, silent=True) or {}
    pin = data.get("pin", "")
    reason = data.get("reason", "Manual unlock via dashboard")

    mdt = _mdt()
    if not mdt:
        return jsonify({"success": False, "message": "MinimumDailyTarget not available"}), 503

    ok = mdt.unlock(pin=pin, reason=reason)
    if ok:
        return jsonify({"success": True, "message": "Daily target lock removed", "timestamp": _ts()})
    return jsonify({"success": False, "message": "Invalid PIN"}), 403


# ---------------------------------------------------------------------------
# User registry (multi-user / business scaling) endpoints
# ---------------------------------------------------------------------------

@app.route("/api/owner/users", methods=["GET"])
def list_users():
    """Return all registered users and a summary."""
    reg = _user_registry()
    if not reg:
        return jsonify({"error": "UserRegistry not available"}), 503
    return jsonify({
        "timestamp": _ts(),
        "summary": reg.get_summary(),
        "users": reg.list_users(),
    })


@app.route("/api/owner/users/register", methods=["POST"])
def register_user():
    """
    Register a new user/subscriber.

    JSON body fields
    ----------------
    user_id          : str   — optional; auto-generated if omitted
    display_name     : str
    email            : str
    plan             : str   — free | starter | pro | elite
    daily_target_usd : float — optional; defaults to plan default
    pin              : str   — owner PIN (required)
    notes            : str   — optional
    """
    data = request.get_json(force=True, silent=True) or {}
    pin = data.get("pin", "")

    if not _validate_owner_pin(pin):
        return jsonify({"success": False, "message": "Invalid PIN"}), 403

    reg = _user_registry()
    if not reg:
        return jsonify({"success": False, "message": "UserRegistry not available"}), 503

    try:
        user = reg.register_user(
            user_id=data.get("user_id"),
            display_name=data.get("display_name", ""),
            email=data.get("email", ""),
            plan=data.get("plan", "starter"),
            daily_target_usd=data.get("daily_target_usd"),
            notes=data.get("notes", ""),
        )
        return jsonify({"success": True, "user": user.to_dict(), "timestamp": _ts()})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/owner/users/<user_id>", methods=["GET"])
def get_user(user_id: str):
    """Return a single user record."""
    reg = _user_registry()
    if not reg:
        return jsonify({"error": "UserRegistry not available"}), 503
    user = reg.get_user(user_id)
    if user is None:
        return jsonify({"error": f"User '{user_id}' not found"}), 404
    return jsonify({"timestamp": _ts(), "user": user.to_dict()})


@app.route("/api/owner/users/<user_id>/kill-switch", methods=["POST"])
def user_kill_switch(user_id: str):
    """
    Enable or disable the kill switch for a specific user.

    JSON body fields
    ----------------
    active : bool  — True to activate, False to deactivate
    reason : str   — optional reason
    pin    : str   — owner PIN
    """
    data = request.get_json(force=True, silent=True) or {}
    pin = data.get("pin", "")
    active = bool(data.get("active", True))
    reason = data.get("reason", "")

    if not _validate_owner_pin(pin):
        return jsonify({"success": False, "message": "Invalid PIN"}), 403

    reg = _user_registry()
    if not reg:
        return jsonify({"success": False, "message": "UserRegistry not available"}), 503

    ok = reg.set_kill_switch(user_id=user_id, active=active, reason=reason)
    if ok:
        state = "activated" if active else "cleared"
        return jsonify({"success": True, "message": f"Kill switch {state} for user '{user_id}'", "timestamp": _ts()})
    return jsonify({"success": False, "message": f"User '{user_id}' not found"}), 404


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("OWNER_DASHBOARD_PORT", 5050))
    logger.info("Starting Owner Dashboard API on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=False)
