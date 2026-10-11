"""Real signed-login regressions for sole-owner authority and delegation."""

import os
import asyncio
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
from flask import Flask, jsonify

from admin_access import (
    AccessDenied, authenticate_bearer, is_administrator, permission_summary, set_administrator,
)
from admin_access_flask import install_admin_access


class AdministratorAccessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.user_db = Path(self.directory.name) / "users.db"
        self.admin_db = Path(self.directory.name) / "admin.db"
        with sqlite3.connect(self.user_db) as connection:
            connection.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, enabled INTEGER)")
            connection.executemany("INSERT INTO users VALUES (?, ?)", [
                ("verified_dante", 1), ("subscriber", 1), ("another", 1),
                ("dante", 1), ("platform", 1), ("nija_llc", 1), ("disabled", 0),
            ])
        self.secret = "unit-test-signing-material-" * 3
        env = {
            "NIJA_AUTH_USER_DB_PATH": str(self.user_db),
            "NIJA_ADMIN_DB_PATH": str(self.admin_db),
            "NIJA_OWNER_USER_ID": "verified_dante",
            "JWT_SECRET_KEY": self.secret,
        }
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = Flask(__name__)
        install_admin_access(self.app, dashboard="user")
        self.mutation = Mock()

        @self.app.get("/api/health")
        def health():
            return jsonify({"healthy": True})

        @self.app.get("/api/users")
        def users():
            return jsonify({"private": True})

        @self.app.get("/api/user/<user_id>/pnl")
        def pnl(user_id):
            return jsonify({"user_id": user_id})

        @self.app.post("/api/user/<user_id>/risk")
        def risk(user_id):
            self.mutation(user_id)
            return jsonify({"updated": True})

        self.client = self.app.test_client()

    def header(self, user_id, **claims):
        payload = {"user_id": user_id, "iat": int(time.time()), "exp": int(time.time()) + 300, **claims}
        return {"Authorization": "Bearer " + jwt.encode(payload, self.secret, algorithm="HS256")}

    def test_only_verified_dante_is_owner_by_default(self):
        self.assertEqual(permission_summary("verified_dante")["role"], "owner")
        self.assertTrue(permission_summary("verified_dante")["can_manage_administrators"])
        for user_id in ("subscriber", "dante", "platform", "nija_llc"):
            self.assertFalse(is_administrator(user_id))
        self.assertFalse(self.admin_db.exists())

    def test_missing_forged_expired_and_role_spoofed_tokens(self):
        self.assertEqual(self.client.get("/api/users").status_code, 401)
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/users", headers={"Authorization": "Bearer fake"}).status_code, 401)
        self.assertEqual(self.client.get("/api/users", headers=self.header("verified_dante", exp=1)).status_code, 401)
        self.assertEqual(self.client.get("/api/users", headers=self.header("subscriber", role="owner")).status_code, 403)
        token = jwt.encode({"user_id": "verified_dante", "iat": 1, "exp": 9999999999}, "wrong-" * 8, "HS256")
        self.assertEqual(self.client.get("/api/users", headers={"Authorization": "Bearer " + token}).status_code, 401)

    def test_token_without_expiry_is_rejected(self):
        token = jwt.encode({"user_id": "verified_dante", "iat": int(time.time())}, self.secret, "HS256")
        with self.assertRaises(AccessDenied):
            authenticate_bearer("Bearer " + token)

    def test_disabled_and_unknown_users_cannot_authenticate(self):
        for user_id in ("disabled", "unknown"):
            self.assertEqual(self.client.get("/api/users", headers=self.header(user_id)).status_code, 401)

    def test_personal_reads_are_scoped_and_legacy_platform_is_owner_only(self):
        self.assertEqual(self.client.get("/api/user/subscriber/pnl", headers=self.header("subscriber")).status_code, 200)
        self.assertEqual(self.client.get("/api/user/another/pnl", headers=self.header("subscriber")).status_code, 403)
        self.assertEqual(self.client.get("/api/user/platform/pnl", headers=self.header("platform")).status_code, 403)
        self.assertEqual(self.client.get("/api/user/platform/pnl", headers=self.header("verified_dante")).status_code, 200)

    def test_user_cannot_mutate_dashboard_control_even_own_account(self):
        result = self.client.post("/api/user/subscriber/risk", headers=self.header("subscriber"))
        self.assertEqual(result.status_code, 403)
        self.mutation.assert_not_called()

    def test_grant_persists_and_revoke_invalidates_existing_token(self):
        token = self.header("subscriber")
        self.assertEqual(self.client.get("/api/users", headers=token).status_code, 403)
        self.assertEqual(self.client.post("/api/admin/grants/subscriber", headers=self.header("verified_dante")).status_code, 200)
        self.assertTrue(is_administrator("subscriber"))
        self.assertEqual(self.client.get("/api/users", headers=token).status_code, 200)
        self.assertFalse(permission_summary("subscriber")["can_manage_administrators"])
        self.assertEqual(self.client.post("/api/admin/grants/another", headers=token).status_code, 403)
        self.assertEqual(self.client.delete("/api/admin/grants/another", headers=token).status_code, 403)
        self.assertEqual(self.client.delete("/api/admin/grants/subscriber", headers=self.header("verified_dante")).status_code, 200)
        self.assertEqual(self.client.get("/api/users", headers=token).status_code, 403)
        with sqlite3.connect(self.admin_db) as connection:
            actions = connection.execute("SELECT actor_id, action FROM administrator_audit ORDER BY id").fetchall()
        self.assertEqual(actions, [("verified_dante", "grant"), ("verified_dante", "revoke")])
        self.assertEqual(self.admin_db.stat().st_mode & 0o777, 0o600)

    def test_owner_cannot_be_revoked_or_transferred(self):
        for grant in (True, False):
            with self.assertRaises(AccessDenied):
                set_administrator("verified_dante", "verified_dante", grant)
        self.assertTrue(is_administrator("verified_dante"))

    def test_disabled_delegate_and_owner_invalidate_grants(self):
        set_administrator("verified_dante", "subscriber", True)
        with sqlite3.connect(self.user_db) as connection:
            connection.execute("UPDATE users SET enabled=0 WHERE user_id='subscriber'")
        self.assertFalse(is_administrator("subscriber"))
        with sqlite3.connect(self.user_db) as connection:
            connection.execute("UPDATE users SET enabled=1 WHERE user_id='subscriber'")
            connection.execute("UPDATE users SET enabled=0 WHERE user_id='verified_dante'")
        self.assertFalse(is_administrator("subscriber"))

    def test_missing_owner_binding_and_corrupt_permissions_fail_closed(self):
        with patch.dict(os.environ, {"NIJA_OWNER_USER_ID": ""}):
            self.assertEqual(self.client.get("/api/users", headers=self.header("verified_dante")).status_code, 503)
        self.admin_db.write_text("not a sqlite database")
        self.assertEqual(self.client.get("/api/users", headers=self.header("subscriber")).status_code, 503)

    def test_owner_change_does_not_carry_old_delegation_forward(self):
        set_administrator("verified_dante", "subscriber", True)
        with patch.dict(os.environ, {"NIJA_OWNER_USER_ID": "another"}):
            self.assertFalse(is_administrator("subscriber"))

    def test_unknown_grant_rejected_but_disabled_user_can_be_revoked(self):
        self.assertEqual(self.client.post("/api/admin/grants/unknown", headers=self.header("verified_dante")).status_code, 400)
        self.assertEqual(self.client.delete("/api/admin/grants/disabled", headers=self.header("verified_dante")).status_code, 200)

    def test_fastapi_enforces_the_same_policy(self):
        from fastapi import FastAPI
        import httpx
        from admin_access_fastapi import install_admin_access as install_fastapi

        app = FastAPI()
        install_fastapi(app)
        async def verify():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                self.assertEqual((await client.get("/api/admin/me")).status_code, 401)
                response = await client.post("/api/admin/grants/another", headers=self.header("subscriber"))
                self.assertEqual(response.status_code, 403)
                response = await client.post("/api/admin/grants/subscriber", headers=self.header("verified_dante"))
                self.assertEqual(response.status_code, 200)
                response = await client.get("/api/admin/me", headers=self.header("subscriber"))
                self.assertEqual(response.json()["role"], "administrator")
                response = await client.delete("/api/admin/grants/subscriber", headers=self.header("verified_dante"))
                self.assertEqual(response.status_code, 200)
        asyncio.run(verify())

    def test_actual_owner_dashboard_denies_anonymous_and_subscriber_controls(self):
        import owner_dashboard_api as dashboard

        client = dashboard.app.test_client()
        with patch.object(dashboard, "_get_kill_switch") as kill_switch:
            self.assertEqual(client.post("/api/owner/kill-switch/activate", json={"pin": "1234"}).status_code, 401)
            response = client.post("/api/owner/kill-switch/activate", json={"pin": "1234"}, headers=self.header("subscriber"))
            self.assertEqual(response.status_code, 403)
            kill_switch.assert_not_called()
        self.assertEqual(client.get("/users.db").status_code, 404)
        self.assertEqual(client.get("/admin_access.py").status_code, 404)

    def test_owner_pin_fallback_is_fail_closed_and_constant_time(self):
        import owner_dashboard_api as dashboard

        with patch.object(dashboard, "_owner", return_value=None):
            self.assertFalse(dashboard._validate_owner_pin(""))
            self.assertFalse(dashboard._validate_owner_pin("1234"))
            with patch.dict(os.environ, {"OWNER_PIN": "test-pin"}):
                self.assertTrue(dashboard._validate_owner_pin("test-pin"))
                self.assertFalse(dashboard._validate_owner_pin("other"))
                self.assertFalse(dashboard._validate_owner_pin(1234))

    def test_login_configuration_requires_explicit_https_endpoint(self):
        import owner_dashboard_api as dashboard

        client = dashboard.app.test_client()
        self.assertEqual(client.get("/api/owner/login-config").status_code, 503)
        for url in ("http://example.com/login", "https://user:password@example.com/login", "https://example.com/login?secret=x"):
            with patch.dict(os.environ, {"NIJA_OWNER_LOGIN_URL": url}):
                self.assertEqual(client.get("/api/owner/login-config").status_code, 503)
        with patch.dict(os.environ, {"NIJA_OWNER_LOGIN_URL": "https://example.com/api/auth/login"}):
            self.assertEqual(client.get("/api/owner/login-config").get_json()["login_url"], "https://example.com/api/auth/login")

    def test_safety_blueprint_controls_cannot_bypass_administrator_auth(self):
        from safety_status_api import safety_api

        standalone = Flask("standalone_safety")
        standalone.register_blueprint(safety_api)
        client = standalone.test_client()
        with patch("builtins.open") as write_file, patch("safety_status_api.os.remove") as remove_file:
            for method in (client.post, client.delete):
                self.assertEqual(method("/api/safety/emergency-stop", json={}).status_code, 401)
                self.assertEqual(method("/api/safety/emergency-stop", json={}, headers=self.header("subscriber")).status_code, 403)
            write_file.assert_not_called()
            remove_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
