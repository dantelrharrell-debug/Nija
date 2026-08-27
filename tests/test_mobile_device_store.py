import os

from mobile_device_store import MobileDeviceStore


def _configure_key(monkeypatch):
    monkeypatch.setenv(
        "PUSH_TOKEN_ENCRYPTION_KEY",
        "test-only-high-entropy-mobile-push-secret-that-is-stable",
    )


def test_push_token_persists_encrypted_across_store_instances(tmp_path, monkeypatch):
    _configure_key(monkeypatch)
    db_path = str(tmp_path / "devices.db")
    token = "provider-token-super-secret"

    first = MobileDeviceStore(db_path)
    first.register_device("user-a", "device-1", "ios", token, {"model": "test"})

    raw = open(db_path, "rb").read()
    assert token.encode() not in raw

    second = MobileDeviceStore(db_path)
    public_devices = second.list_devices("user-a")
    assert public_devices[0]["device_id"] == "device-1"
    assert "push_token" not in public_devices[0]

    internal_devices = second.list_devices("user-a", include_tokens=True)
    assert internal_devices[0]["push_token"] == token


def test_device_registration_is_user_scoped(tmp_path, monkeypatch):
    _configure_key(monkeypatch)
    store = MobileDeviceStore(str(tmp_path / "devices.db"))
    store.register_device("user-a", "device-a", "android", "token-a")
    store.register_device("user-b", "device-b", "ios", "token-b")

    assert [d["device_id"] for d in store.list_devices("user-a")] == ["device-a"]
    assert [d["device_id"] for d in store.list_devices("user-b")] == ["device-b"]


def test_provider_token_reassignment_removes_old_owner(tmp_path, monkeypatch):
    _configure_key(monkeypatch)
    store = MobileDeviceStore(str(tmp_path / "devices.db"))
    store.register_device("user-a", "old-device", "android", "rotating-token")
    store.register_device("user-b", "new-device", "android", "rotating-token")

    assert store.count_devices("user-a") == 0
    assert store.count_devices("user-b") == 1


def test_delete_user_devices_is_complete_and_idempotent(tmp_path, monkeypatch):
    _configure_key(monkeypatch)
    store = MobileDeviceStore(str(tmp_path / "devices.db"))
    store.register_device("user-a", "device-1", "ios", "token-1")
    store.register_device("user-a", "device-2", "android", "token-2")

    assert store.delete_user_devices("user-a") == 2
    assert store.count_devices("user-a") == 0
    assert store.delete_user_devices("user-a") == 0


def test_registration_requires_stable_encryption_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("PUSH_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("VAULT_ENCRYPTION_KEY", raising=False)
    store = MobileDeviceStore(str(tmp_path / "devices.db"))

    try:
        store.register_device("user-a", "device-1", "ios", "token-1")
        raised = False
    except RuntimeError:
        raised = True

    assert raised is True
