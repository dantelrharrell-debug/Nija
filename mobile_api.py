"""NIJA mobile API extensions.

User-scoped mobile endpoints authenticate with the canonical API JWT and derive
identity from the token. Push-device registrations are persisted by
``mobile_device_store`` and push delivery is delegated to ``push_notifications``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from flask import Blueprint, jsonify, request

from api_server import require_auth
from mobile_device_store import get_mobile_device_store
from push_notifications import get_push_notification_service

logger = logging.getLogger(__name__)

MOBILE_API_BASE = "/api/mobile"
mobile_api = Blueprint("mobile_api", __name__, url_prefix=MOBILE_API_BASE)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _authenticated_user() -> str:
    return str(request.user_id)


def _reject_cross_user(payload: Dict) -> Optional[tuple]:
    """Reject legacy payloads that try to act as another user."""
    supplied = payload.get("user_id")
    if supplied is not None and str(supplied) != _authenticated_user():
        return jsonify({"error": "Cannot access another user's mobile resources"}), 403
    return None


@mobile_api.route("/status", methods=["GET"])
def get_mobile_status():
    return jsonify({"status": "ok", "service": "mobile_api", "timestamp": _utcnow()})


@mobile_api.route("/device/register", methods=["POST"])
@require_auth
def register_device():
    data = request.get_json(silent=True) or {}
    cross_user = _reject_cross_user(data)
    if cross_user:
        return cross_user

    required = ("push_token", "platform", "device_id")
    missing = [field for field in required if not str(data.get(field, "")).strip()]
    if missing:
        return jsonify({"error": "Missing required field(s)", "fields": missing}), 400

    try:
        get_mobile_device_store().register_device(
            user_id=_authenticated_user(),
            push_token=str(data["push_token"]),
            platform=str(data["platform"]),
            device_id=str(data["device_id"]),
            device_info=data.get("device_info") if isinstance(data.get("device_info"), dict) else {},
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        logger.error("Mobile device registration unavailable: %s", exc)
        return jsonify({"error": "Push registration is not configured on this server"}), 503

    return jsonify({
        "success": True,
        "message": "Device registered successfully",
        "device_id": str(data["device_id"]),
        "platform": str(data["platform"]).lower(),
    })


@mobile_api.route("/device/unregister", methods=["POST", "DELETE"])
@require_auth
def unregister_device():
    data = request.get_json(silent=True) or {}
    cross_user = _reject_cross_user(data)
    if cross_user:
        return cross_user
    device_id = str(data.get("device_id", "")).strip()
    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    deleted = get_mobile_device_store().unregister_device(_authenticated_user(), device_id)
    return jsonify({"success": True, "removed": deleted, "device_id": device_id})


@mobile_api.route("/device/list", methods=["GET"])
@require_auth
def list_devices():
    supplied = request.args.get("user_id")
    if supplied and supplied != _authenticated_user():
        return jsonify({"error": "Cannot access another user's mobile resources"}), 403
    devices = get_mobile_device_store().list_devices(_authenticated_user())
    return jsonify({"success": True, "devices": devices, "count": len(devices)})


def send_push_notification(user_id: str, title: str, body: str, data: Optional[Dict] = None) -> bool:
    """Internal push entry point. Provider credentials may be added later."""
    result = get_push_notification_service().send_to_user(
        user_id=user_id,
        title=title,
        body=body,
        data=data or {},
    )
    return result.sent > 0


@mobile_api.route("/notifications/send", methods=["POST"])
@require_auth
def send_notification():
    """Allow an authenticated user to send only to their own registered devices.

    System/admin notifications should call ``send_push_notification`` internally;
    this route deliberately does not provide cross-user dispatch.
    """
    data = request.get_json(silent=True) or {}
    cross_user = _reject_cross_user(data)
    if cross_user:
        return cross_user
    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    if not title or not body:
        return jsonify({"error": "title and body are required"}), 400

    result = get_push_notification_service().send_to_user(
        _authenticated_user(), title, body, data.get("data") if isinstance(data.get("data"), dict) else {}
    )
    status = 200 if result.sent else (503 if result.not_configured else 502)
    return jsonify(result.to_dict()), status


@mobile_api.route("/dashboard/summary", methods=["GET"])
@require_auth
def get_dashboard_summary():
    supplied = request.args.get("user_id")
    if supplied and supplied != _authenticated_user():
        return jsonify({"error": "Cannot access another user's dashboard"}), 403
    return jsonify({
        "success": True,
        "data": {
            "user_id": _authenticated_user(),
            "trading_active": False,
            "stats": {"total_pnl": 0.0, "win_rate": 0.0, "total_trades": 0, "active_positions": 0},
            "account": {"balance": 0.0, "tier": "basic", "max_position_size": 100.0},
            "last_updated": _utcnow(),
        },
    })


@mobile_api.route("/trading/quick-toggle", methods=["POST"])
@require_auth
def quick_toggle_trading():
    data = request.get_json(silent=True) or {}
    cross_user = _reject_cross_user(data)
    if cross_user:
        return cross_user
    if "enabled" not in data or not isinstance(data["enabled"], bool):
        return jsonify({"error": "enabled must be a boolean"}), 400

    user_id = _authenticated_user()
    enabled = data["enabled"]
    logger.info("Mobile trading toggle requested user_id=%s enabled=%s", user_id, enabled)
    send_push_notification(
        user_id,
        "Trading Enabled" if enabled else "Trading Disabled",
        "NIJA is now actively monitoring markets and executing trades" if enabled else "NIJA has stopped monitoring markets",
        {"type": "trading_status", "enabled": enabled},
    )
    return jsonify({"success": True, "trading_enabled": enabled})


@mobile_api.route("/positions/lightweight", methods=["GET"])
@require_auth
def get_lightweight_positions():
    supplied = request.args.get("user_id")
    if supplied and supplied != _authenticated_user():
        return jsonify({"error": "Cannot access another user's positions"}), 403
    return jsonify({"success": True, "positions": [], "count": 0, "last_updated": _utcnow()})


@mobile_api.route("/trades/recent", methods=["GET"])
@require_auth
def get_recent_trades():
    supplied = request.args.get("user_id")
    if supplied and supplied != _authenticated_user():
        return jsonify({"error": "Cannot access another user's trades"}), 403
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    if not 1 <= limit <= 50:
        return jsonify({"error": "limit must be between 1 and 50"}), 400
    return jsonify({"success": True, "trades": [], "count": 0, "limit": limit, "last_updated": _utcnow()})


@mobile_api.route("/config", methods=["GET"])
def get_mobile_config():
    """Non-sensitive app compatibility information."""
    return jsonify({
        "success": True,
        "config": {
            "api_version": "1.1.0",
            "min_app_version": "1.0.0",
            "features": {
                "push_notifications": True,
                "biometric_auth": True,
                "real_time_updates": True,
                "multi_exchange": True,
            },
            "refresh_intervals": {"dashboard": 30, "positions": 10, "trades": 60},
            "supported_exchanges": ["coinbase", "kraken", "binance", "okx", "alpaca"],
        },
    })


@mobile_api.route("/simulation/dashboard", methods=["GET"])
@require_auth
def get_simulation_dashboard():
    try:
        results_path = Path("/home/runner/work/Nija/Nija/results/demo_backtest.json")
        if not results_path.exists():
            return jsonify({"mode": "education", "balance": 10000.0, "status": "ready", "message": "Start trading to see results"})
        with results_path.open("r", encoding="utf-8") as fh:
            results = json.load(fh)
        summary = results.get("summary", {})
        return jsonify({
            "mode": "education",
            "balance": {
                "initial": summary.get("initial_balance", 10000.0),
                "current": summary.get("final_balance", 10000.0),
                "pnl": summary.get("total_pnl", 0.0),
                "pnl_pct": summary.get("total_return_pct", 0.0),
            },
            "performance": {
                "total_trades": summary.get("total_trades", 0),
                "win_rate": round(summary.get("win_rate", 0.0) * 100, 1),
                "profit_factor": round(summary.get("profit_factor", 0.0), 2),
                "sharpe_ratio": round(summary.get("sharpe_ratio", 0.0), 2),
            },
            "risk": {
                "max_drawdown": summary.get("max_drawdown", 0.0),
                "max_drawdown_pct": round(summary.get("max_drawdown_pct", 0.0), 2),
            },
            "timestamp": _utcnow(),
        })
    except Exception:
        logger.exception("Error retrieving simulation dashboard")
        return jsonify({"error": "Failed to load simulation data"}), 500


@mobile_api.route("/simulation/trades/recent", methods=["GET"])
@require_auth
def get_recent_simulation_trades():
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    if not 1 <= limit <= 50:
        return jsonify({"error": "limit must be between 1 and 50"}), 400

    try:
        results_path = Path("/home/runner/work/Nija/Nija/results/demo_backtest.json")
        if not results_path.exists():
            return jsonify({"trades": [], "total": 0, "message": "No simulation trades yet"})
        with results_path.open("r", encoding="utf-8") as fh:
            results = json.load(fh)
        all_trades = results.get("trades", [])
        recent = list(reversed(all_trades[-limit:]))
        formatted = [{
            "symbol": trade.get("symbol", ""),
            "side": trade.get("side", ""),
            "pnl": round(trade.get("pnl", 0.0), 2),
            "pnl_pct": round(trade.get("pnl_pct", 0.0), 2),
            "entry_time": trade.get("entry_time", ""),
            "exit_time": trade.get("exit_time", ""),
            "exit_reason": trade.get("exit_reason", ""),
            "status": "win" if trade.get("pnl", 0) > 0 else "loss" if trade.get("pnl", 0) < 0 else "breakeven",
        } for trade in recent]
        return jsonify({"trades": formatted, "total": len(all_trades), "showing": len(formatted)})
    except Exception:
        logger.exception("Error retrieving simulation trades")
        return jsonify({"error": "Failed to load trades"}), 500


__all__ = ["mobile_api", "send_push_notification", "MOBILE_API_BASE"]
