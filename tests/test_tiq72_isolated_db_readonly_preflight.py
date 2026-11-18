"""Offline synthetic tests. No database connections, credentials or writes."""
import unittest
from scripts import tiq72_isolated_db_readonly_preflight as preflight


class PretendError(Exception):
    def __init__(self, state=None):
        self.pgcode = state


def good_private_url():
    return (
        "postgresql://" + preflight.EXPECTED_USER + ":" +
        "synthetic_only" + "@" + preflight.EXPECTED_HOST + "/" +
        preflight.EXPECTED_DB + "?sslmode=require"
    )


def resolve_ok(*_args, **_kwargs):
    return [(0, 0, 0, "", ())]


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def dial_ok(*_args, **_kwargs):
    return FakeConnection()


class TestIsolatedReadOnlyPreflight(unittest.TestCase):
    def test_private_database_identity_is_exact(self):
        valid = good_private_url()
        self.assertTrue(preflight.verified_private_url(valid))
        for replacement in (
            valid.replace(preflight.EXPECTED_HOST, "other-workspace"),
            valid.replace(preflight.EXPECTED_DB, "production"),
            valid.replace(preflight.EXPECTED_USER, "other-user"),
            valid.replace("sslmode=require", "sslmode=disable"),
            valid.replace("synthetic_only", ""),
            "not-a-url",
        ):
            self.assertFalse(preflight.verified_private_url(replacement))

    def test_error_codes_are_fixed_not_exceptions(self):
        self.assertEqual(
            preflight.classify_connect_failure(PretendError("28P01")),
            "private_db_credentials_rejected",
        )
        self.assertEqual(
            preflight.classify_connect_failure(PretendError("3D000")),
            "private_db_database_unavailable",
        )
        self.assertEqual(
            preflight.classify_connect_failure(
                PretendError(), resolve=resolve_ok, dial=dial_ok),
            "private_db_tls_or_auth_rejected",
        )

    def test_network_failure_codes_are_safe(self):
        def no_dns(*_args, **_kwargs):
            raise OSError("sensitive details must never be included")
        def no_tcp(*_args, **_kwargs):
            raise OSError("sensitive details must never be included")
        self.assertEqual(
            preflight.classify_connect_failure(
                PretendError(), resolve=no_dns, dial=dial_ok),
            "private_db_dns_unavailable",
        )
        self.assertEqual(
            preflight.classify_connect_failure(
                PretendError(), resolve=resolve_ok, dial=no_tcp),
            "private_db_tcp_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
