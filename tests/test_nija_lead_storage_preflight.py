"""Regression tests for non-destructive lead storage diagnostics."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.nija_lead_storage_preflight import inspect


def make_db(path, *, forwarding=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        if forwarding:
            db.execute("CREATE TABLE website_lead_forwarding (event_key TEXT PRIMARY KEY, state TEXT)")
            db.execute("INSERT INTO website_lead_forwarding VALUES (?, ?)", ("opaque", "sent"))
        else:
            db.execute("CREATE TABLE website_leads (event_key TEXT PRIMARY KEY, form_name TEXT, email TEXT, received_at TEXT)")
            db.execute("INSERT INTO website_leads VALUES (?, ?, ?, ?)", ("opaque", "website lead", "private@example.com", "2026-11-02"))


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.disk = self.root / "data"
        self.disk.mkdir()
        self.default = self.root / "app" / "data" / "nija_outreach.sqlite3"
        self.lead = self.disk / "nija_outreach.sqlite3"
        self.forward = self.disk / "nija_lead_forwarding.sqlite3"
        self.env = {
            "NIJA_LEAD_DB_PATH": str(self.lead),
            "NIJA_LEAD_FORWARD_DB_PATH": str(self.forward),
            "NIJA_LEAD_WEBHOOK_TOKEN": "DO_NOT_LEAK_TOKEN",
            "NIJA_LEAD_FORWARD_URL": "https://hooks.zapier.com/hooks/catch/secret_value",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, env=None, mounted=True):
        return inspect(environ=self.env if env is None else env,
                       disk=self.disk, app_default=self.default,
                       mount_check=lambda _: mounted)

    def test_verified_storage_is_still_not_full_certification(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        before = self.lead.read_bytes()
        result = self.run_check()
        self.assertEqual(result["issues"], [])
        self.assertTrue(result["lead_db_on_mounted_disk"])
        self.assertEqual(result["lead_database"]["row_count"], 1)
        self.assertEqual(result["forwarding_history"]["row_count"], 1)
        self.assertFalse(result["production_certified"])
        self.assertEqual(before, self.lead.read_bytes())
        self.assertNotIn("DO_NOT_LEAK_TOKEN", json.dumps(result))
        self.assertNotIn("secret_value", json.dumps(result))
        self.assertNotIn("private@example.com", json.dumps(result))

    def test_ephemeral_default_is_not_verified_even_when_readable(self):
        make_db(self.default)
        make_db(self.forward, forwarding=True)
        env = {k:v for k,v in self.env.items() if k != "NIJA_LEAD_DB_PATH"}
        r = self.run_check(env)
        self.assertEqual(r["lead_db_config_source"], "default")
        self.assertIn("active_lead_database_outside_verified_disk", r["issues"])
        self.assertEqual(r["lead_database"]["row_count"], 1)

    def test_missing_database_does_not_create_one(self):
        r = self.run_check()
        self.assertIn("lead_database_not_verified", r["issues"])
        self.assertFalse(self.lead.exists())
        self.assertFalse(self.forward.exists())

    def test_missing_mount_fails_closed(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        r = self.run_check(mounted=False)
        self.assertIn("render_persistent_disk_not_verified", r["issues"])
        self.assertFalse(r["lead_db_on_mounted_disk"])

    def test_unverified_second_copy_is_reported_not_merged(self):
        make_db(self.lead)
        make_db(self.default)
        make_db(self.forward, forwarding=True)
        before = self.default.read_bytes()
        r = self.run_check()
        self.assertIn("multiple_potential_lead_databases_require_reconciliation", r["issues"])
        self.assertEqual(before, self.default.read_bytes())

    def test_bad_destination_and_missing_auth_fail(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        env = {"NIJA_LEAD_DB_PATH": str(self.lead),
               "NIJA_LEAD_FORWARD_DB_PATH": str(self.forward),
               "NIJA_LEAD_FORWARD_URL": "http://unsafe.example/secret"}
        r = self.run_check(env)
        self.assertIn("lead_intake_auth_not_configured", r["issues"])
        self.assertIn("forwarding_https_endpoint_not_configured", r["issues"])
        self.assertNotIn("unsafe.example", json.dumps(r))

    def test_symlink_to_disk_is_valid_if_mount_verified(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        self.default.parent.mkdir(parents=True, exist_ok=True)
        self.default.symlink_to(self.lead)
        env = dict(self.env, NIJA_LEAD_DB_PATH=str(self.default))
        r = self.run_check(env)
        self.assertTrue(r["lead_db_on_mounted_disk"])
        self.assertNotIn("multiple_potential_lead_databases_require_reconciliation", r["issues"])


    def test_wal_database_fails_closed_without_sidecar_changes(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        with sqlite3.connect(self.lead) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.execute("INSERT INTO website_leads VALUES ('second', 'test', 'hidden@example.com', 'now')")
            before = {p.name: p.read_bytes() for p in self.disk.iterdir() if p.is_file()}
            result = self.run_check()
            after = {p.name: p.read_bytes() for p in self.disk.iterdir() if p.is_file()}
            self.assertEqual(before, after)
            self.assertIn("lead_database_not_verified", result["issues"])
            self.assertEqual(result["lead_database"]["read_error"], "wal_database_requires_offline_snapshot")

    def test_whitespace_primary_override_does_not_fall_back(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        env = dict(self.env, NIJA_LEAD_DB_PATH="   ", NIJA_OUTREACH_DB_PATH=str(self.lead))
        result = self.run_check(env)
        self.assertEqual(result["lead_db_config_source"], "NIJA_LEAD_DB_PATH")
        self.assertIn("lead_database_not_verified", result["issues"])

    def test_whitespace_primary_auth_does_not_fall_back(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        env = dict(self.env, NIJA_LEAD_WEBHOOK_TOKEN="   ", NIJA_OUTREACH_SERVICE_TOKEN="fallback")
        result = self.run_check(env)
        self.assertFalse(result["lead_intake_auth_configured"])
        self.assertIn("lead_intake_auth_not_configured", result["issues"])

    def test_malformed_forward_url_is_sanitized(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        for target in ("https://user:SECRET@[bad", "https://SECRET@invalid.example:badport"):
            env = dict(self.env, NIJA_LEAD_FORWARD_URL=target)
            result = self.run_check(env)
            self.assertFalse(result["forwarding_https_configured"])
            self.assertIn("forwarding_https_endpoint_not_configured", result["issues"])
            self.assertNotIn("SECRET", json.dumps(result))

    def test_tilde_path_is_not_expanded(self):
        make_db(self.lead)
        make_db(self.forward, forwarding=True)
        env = dict(self.env, NIJA_LEAD_DB_PATH="~/not-an-actual-lead-db.sqlite3",
                   NIJA_LEAD_FORWARD_DB_PATH="~/not-an-actual-forward-db.sqlite3")
        result = self.run_check(env)
        self.assertIn("lead_database_not_verified", result["issues"])
        self.assertIn("forward_history_not_verified", result["issues"])

if __name__ == "__main__":
    unittest.main()
