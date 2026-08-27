from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mobile_api_has_no_in_memory_push_token_registry():
    source = (ROOT / "mobile_api.py").read_text(encoding="utf-8")
    assert "push_tokens = {}" not in source
    assert "get_mobile_device_store" in source


def test_sensitive_mobile_routes_are_authenticated():
    source = (ROOT / "mobile_api.py").read_text(encoding="utf-8")
    route_functions = [
        "register_device",
        "unregister_device",
        "list_devices",
        "send_notification",
        "get_dashboard_summary",
        "quick_toggle_trading",
        "get_lightweight_positions",
        "get_recent_trades",
        "get_simulation_dashboard",
        "get_recent_simulation_trades",
    ]
    for function_name in route_functions:
        marker = f"@require_auth\ndef {function_name}"
        assert marker in source, f"{function_name} must remain JWT protected"


def test_deployed_gateway_fail_closes_mobile_namespaces():
    source = (ROOT / "mobile_backend_server.py").read_text(encoding="utf-8")
    assert '"/api/mobile/"' in source
    assert '"/api/v1/"' in source
    assert '"/api/account/"' in source
    assert "get_user_database().get_user(user_id)" in source
    assert 'return jsonify({"error": "Authentication required"}), 401' in source


def test_account_deletion_covers_persistent_mobile_and_vault_data():
    source = (ROOT / "account_deletion_api.py").read_text(encoding="utf-8")
    assert "get_mobile_device_store().delete_user_devices" in source
    assert "DELETE FROM credentials WHERE user_id" in source
    assert "DELETE FROM audit_log WHERE user_id" in source
    assert "user_permissions.pop(user_id" in source
    assert "_delete_user_rules(user_id)" in source


def test_native_push_registration_uses_bearer_auth():
    source = (ROOT / "frontend/static/js/capacitor-init.js").read_text(encoding="utf-8")
    assert "/api/mobile/device/register" in source
    assert "Authorization': `Bearer ${token}`" in source
    assert "appUrlOpen" in source
    assert "Blocked untrusted deep link origin" in source
