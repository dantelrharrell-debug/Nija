import json
from pathlib import Path

from mobile_device_store import MobileDeviceStore


ROOT = Path(__file__).resolve().parents[1]


def test_permanent_mobile_identifier_is_locked():
    config = json.loads((ROOT / "capacitor.config.json").read_text(encoding="utf-8"))
    assert config["appId"] == "com.nijaaitrading.app"
    assert config["server"]["hostname"] == "nijaaitrading.com"


def test_android_manifest_uses_permanent_identifier_and_verified_domain():
    manifest = (ROOT / "mobile/android/config/AndroidManifest.xml.template").read_text(encoding="utf-8")
    assert 'package="com.nijaaitrading.app"' in manifest
    assert 'android:host="nijaaitrading.com"' in manifest
    assert 'android:autoVerify="true"' in manifest


def test_ios_entitlements_include_associated_domains():
    entitlements = (ROOT / "mobile/ios/config/NIJA.entitlements.template").read_text(encoding="utf-8")
    assert "applinks:nijaaitrading.com" in entitlements
    assert "applinks:www.nijaaitrading.com" in entitlements


def test_mobile_api_user_scoped_routes_require_authentication():
    source = (ROOT / "mobile_api.py").read_text(encoding="utf-8")
    protected_handlers = [
        "register_device",
        "unregister_device",
        "list_devices",
        "send_notification",
        "get_dashboard_summary",
        "quick_toggle_trading",
        "get_lightweight_positions",
        "get_recent_trades",
    ]
    for handler in protected_handlers:
        marker = f"@require_auth\ndef {handler}"
        assert marker in source, f"{handler} must remain protected by @require_auth"
    assert "push_tokens = {}" not in source
    assert "get_mobile_device_store" in source


def test_mobile_device_store_persists_encrypts_and_deletes(monkeypatch, tmp_path):
    monkeypatch.setenv("PUSH_TOKEN_ENCRYPTION_KEY", "test-only-stable-secret-do-not-use-in-production")
    db_path = tmp_path / "devices.db"
    store = MobileDeviceStore(str(db_path))
    store.register_device(
        user_id="user-a",
        device_id="device-a",
        platform="android",
        push_token="secret-provider-token",
        device_info={"model": "test"},
    )

    listed = store.list_devices("user-a")
    assert len(listed) == 1
    assert "push_token" not in listed[0]
    assert b"secret-provider-token" not in db_path.read_bytes()

    reopened = MobileDeviceStore(str(db_path))
    assert reopened.count_devices("user-a") == 1
    assert reopened.list_devices("user-a", include_tokens=True)[0]["push_token"] == "secret-provider-token"
    assert reopened.delete_user_devices("user-a") == 1
    assert reopened.count_devices("user-a") == 0


def test_account_deletion_covers_mobile_store_vault_permissions_and_rules():
    source = (ROOT / "account_deletion_api.py").read_text(encoding="utf-8")
    required = [
        "get_mobile_device_store().delete_user_devices(user_id)",
        "_delete_persistent_vault_data(user_id)",
        "_delete_legacy_broker_credentials(user_id)",
        "_delete_user_rules(user_id)",
        "get_permission_validator().user_permissions.pop(user_id, None)",
        "_delete_auth_database_records(user_id)",
    ]
    for marker in required:
        assert marker in source
