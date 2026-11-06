"""Offline contract tests: reviewed Kraken connection never activates orders."""
import unittest
from unittest.mock import patch

from bot.kraken_collector_connection import (
    KrakenCollectorConnectionDenied, connect_reviewed_kraken_collector,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.kwargs = dict(
            broker=object(),
            approved_api_key_sha256="a" * 64,
            approved_iban_sha256="b" * 64,
            reviewed_provider_ids={field: "id-" + field for field in REQUIRED},
            independent_open_intents=lambda: {},
            independent_positions=lambda: {},
            independent_remaining={},
            reviewed_source_owners={},
            monitoring_category=object(),
        )

    def test_no_review_never_composes_or_installs(self):
        with patch("bot.kraken_collector_connection.compose_authenticated_kraken_collector_sources") as compose, patch(
            "bot.kraken_collector_connection.install_reviewed_kraken_collector"
        ) as install:
            with self.assertRaisesRegex(KrakenCollectorConnectionDenied, "certification_required"):
                connect_reviewed_kraken_collector(**self.kwargs)
            compose.assert_not_called()
            install.assert_not_called()

    def test_each_missing_certification_denies(self):
        for missing in ("independently_reviewed", "backup_restore_certified", "broker_ledger_exits_certified"):
            flags = dict(independently_reviewed=True, backup_restore_certified=True, broker_ledger_exits_certified=True)
            flags[missing] = False
            with self.subTest(missing=missing), patch(
                "bot.kraken_collector_connection.compose_authenticated_kraken_collector_sources"
            ) as compose:
                with self.assertRaises(KrakenCollectorConnectionDenied):
                    connect_reviewed_kraken_collector(**self.kwargs, **flags)
                compose.assert_not_called()

    def test_reviewed_connection_uses_existing_installer(self):
        providers = {field: (lambda field=field: {}) for field in REQUIRED}
        with patch("bot.kraken_collector_connection.compose_authenticated_kraken_collector_sources", return_value=providers) as compose, patch(
            "bot.kraken_collector_connection.install_reviewed_kraken_collector"
        ) as install:
            connect_reviewed_kraken_collector(
                **self.kwargs, independently_reviewed=True,
                backup_restore_certified=True, broker_ledger_exits_certified=True,
            )
            compose.assert_called_once()
            install.assert_called_once_with(
                providers=providers, reviewed_provider_ids=self.kwargs["reviewed_provider_ids"],
                independently_reviewed=True, backup_restore_certified=True,
                broker_ledger_exits_certified=True,
            )

    def test_incomplete_registry_never_installs(self):
        with patch("bot.kraken_collector_connection.compose_authenticated_kraken_collector_sources", return_value={}), patch(
            "bot.kraken_collector_connection.install_reviewed_kraken_collector"
        ) as install:
            with self.assertRaisesRegex(KrakenCollectorConnectionDenied, "complete_provider_registry_required"):
                connect_reviewed_kraken_collector(
                    **self.kwargs, independently_reviewed=True,
                    backup_restore_certified=True, broker_ledger_exits_certified=True,
                )
            install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
