# bot/tradingview_webhook/__init__.py
"""
Minimal tradingview_webhook package for NIJA.
Provides a Flask blueprint to accept TradingView alerts at /webhook.
"""

from flask import Blueprint, request, jsonify
from .webhook_handler import handle_tradingview_webhook

bp = Blueprint("tradingview_webhook", __name__)

@bp.route("/webhook", methods=["POST"])
def webhook_route():
    return handle_tradingview_webhook(request)
