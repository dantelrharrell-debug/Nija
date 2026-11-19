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


class FakeCatalogCursor:
    """Synthetic catalog shapes. Executes no SQL outside an in-memory mock."""
    def __init__(self, *, wrong_column=False, missing_constraint=False, invalid_index=False):
        self.wrong_column = wrong_column
        self.missing_constraint = missing_constraint
        self.invalid_index = invalid_index
        self.rows = []
        self.seen = []

    def execute(self, query, parameters):
        self.seen.append(query)
        assert parameters == (list(preflight.TABLES),)
        if "information_schema.columns" in query:
            self.rows = [
                (table, column, "text" if self.wrong_column and column == "report"
                 else data_type, nullable)
                for table, specs in preflight.COLUMNS.items()
                for column, (data_type, nullable) in specs.items()
            ]
        elif "pg_catalog.pg_constraint" in query:
            rows = list(preflight.CONSTRAINTS)
            if self.missing_constraint:
                rows = [row for row in rows if row[1] != "tiq72_v515_session_test_only"]
            self.rows = rows
        elif "pg_catalog.pg_index" in query:
            self.rows = [
                (table, index, not(self.invalid_index and index == "tiq72_v515_res_owner_run"), True)
                for table, index in preflight.INDEXES
            ]
        else:
            raise AssertionError("unexpected_catalog_query")

    def fetchall(self):
        return self.rows


class TestIsolatedSchemaContract(unittest.TestCase):
    def test_reviewed_four_table_catalog_shape_passes(self):
        cursor = FakeCatalogCursor()
        self.assertTrue(preflight.schema_contract_verified(cursor))
        self.assertEqual(len(cursor.seen), 3)

    def test_missing_test_only_session_constraint_denies(self):
        self.assertFalse(preflight.schema_contract_verified(
            FakeCatalogCursor(missing_constraint=True)))

    def test_mismatched_paid_report_jsonb_column_denies(self):
        self.assertFalse(preflight.schema_contract_verified(
            FakeCatalogCursor(wrong_column=True)))

    def test_invalid_required_index_denies(self):
        self.assertFalse(preflight.schema_contract_verified(
            FakeCatalogCursor(invalid_index=True)))


if __name__ == "__main__":
    unittest.main()
