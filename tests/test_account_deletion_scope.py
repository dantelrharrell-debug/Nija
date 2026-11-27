"""Isolated HTTP/SQLite checks for the existing account cleanup boundary.

The canonical JWT functions are loaded without starting api_server's runtime.
Real Flask requests, signed synthetic JWTs and the real encrypted mobile device
store are used. Runtime managers are test adapters with temporary stores; no
production credentials, accounts, remote services or trading modules are loaded.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import secrets
import socket
import sqlite3
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Dict, Optional

import jwt
import pytest
from flask import Flask, jsonify, request

from mobile_device_store import MobileDeviceStore


ROOT = Path(__file__).resolve().parents[1]
USER_A = "synthetic-account-a"
USER_B = "synthetic-account-b"
AUTH_TABLES = ("users", "sessions", "login_history")
UNSUPPORTED_AUTH = ("email_verification_tokens", "two_factor_auth", "two_factor_backup_codes")


def _rows(path: Path, table: str, user_id: str) -> int:
    with sqlite3.connect(path) as connection:
        return connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_id,)
        ).fetchone()[0]


def _module(monkeypatch, name: str, **attributes: object) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def isolated_api(monkeypatch, tmp_path):
    def no_network(*args, **kwargs):
        raise AssertionError("Network access is forbidden in account deletion tests")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setenv("SECRETS_BACKEND", "env")
    monkeypatch.setenv("PUSH_TOKEN_ENCRYPTION_KEY", secrets.token_urlsafe(32))

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY=secrets.token_urlsafe(32))
    auth_module = _module(
        monkeypatch, "api_server", app=app, jwt=jwt, request=request, jsonify=jsonify,
        wraps=wraps, Optional=Optional, Dict=Dict, logger=logging.getLogger("test.auth"),
    )
    auth_source = ast.parse((ROOT / "api_server.py").read_text(encoding="utf-8"))
    selected = [
        node for node in auth_source.body
        if isinstance(node, ast.FunctionDef) and node.name in {"decode_jwt_token", "require_auth"}
    ]
    assert len(selected) == 2
    exec(compile(ast.Module(body=selected, type_ignores=[]), "api_server.py", "exec"), auth_module.__dict__)

    auth_path = tmp_path / "auth.sqlite3"
    vault_path = tmp_path / "vault.sqlite3"
    for path, tables in (
        (auth_path, AUTH_TABLES + UNSUPPORTED_AUTH),
        (vault_path, ("credentials", "audit_log")),
    ):
        with sqlite3.connect(path) as connection:
            for table in tables:
                connection.execute(f"CREATE TABLE {table} (user_id TEXT, value TEXT)")
                connection.executemany(
                    f"INSERT INTO {table} VALUES (?, ?)", [(USER_A, "test-a"), (USER_B, "test-b")]
                )

    user_db = types.SimpleNamespace(
        db_path=str(auth_path), get_user=lambda user: {"user_id": user} if _rows(auth_path, "users", user) else None
    )
    auth_module.user_db = user_db
    vault = types.SimpleNamespace(
        db_path=str(vault_path),
        list_user_brokers=lambda user: ["kraken"] if _rows(vault_path, "credentials", user) else [],
    )
    legacy = types.SimpleNamespace(user_keys={USER_A: {"kraken": "test-a"}, USER_B: {"kraken": "test-b"}})
    legacy.list_user_brokers = lambda user: list(legacy.user_keys.get(user, {}))
    legacy.delete_user_api_key = lambda user, broker: legacy.user_keys.get(user, {}).pop(broker, None) is not None
    users = types.SimpleNamespace(users={USER_A: {}, USER_B: {}})
    permissions = types.SimpleNamespace(user_permissions={USER_A: {}, USER_B: {}})
    rules_paths = {user: tmp_path / f"{user}.json" for user in (USER_A, USER_B)}
    for path in rules_paths.values():
        path.write_text('{"synthetic": true}', encoding="utf-8")
    rules = types.SimpleNamespace(
        _rules_cache={USER_A: {}, USER_B: {}},
        _get_user_lock=lambda user: threading.RLock(),
        _rules_file=lambda user: str(rules_paths[user]),
    )
    devices = MobileDeviceStore(str(tmp_path / "devices.sqlite3"))
    for user in (USER_A, USER_B):
        devices.register_device(user, f"device-{user}", "ios", f"synthetic-push-{user}")

    _module(monkeypatch, "auth", __path__=[], get_api_key_manager=lambda: legacy, get_user_manager=lambda: users)
    _module(monkeypatch, "auth.user_database", get_user_database=lambda: user_db)
    _module(monkeypatch, "execution", get_permission_validator=lambda: permissions)
    _module(monkeypatch, "vault", get_vault=lambda: vault)
    _module(monkeypatch, "bot", __path__=[])
    _module(monkeypatch, "bot.user_rules_engine", get_user_rules_engine=lambda: rules)
    monkeypatch.setattr("mobile_device_store.get_mobile_device_store", lambda: devices)

    spec = importlib.util.spec_from_file_location("isolated_account_deletion", ROOT / "account_deletion_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app.register_blueprint(module.account_deletion_api)

    # Uncovered local/provider/backup fixtures must not be touched or certified.
    outside = tmp_path / "outside-scope.fixture.json"
    outside_bytes = (
        b'{"website_leads":true,"nija_broker_vault":true,"provider_copy":true,"backup":true}'
    )
    outside.write_bytes(outside_bytes)

    def headers(user=USER_A, *, expired=False):
        expiry = datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1)
        token = jwt.encode({"user_id": user, "exp": expiry}, app.config["SECRET_KEY"], algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    return types.SimpleNamespace(
        client=app.test_client(), module=module, headers=headers, auth_path=auth_path, vault_path=vault_path,
        legacy=legacy, users=users, permissions=permissions, rules=rules, rules_paths=rules_paths,
        devices=devices, outside=outside, outside_bytes=outside_bytes,
    )


def _delete(api, **payload):
    return api.client.delete(
        "/api/account/deletion", headers=api.headers(),
        json={"confirmation": "DELETE MY NIJA ACCOUNT", **payload},
    )


@pytest.mark.parametrize("method", ["get", "delete"])
@pytest.mark.parametrize("authorization", ["missing", "invalid", "expired"])
def test_scope_routes_keep_canonical_jwt_authentication(isolated_api, method, authorization):
    api = isolated_api
    headers = {} if authorization == "missing" else {"Authorization": "Bearer invalid"}
    if authorization == "expired":
        headers = api.headers(expired=True)
    response = getattr(api.client, method)("/api/account/deletion", headers=headers)
    assert response.status_code == 401
    assert _rows(api.auth_path, "users", USER_A) == 1
    assert _rows(api.vault_path, "credentials", USER_A) == 1


def test_preconfirmation_notice_is_truthful_and_read_only(isolated_api):
    api = isolated_api
    response = api.client.get("/api/account/deletion", headers=api.headers())
    assert response.status_code == 200
    body = response.get_json()
    assert body["available"] is True
    assert body["confirmation_phrase"] == "DELETE MY NIJA ACCOUNT"
    assert body["deletion_scope"] == "covered_active_stores_only"
    outside = " ".join(body["not_covered"])
    for category in ("member broker vault", "authentication-token", "two-factor", "billing", "CRM", "backups", "logs"):
        assert category in outside
    assert "may remain" in body["retention_notice"]
    assert "does not retain an account-linked record" not in body["retention_notice"]
    assert "No separate privacy request is submitted automatically" in body["privacy_follow_up"]
    assert "support@nijaaitrading.com" in body["privacy_follow_up"]
    assert "does not cancel a separately managed subscription" in body["privacy_follow_up"]
    assert _rows(api.auth_path, "users", USER_A) == 1
    assert api.devices.count_devices(USER_A) == 1
    assert api.rules_paths[USER_A].exists()


def test_confirmation_remains_required_without_any_cleanup(isolated_api):
    api = isolated_api
    response = api.client.delete("/api/account/deletion", headers=api.headers(), json={})
    assert response.status_code == 400
    assert response.get_json()["required_confirmation"] == "DELETE MY NIJA ACCOUNT"
    assert _rows(api.auth_path, "users", USER_A) == 1
    assert _rows(api.vault_path, "credentials", USER_A) == 1
    assert api.devices.count_devices(USER_A) == 1


def test_success_cleans_only_covered_authenticated_user_stores(isolated_api, caplog):
    api = isolated_api
    notice = api.client.get("/api/account/deletion", headers=api.headers()).get_json()
    with caplog.at_level(logging.WARNING, logger="nija.account_deletion"):
        response = _delete(api, user_id=USER_B)
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["status"] == "deleted"
    assert body["broker_credentials_removed"] == ["kraken"]
    assert body["mobile_devices_removed"] == 1
    assert body["trading_rules_removed"] is True
    for key in ("deletion_scope", "not_covered", "retention_notice", "privacy_follow_up"):
        assert body[key] == notice[key]
    assert "only from the active stores covered" in body["message"]
    assert "backups are outside this request" in body["message"]

    for table in AUTH_TABLES:
        assert _rows(api.auth_path, table, USER_A) == 0
        assert _rows(api.auth_path, table, USER_B) == 1
    for table in ("credentials", "audit_log"):
        assert _rows(api.vault_path, table, USER_A) == 0
        assert _rows(api.vault_path, table, USER_B) == 1
    for table in UNSUPPORTED_AUTH:
        assert _rows(api.auth_path, table, USER_A) == 1
        assert _rows(api.auth_path, table, USER_B) == 1
    for mapping in (api.legacy.user_keys, api.users.users, api.permissions.user_permissions, api.rules._rules_cache):
        assert USER_A not in mapping
        assert USER_B in mapping
    assert api.devices.count_devices(USER_A) == 0
    assert api.devices.count_devices(USER_B) == 1
    assert not api.rules_paths[USER_A].exists()
    assert api.rules_paths[USER_B].exists()
    assert api.outside.read_bytes() == api.outside_bytes
    logs = " ".join(record.getMessage() for record in caplog.records if record.name == "nija.account_deletion")
    assert "ACCOUNT_DELETED scope=covered_active_stores_only" in logs
    assert USER_A not in logs and USER_B not in logs


@pytest.mark.parametrize("failure_stage", ["mobile_devices", "authentication_store"])
def test_partial_cleanup_never_claims_success_or_logs_raw_error(isolated_api, monkeypatch, caplog, failure_stage):
    api = isolated_api
    raw_error = f"{USER_A}: synthetic sensitive provider detail"

    def fail(*args, **kwargs):
        raise RuntimeError(raw_error)

    if failure_stage == "mobile_devices":
        monkeypatch.setattr(api.devices, "delete_user_devices", fail)
    else:
        monkeypatch.setattr(api.module, "_delete_auth_database_records", fail)
    with caplog.at_level(logging.ERROR, logger="nija.account_deletion"):
        response = _delete(api)
    assert response.status_code == 500
    body = response.get_json()
    assert "success" not in body and body.get("status") != "deleted"
    assert "could not be confirmed" in body["message"]
    assert "Cleanup may be partial" in body["message"]
    assert "does not confirm that account access has been revoked" in body["message"]
    assert "fail-closed" not in body["message"]
    assert body["error"] == "Account deletion could not be confirmed"
    assert _rows(api.vault_path, "credentials", USER_A) == 0
    assert _rows(api.auth_path, "users", USER_A) == 1
    assert _rows(api.auth_path, "sessions", USER_A) == 1
    assert _rows(api.vault_path, "credentials", USER_B) == 1
    assert _rows(api.auth_path, "users", USER_B) == 1
    assert api.outside.read_bytes() == api.outside_bytes
    # The canonical decorator still accepts this valid JWT after partial
    # cleanup. Do not substitute a disclosure for deployed revocation proof.
    assert api.client.get("/api/account/deletion", headers=api.headers()).status_code == 200
    records = [record for record in caplog.records if record.name == "nija.account_deletion"]
    logs = " ".join(record.getMessage() for record in records)
    assert f"ACCOUNT_DELETION_FAILED stage={failure_stage} error_type=RuntimeError" in logs
    assert "ACCOUNT_DELETED " not in logs
    assert USER_A not in logs and raw_error not in logs
    assert all(record.exc_info is None for record in records)


def test_repeat_request_denies_deleted_jwt_subject(isolated_api):
    api = isolated_api
    assert _delete(api).status_code == 200
    response = _delete(api)
    assert response.status_code == 401
    assert response.get_json() == {"error": "Account is unavailable"}
    assert _rows(api.auth_path, "users", USER_B) == 1
    assert api.devices.count_devices(USER_B) == 1



def test_existing_signed_token_is_rejected_after_successful_account_deletion(isolated_api):
    api = isolated_api
    signed_headers = api.headers()
    assert api.client.get("/api/account/deletion", headers=signed_headers).status_code == 200
    assert _delete(api).status_code == 200
    # Previously valid signed JWTs must not authenticate against a deleted subject.
    for method in ("get", "delete"):
        response = getattr(api.client, method)("/api/account/deletion", headers=signed_headers)
        assert response.status_code == 401
        assert response.get_json() == {"error": "Account is unavailable"}
    assert _rows(api.auth_path, "users", USER_B) == 1


def test_disabled_account_denies_unexpired_valid_token(isolated_api, monkeypatch):
    api = isolated_api
    database = sys.modules["api_server"].user_db
    original = database.get_user

    def disabled(user_id):
        account = original(user_id)
        return {**account, "enabled": False} if account and user_id == USER_A else account

    monkeypatch.setattr(database, "get_user", disabled)
    response = api.client.get("/api/account/deletion", headers=api.headers())
    assert response.status_code == 401
    assert response.get_json() == {"error": "Account is unavailable"}
    assert _rows(api.auth_path, "users", USER_A) == 1


def test_auth_account_lookup_failure_fails_closed_without_logging_details(isolated_api, monkeypatch, caplog):
    api = isolated_api
    database = sys.modules["api_server"].user_db

    def broken_lookup(_user_id):
        raise sqlite3.OperationalError("synthetic-database-location-is-private")

    monkeypatch.setattr(database, "get_user", broken_lookup)
    with caplog.at_level(logging.ERROR, logger="test.auth"):
        response = api.client.get("/api/account/deletion", headers=api.headers())
    assert response.status_code == 503
    assert response.get_json() == {"error": "Authentication temporarily unavailable"}
    logs = " ".join(row.getMessage() for row in caplog.records)
    assert "AUTH_SUBJECT_LOOKUP_FAILED error_type=OperationalError" in logs
    assert USER_A not in logs and "synthetic-database-location-is-private" not in logs
    assert _rows(api.auth_path, "users", USER_A) == 1



@pytest.mark.parametrize("source_file", ["api_server.py", "gateway.py"])
def test_both_api_entrypoints_reject_stale_and_disabled_jwts(source_file, monkeypatch, caplog):
    """Execute the actual decorators without loading production managers.

    Token subjects must still resolve to a current enabled user. Missing or
    unavailable account records deny even a correctly signed, unexpired JWT.
    """
    app = Flask("synthetic-" + source_file)
    app.config.update(TESTING=True, SECRET_KEY=secrets.token_urlsafe(32))
    source = ast.parse((ROOT / source_file).read_text(encoding="utf-8"))
    functions = [
        node for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"decode_jwt_token", "require_auth"}
    ]
    assert len(functions) == 2
    database = types.SimpleNamespace(
        get_user=lambda uid: {"user_id": uid, "enabled": True}
        if uid == USER_A else None
    )
    namespace = dict(
        app=app, jwt=jwt, request=request, jsonify=jsonify, wraps=wraps,
        logger=logging.getLogger("synthetic.auth." + source_file),
        Optional=Optional, Dict=Dict, user_db=database,
    )
    exec(compile(ast.Module(body=functions, type_ignores=[]), source_file, "exec"), namespace)

    @app.get("/synthetic/probe")
    @namespace["require_auth"]
    def protected_probe():
        return jsonify({"user_id": request.user_id})

    client = app.test_client()

    def authorization(subject):
        token = jwt.encode({
            "user_id": subject,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        }, app.config["SECRET_KEY"], algorithm="HS256")
        return {"Authorization": "Bearer " + token}

    assert client.get("/synthetic/probe", headers=authorization(USER_A)).status_code == 200
    for subject in (USER_B, "   ", 17, None):
        response = client.get("/synthetic/probe", headers=authorization(subject))
        assert response.status_code == 401
        assert response.get_json()["error"] in ("Account is unavailable", "Invalid or expired token")

    monkeypatch.setattr(
        database, "get_user",
        lambda uid: {"user_id": uid, "enabled": False} if uid == USER_A else None,
    )
    disabled = client.get("/synthetic/probe", headers=authorization(USER_A))
    assert disabled.status_code == 401
    assert disabled.get_json() == {"error": "Account is unavailable"}

    def unavailable(_):
        raise sqlite3.OperationalError("private-backend-detail")

    monkeypatch.setattr(database, "get_user", unavailable)
    with caplog.at_level(logging.ERROR, logger=namespace["logger"].name):
        error = client.get("/synthetic/probe", headers=authorization(USER_A))
    assert error.status_code == 503
    assert error.get_json() == {"error": "Authentication temporarily unavailable"}
    assert "private-backend-detail" not in error.get_data(as_text=True)
    logs = " ".join(entry.getMessage() for entry in caplog.records
                    if entry.name == namespace["logger"].name)
    assert "AUTH_SUBJECT_LOOKUP_FAILED error_type=OperationalError" in logs
    assert USER_A not in logs and "private-backend-detail" not in logs



@pytest.mark.parametrize("source_file", ["api_gateway.py", "fastapi_backend.py"])
def test_fastapi_entrypoints_reject_deleted_jwt_subjects(source_file, caplog):
    """Run the actual source FastAPI dependencies without a trading service."""
    import asyncio

    class SyntheticHTTPException(Exception):
        def __init__(self, status_code, detail, headers=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
            self.headers = headers

    async def no_rate_limit(_request, _subject):
        return None

    key = secrets.token_urlsafe(40)
    account = types.SimpleNamespace(
        get_user=lambda uid: {"user_id": uid, "enabled": True}
        if uid == USER_A else None
    )
    env = dict(
        jwt=jwt, JWT_SECRET_KEY_STR=key, JWT_ALGORITHM="HS256",
        HTTPException=SyntheticHTTPException,
        status=types.SimpleNamespace(HTTP_401_UNAUTHORIZED=401,
                                     HTTP_503_SERVICE_UNAVAILABLE=503),
        Optional=Optional, Dict=Dict, Request=object,
        HTTPAuthorizationCredentials=object, security=object(),
        Depends=lambda _: None, user_db=account,
        check_rate_limit=no_rate_limit,
        logger=logging.getLogger("synthetic.fastapi." + source_file),
    )
    source = ast.parse((ROOT / source_file).read_text(encoding="utf-8"))
    functions = [node for node in source.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in {"decode_access_token", "get_current_user"}]
    assert len(functions) == 2
    exec(compile(ast.Module(body=functions, type_ignores=[]), source_file, "exec"), env)

    def access(subject):
        token = jwt.encode(
            {"user_id": subject, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            key, algorithm="HS256",
        )
        credentials = types.SimpleNamespace(credentials=token)
        caller = env["get_current_user"]
        if source_file == "fastapi_backend.py":
            return asyncio.run(caller(request=object(), credentials=credentials))
        return asyncio.run(caller(credentials=credentials))

    assert access(USER_A) == USER_A
    for subject in (USER_B, " ", 17, None):
        with pytest.raises(SyntheticHTTPException) as denied:
            access(subject)
        assert denied.value.status_code == 401

    account.get_user = lambda uid: {"user_id": uid, "enabled": False}
    with pytest.raises(SyntheticHTTPException) as disabled:
        access(USER_A)
    assert disabled.value.status_code == 401
    assert disabled.value.detail == "Account is unavailable"

    def broken(_uid):
        raise sqlite3.OperationalError("private-user-database-location")
    account.get_user = broken
    with caplog.at_level(logging.ERROR, logger=env["logger"].name):
        with pytest.raises(SyntheticHTTPException) as unavailable:
            access(USER_A)
    assert unavailable.value.status_code == 503
    assert unavailable.value.detail == "Authentication temporarily unavailable"
    rendered = " ".join(r.getMessage() for r in caplog.records
                        if r.name == env["logger"].name)
    assert "AUTH_SUBJECT_LOOKUP_FAILED error_type=OperationalError" in rendered
    assert "private-user-database-location" not in rendered
    assert USER_A not in rendered
