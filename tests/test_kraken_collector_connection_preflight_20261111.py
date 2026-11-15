"""Regression checks for fail-closed Kraken collector connection preflight.

No exchange, credentials, Redis, Render or live collector are accessed.
"""
from unittest.mock import patch

import pytest

from bot.kraken_collector_connection import (
    KrakenCollectorConnectionDenied,
    connect_reviewed_kraken_collector,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED


def _arguments():
    return {
        "broker": object(),
        "approved_api_key_sha256": "a" * 64,
        "approved_iban_sha256": "b" * 64,
        "reviewed_provider_ids": {
            name: "reviewed:" + name for name in REQUIRED
        },
        "independent_open_intents": lambda: {},
        "independent_positions": lambda: {},
        "independent_remaining": {},
        "reviewed_source_owners": {},
        "monitoring_category": "monitoring",
        "independently_reviewed": True,
        "backup_restore_certified": True,
        "broker_ledger_exits_certified": True,
    }


@pytest.mark.parametrize("invalid", [
    {},
    {"account_identity": "owner"},
    {name: "same-provider" for name in REQUIRED},
    {name: " " for name in REQUIRED},
])
def test_invalid_reviewed_provider_registry_never_constructs_or_installs(invalid):
    args = _arguments()
    args["reviewed_provider_ids"] = invalid
    with patch("bot.kraken_collector_connection.compose_authenticated_kraken_collector_sources") as compose, patch(
        "bot.kraken_collector_connection.install_reviewed_kraken_collector"
    ) as install:
        with pytest.raises(KrakenCollectorConnectionDenied, match="unique_reviewed_provider_ids_required"):
            connect_reviewed_kraken_collector(**args)
        compose.assert_not_called()
        install.assert_not_called()


def test_missing_independent_source_binding_never_constructs_or_installs():
    args = _arguments()
    args["independent_open_intents"] = None
    with patch("bot.kraken_collector_connection.compose_authenticated_kraken_collector_sources") as compose, patch(
        "bot.kraken_collector_connection.install_reviewed_kraken_collector"
    ) as install:
        with pytest.raises(KrakenCollectorConnectionDenied, match="independent_source_bindings_required"):
            connect_reviewed_kraken_collector(**args)
        compose.assert_not_called()
        install.assert_not_called()


def test_unapproved_connection_never_constructs_or_installs():
    args = _arguments()
    args["independently_reviewed"] = False
    with patch("bot.kraken_collector_connection.compose_authenticated_kraken_collector_sources") as compose, patch(
        "bot.kraken_collector_connection.install_reviewed_kraken_collector"
    ) as install:
        with pytest.raises(KrakenCollectorConnectionDenied, match="independent_production_certification_required"):
            connect_reviewed_kraken_collector(**args)
        compose.assert_not_called()
        install.assert_not_called()
