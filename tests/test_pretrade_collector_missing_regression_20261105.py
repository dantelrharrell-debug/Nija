"""Regression test: a missing independent collector never authorizes orders."""
import unittest
from unittest.mock import patch
from bot import pretrade_independent_attestation as evidence


class MissingCollectorTest(unittest.TestCase):
    def test_missing_collector_denies_all_checks(self):
        with patch.object(evidence, '_COLLECTOR', None):
            report = evidence.inspect_authenticated_attestations('platform:kraken')
        self.assertEqual(report['producer_status'], 'collector_missing')
        self.assertFalse(report['authorizes_orders'])
        self.assertFalse(any(report['checks'].values()))


if __name__ == '__main__':
    unittest.main()
