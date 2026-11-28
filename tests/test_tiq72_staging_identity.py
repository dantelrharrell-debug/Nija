"""Real NIJA Argon2 and SQLite verification without any network or live data."""
import secrets
import tempfile
import unittest
from pathlib import Path

from auth.user_database import UserDatabase
from game_sandbox.tiq72_staging_identity import SCOPE, create_issuer


class TestTiq72Issuer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "staging.sqlite3")
        self.jwt_key, self.bridge = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        db = UserDatabase(self.path)
        self.subject = "tiq-stage-buyer-fixture"
        self.email = self.subject + "@example.invalid"
        self.password = secrets.token_urlsafe(30)
        self.assertTrue(db.create_user(self.subject, self.email, self.password))
        self.db = db

    def client(self):
        return create_issuer(scope=SCOPE, accounts=UserDatabase(self.path),
                             jwt_key=self.jwt_key, bridge_key=self.bridge).test_client()

    def login(self, client, email=None, password=None, use_bridge=True):
        return client.post("/api/auth/login", json={"email": email or self.email,
                                                    "password": password or self.password},
                           headers={"X-NIJA-Staging-Bridge": self.bridge} if use_bridge else {})

    def profile(self, client, token):
        return client.get("/api/user/profile", headers={"Authorization": "Bearer " + token,
                                                         "X-NIJA-Staging-Bridge": self.bridge})

    def test_separate_compartment_and_authentication_are_mandatory(self):
        with self.assertRaises(ValueError):
            create_issuer(scope="production", accounts=self.db, jwt_key=self.jwt_key, bridge_key=self.bridge)
        with self.assertRaises(ValueError):
            create_issuer(scope=SCOPE, accounts=self.db, jwt_key=self.bridge, bridge_key=self.bridge)
        c = self.client()
        self.assertEqual(self.login(c, use_bridge=False).status_code, 404)
        self.assertEqual(self.login(c, email="person@example.com").status_code, 401)
        self.assertEqual(self.login(c, password=secrets.token_urlsafe(30)).status_code, 401)
        self.assertEqual(c.post("/api/auth/register", headers={"X-NIJA-Staging-Bridge": self.bridge}).status_code, 404)
        self.assertEqual(c.get("/api/trading/status", headers={"X-NIJA-Staging-Bridge": self.bridge}).status_code, 404)

    def test_existing_account_signs_in_after_reopening_and_disabled_accounts_lose_access(self):
        token = self.login(self.client()).json["access_token"]
        p = self.profile(self.client(), token)
        self.assertEqual(p.status_code, 200)
        self.assertEqual(p.json, {"user_id": self.subject, "enabled": True})
        self.assertEqual(p.headers["Cache-Control"], "private, no-store")
        self.assertEqual(self.profile(self.client(), token + "extra").status_code, 401)
        self.assertTrue(self.db.update_user(self.subject, {"enabled": False}))
        self.assertEqual(self.profile(self.client(), token).status_code, 401)


if __name__ == "__main__":
    unittest.main()
