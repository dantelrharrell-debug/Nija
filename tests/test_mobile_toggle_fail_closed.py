"""Regression tests for mobile controls that must not claim live execution.

The function is extracted from source so these safety tests can run without
importing production trading modules or contacting brokers.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


def _handler(payload, authenticated_user="member-a", query_user=None):
    source = (ROOT / "mobile_api.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    original = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "quick_toggle_trading"
    )
    original.decorator_list = []
    namespace = {
        "request": SimpleNamespace(get_json=lambda silent=True: payload),
        "jsonify": lambda data: data,
        "_authenticated_user": lambda: authenticated_user,
        "_reject_cross_user": lambda data: (
            ({"error": "Cannot access another user's mobile resources"}, 403)
            if data.get("user_id") not in (None, authenticated_user)
            else None
        ),
        "logger": SimpleNamespace(warning=Mock()),
    }
    exec(compile(ast.Module(body=[original], type_ignores=[]), str(ROOT / "mobile_api.py"), "exec"), namespace)
    return namespace["quick_toggle_trading"](), namespace


def test_enable_request_does_not_claim_trading_started():
    (body, status), namespace = _handler({"enabled": True})
    assert status == 503
    assert body["success"] is False
    assert body["trading_enabled"] is False
    assert body["state_verified"] is False
    assert body["reason"] == "authoritative_controller_not_connected"
    assert namespace["logger"].warning.called


def test_disable_request_does_not_claim_emergency_pause():
    (body, status), _ = _handler({"enabled": False})
    assert status == 503
    assert body["success"] is False
    assert body["state_verified"] is False


def test_cross_account_request_denied_before_controller_check():
    (body, status), namespace = _handler({"enabled": True, "user_id": "member-b"})
    assert status == 403
    assert "another user's" in body["error"]
    assert not namespace["logger"].warning.called


def test_invalid_boolean_denied():
    (body, status), namespace = _handler({"enabled": "true"})
    assert status == 400
    assert "boolean" in body["error"]
    assert not namespace["logger"].warning.called


def test_missing_enabled_denied():
    (body, status), _ = _handler({})
    assert status == 400
    assert "boolean" in body["error"]


def test_route_remains_jwt_protected():
    source = (ROOT / "mobile_api.py").read_text(encoding="utf-8")
    assert '@mobile_api.route("/trading/quick-toggle", methods=["POST"])\n@require_auth' in source
