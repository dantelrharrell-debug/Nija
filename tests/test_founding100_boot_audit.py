"""Synthetic tests: no external sources, secret logging or state mutation."""
import unittest

from founding100_boot_audit import _FLAG_NAMES, run_opt_in_audit, launch_opt_in_audit
from unittest.mock import patch


class BootAuditTests(unittest.TestCase):
    def settings(self):
        return {
            "NIJA_FOUNDING100_AUDIT_ON_STARTUP": "true",
            "NIJA_FOUNDING100_AUDIT_USER_ID": "private-member-123",
            "NIJA_FOUNDING100_AUDIT_APPLICATION_ID": "private-app-123",
            "BILLING_DATABASE_URL": "secret-database-url",
            "NIJA_ONBOARDING_DB_PATH": "/private/outbox",
            "STRIPE_SECRET_KEY": "secret-stripe-key",
        }

    def complete_report(self):
        report = {key: True for key in _FLAG_NAMES}
        report.update(authoritative_member_verified=True, blocking_sources=[])
        return report

    def test_launch_is_background_and_opt_in_only(self):
        with patch("threading.Thread") as factory:
            self.assertFalse(launch_opt_in_audit(environ={}))
            factory.assert_not_called()
            self.assertTrue(launch_opt_in_audit(environ=self.settings()))
            factory.assert_called_once()
            self.assertTrue(factory.call_args.kwargs["daemon"])
            factory.return_value.start.assert_called_once()

    def test_disabled_does_not_read_sources(self):
        events = []
        result = run_opt_in_audit(
            environ={}, auditor=lambda *a, **k: self.fail("should not call"), emit=events.append)
        self.assertIsNone(result)
        self.assertEqual(events, [])

    def test_missing_target_fails_without_access(self):
        env = self.settings()
        env["NIJA_FOUNDING100_AUDIT_USER_ID"] = ""
        events = []
        self.assertFalse(run_opt_in_audit(
            environ=env, auditor=lambda *a, **k: self.fail("should not call"),
            emit=events.append))
        self.assertIn("reason=target_invalid", events[0])

    def test_verified_membership_never_grants_onboarding(self):
        env = self.settings()
        events = []
        received = []
        def audit(user, app, **kwargs):
            received.append((user, app, kwargs))
            return self.complete_report()
        self.assertTrue(run_opt_in_audit(environ=env, auditor=audit, emit=events.append))
        self.assertEqual(received[0][0], env["NIJA_FOUNDING100_AUDIT_USER_ID"])
        self.assertEqual(received[0][1], env["NIJA_FOUNDING100_AUDIT_APPLICATION_ID"])
        self.assertIn("result=membership_verified", events[0])
        self.assertIn("full_onboarding_certified=false", events[0])
        self.assertIn("trading_authorized=false", events[0])
        for confidential in env.values():
            if confidential and confidential != "true":
                self.assertNotIn(confidential, events[0])

    def test_missing_outbox_and_other_gates_fail_closed(self):
        report = self.complete_report()
        report["application_binding_verified"] = False
        report["authoritative_member_verified"] = False
        report["blocking_sources"] = [
            "onboarding_identity_record_missing_or_unavailable",
            "secret-customer-email-should-not-log",
        ]
        events = []
        self.assertFalse(run_opt_in_audit(
            environ=self.settings(), auditor=lambda *a, **k: report,
            emit=events.append))
        self.assertIn("onboarding_identity_record_missing_or_unavailable", events[0])
        self.assertNotIn("secret-customer-email-should-not-log", events[0])

    def test_bad_source_errors_never_leak(self):
        def audit(*a, **k):
            raise RuntimeError("database-secret customer-email")
        events = []
        self.assertFalse(run_opt_in_audit(
            environ=self.settings(), auditor=audit, emit=events.append))
        self.assertEqual(events[0],
            "NIJA_FOUNDING100_AUDIT result=blocked reason=source_error full_onboarding_certified=false")


if __name__ == "__main__":
    unittest.main()
