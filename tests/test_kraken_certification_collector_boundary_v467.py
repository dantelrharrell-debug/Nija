"""Fail-closed tests for the Kraken certification collector boundary."""
import time
import unittest

from bot.kraken_certification_collector_boundary_v467 import (
    build_kraken_certification_collector, PROVENANCE,
)
from bot.pretrade_independent_attestation import FIELDS


def valid(account="kraken:platform"):
    return {
        "account": account, "source": "authenticated_independent",
        "read_only": True, "scope_verified": True,
        "observed_at_epoch": time.time(),
        "provenance": {k: True for k in PROVENANCE},
        "checks": {k: True for k in FIELDS},
    }


class KrakenCertificationBoundaryTests(unittest.TestCase):
    def test_valid_evidence(self):
        collector = build_kraken_certification_collector(lambda account: valid(account))
        self.assertEqual(collector("kraken:platform")["account"], "kraken:platform")

    def test_account_mismatch_fails(self):
        collector = build_kraken_certification_collector(lambda account: valid("other"))
        with self.assertRaises(ValueError):
            collector("kraken:platform")

    def test_missing_provenance_fails(self):
        data = valid()
        data["provenance"]["complete_pagination_verified"] = False
        with self.assertRaises(ValueError):
            build_kraken_certification_collector(lambda _: data)("kraken:platform")

    def test_missing_protection_fails(self):
        data = valid()
        data["checks"]["protective_exit_readback"] = False
        with self.assertRaises(ValueError):
            build_kraken_certification_collector(lambda _: data)("kraken:platform")

    def test_stale_fails(self):
        data = valid()
        data["observed_at_epoch"] -= 61
        with self.assertRaises(ValueError):
            build_kraken_certification_collector(lambda _: data)("kraken:platform")

    def test_read_only_required(self):
        data = valid()
        data["read_only"] = False
        with self.assertRaises(ValueError):
            build_kraken_certification_collector(lambda _: data)("kraken:platform")


if __name__ == "__main__":
    unittest.main()
