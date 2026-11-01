"""Fail-closed database isolation regression tests; no real credentials or I/O."""
import unittest
from unittest.mock import Mock

from billing_staging_database_binding import verify_staging_database_binding

_STAGE = "srv-dasmtjfpn0mc73948r10"
_URL = "postgresql://unit:fixture@dpg-dbhtsmqjnfac73cbblmg-a/nija_billing_staging_db"


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _Connection:
    def __init__(self, database):
        self.database = database
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        self.statements.append(str(statement))
        return _Result(self.database)


class _Engine:
    def __init__(self, database):
        self.connection = _Connection(database)
        self.dispose = Mock()

    def connect(self):
        return self.connection


class StagingDatabaseBindingTests(unittest.TestCase):
    def test_verified_postgresql_database_is_read_only(self):
        engine = _Engine("nija_billing_staging_db")
        factory = Mock(return_value=engine)
        result = verify_staging_database_binding(_URL, service_id=_STAGE, engine_factory=factory)
        self.assertTrue(result)
        self.assertEqual(engine.connection.statements, ["SELECT current_database()"])
        engine.dispose.assert_called_once_with()

    def test_production_and_local_skip_without_accessing_credentials(self):
        factory = Mock(side_effect=AssertionError("must not connect"))
        for service_id in ("srv-dasn1mbbc2fs738036gg", "", "some-other-staging"):
            self.assertFalse(verify_staging_database_binding("not-a-dsn", service_id=service_id, engine_factory=factory))
        factory.assert_not_called()

    def test_invalid_url_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "url_invalid"):
            verify_staging_database_binding("nija_billing_staging_db", service_id=_STAGE)

    def test_wrong_database_or_wrong_host_rejected_before_connect(self):
        urls = [
            "postgresql://unit:fixture@dpg-dbhtsmqjnfac73cbblmg-a/nija_billing_db",
            "postgresql://unit:fixture@dpg-dasaafgjo6nc73au2010-a/nija_billing_staging_db",
            "sqlite:////tmp/nija_billing_staging_db",
        ]
        factory = Mock(side_effect=AssertionError("must not connect"))
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaisesRegex(RuntimeError, "target_mismatch"):
                    verify_staging_database_binding(url, service_id=_STAGE, engine_factory=factory)
        factory.assert_not_called()

    def test_mismatched_live_database_identity_fails_and_disposes(self):
        engine = _Engine("nija_billing_db")
        with self.assertRaisesRegex(RuntimeError, "identity_mismatch"):
            verify_staging_database_binding(_URL, service_id=_STAGE, engine_factory=Mock(return_value=engine))
        engine.dispose.assert_called_once_with()

    def test_unavailable_probe_fails_with_sanitized_error(self):
        factory = Mock(side_effect=ConnectionError("private fixture details must not escape"))
        with self.assertRaisesRegex(RuntimeError, "identity_probe_failed") as caught:
            verify_staging_database_binding(_URL, service_id=_STAGE, engine_factory=factory)
        self.assertNotIn("private fixture", str(caught.exception))

    def test_render_host_suffix_is_allowed_for_private_dns_forms(self):
        engine = _Engine("nija_billing_staging_db")
        url = "postgresql://unit:fixture@dpg-dbhtsmqjnfac73cbblmg-a.internal/nija_billing_staging_db"
        self.assertTrue(verify_staging_database_binding(url, service_id=_STAGE, engine_factory=Mock(return_value=engine)))


if __name__ == "__main__":
    unittest.main()
