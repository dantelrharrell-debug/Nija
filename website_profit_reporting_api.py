"""Fail-closed, read-only NIJA website profit reporting API.

Evidence is prepared and signed by a *separate trusted reconciliation process*
and placed in restricted server storage. This module cannot accept visitor
events, purchases, expenses, certification flags or signatures over HTTP.
Nothing in this module changes checkout, subscriptions, or trading authority.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from website_net_profit import net_profit_report

_PERIOD = re.compile(r"^[0-9]{4}-(?:0[1-9]|1[0-2])$")
_MAX_BYTES = 8 * 1024 * 1024
_ROUTE = "/api/admin/website-profit"


def _canonical(data: dict[str, Any]) -> bytes:
    """Stable, unambiguous encoding for a server-side reconciliation signature."""
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sign_evidence(data: dict[str, Any], key: str) -> str:
    """Used only by an independent, authenticated finance importer.

    No signing functionality is exposed via the web API.
    """
    unsigned = {k: v for k, v in data.items() if k != "signature"}
    return hmac.new(key.encode("utf-8"), _canonical(unsigned), hashlib.sha256).hexdigest()


def _load_signed_evidence(period: str, folder: str, signing_key: str) -> dict[str, Any] | None:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        return None
    path = root / (period + ".json")
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_BYTES:
            return None
        if path.resolve().parent != root:
            return None
        with path.open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            return None
        envelope = json.loads(raw)
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None
    provided = envelope.get("signature")
    if not isinstance(provided, str) or re.fullmatch(r"[0-9a-f]{64}", provided) is None:
        return None
    try:
        expected = sign_evidence(envelope, signing_key)
    except (TypeError, ValueError, OverflowError):
        return None
    if not hmac.compare_digest(provided, expected):
        return None
    if envelope.get("reporting_period") != period:
        return None
    if not isinstance(envelope.get("revenue_events"), list):
        return None
    if not isinstance(envelope.get("cost_events"), list):
        return None
    if len(envelope["revenue_events"]) + len(envelope["cost_events"]) > 150000:
        return None
    return envelope


def create_profit_blueprint() -> Blueprint:
    """Register an optional admin-only aggregate GET endpoint on billing API."""
    blueprint = Blueprint("website_profit_reporting", __name__)

    @blueprint.get(_ROUTE)
    def get_website_profit():
        dashboard_key = os.getenv("NIJA_PROFIT_DASHBOARD_TOKEN", "").strip()
        signing_key = os.getenv("NIJA_PROFIT_EVIDENCE_HMAC_KEY", "").strip()
        folder = os.getenv("NIJA_PROFIT_EVIDENCE_DIR", "").strip()
        # Unprovisioned deployment is explicitly NOT an enabled dashboard.
        if (min(len(dashboard_key), len(signing_key)) < 32
                or not folder or hmac.compare_digest(dashboard_key, signing_key)):
            response = jsonify({"status": "unavailable", "reason": "profit_reporting_not_configured"})
            response.headers["Cache-Control"] = "no-store"
            return response, 503

        header = request.headers.get("Authorization", "")
        parts = header.split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer" or not hmac.compare_digest(parts[1], dashboard_key):
            response = jsonify({"error": "administrator_authorization_required"})
            response.headers["Cache-Control"] = "no-store"
            return response, 401

        period = request.args.get("period", "")
        if not isinstance(period, str) or not _PERIOD.fullmatch(period):
            response = jsonify({"error": "valid_reporting_period_required", "format": "YYYY-MM"})
            response.headers["Cache-Control"] = "no-store"
            return response, 400

        evidence = _load_signed_evidence(period, folder, signing_key)
        if evidence is None:
            response = jsonify({
                "reporting_period": period,
                "status": "unverified",
                "reason": "signed_reconciliation_evidence_not_available",
                "net_profit_usd": None,
                "net_profit_per_visitor_usd": None,
                "net_profit_per_qualified_lead_usd": None,
                "visitor_target_met": None,
                "target_usd_per_visitor": "1.00",
            })
            response.headers["Cache-Control"] = "no-store"
            return response, 200

        certifications = evidence.get("certification", {})
        if not isinstance(certifications, dict):
            certifications = {}
        # In addition to signing, independent analytics, provider receipts,
        # refunds and all cost allocations must each be explicitly approved.
        verified_visitors = certifications.get("visitor_counts_verified") is True
        verified_revenue = certifications.get("provider_revenue_verified") is True
        verified_expenses = certifications.get("all_costs_verified") is True
        verified_leads = certifications.get("qualified_leads_verified") is True
        aggregates = evidence.get("aggregate_counts")
        if aggregates is not None and not isinstance(aggregates, dict):
            response = jsonify({"status": "invalid_evidence", "reporting_period": period})
            response.headers["Cache-Control"] = "no-store"
            return response, 503
        if aggregates is None:
            aggregates = {}
        period_closed = period < datetime.now(timezone.utc).strftime("%Y-%m")
        revenue_complete = (
            period_closed and verified_visitors and verified_revenue
            and evidence.get("revenue_complete") is True
        )
        costs_complete = (
            period_closed and verified_expenses
            and evidence.get("costs_complete") is True
        )
        try:
            result = net_profit_report(
                evidence["revenue_events"],
                evidence["cost_events"],
                reporting_period=period,
                revenue_complete=revenue_complete,
                costs_complete=costs_complete,
                certified_unique_visitors=aggregates.get("unique_visitors") if verified_visitors else None,
                certified_qualified_leads=aggregates.get("unique_qualified_leads") if verified_leads else None,
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            response = jsonify({"status": "invalid_evidence", "reporting_period": period})
            response.headers["Cache-Control"] = "no-store"
            return response, 503

        if not period_closed:
            result["status"] = "reporting_period_open"
        elif result["unique_visitors"] == 0:
            result["status"] = "no_verified_visitors"
            result["net_profit_usd"] = None
            result["net_profit_per_visitor_usd"] = None
            result["net_profit_per_qualified_lead_usd"] = None
            result["visitor_target_met"] = None

        if not verified_leads:
            # Do not claim a per-lead profit ratio for unverified CRM evidence.
            result["net_profit_per_qualified_lead_usd"] = None
            result["qualified_lead_count_source"] = "unverified"
        result["target_usd_per_visitor"] = "1.00"
        result["source_status"] = {
            "visitor_counts_verified": verified_visitors,
            "provider_revenue_verified": verified_revenue,
            "all_costs_verified": verified_expenses,
            "qualified_leads_verified": verified_leads,
            "reporting_period_closed": period_closed,
        }
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return blueprint
