"""Offline regression coverage for Kraken collector identity-pin preflight."""
from unittest.mock import patch

import pytest

from bot.kraken_collector_connection import (
    KrakenCollectorConnectionDenied,
    connect_reviewed_kraken_collector,
)


@pytest.mark.parametrize("bad_pin", [None, "", "A" * 64, "g" * 64, "0" * 63])
@pytest.mark.parametrize("pin_field", ["approved_api_key_sha256", "approved_iban_sha256"])
def test_malformed_pin_denied_before_any_source_factory(pin_field, bad_pin):
    kwargs = {
        "broker": object(),
        "approved_api_key_sha256": "a" * 64,
        "approved_iban_sha256": "b" * 64,
        "reviewed_provider_ids": {},
        "independent_open_intents": lambda: {},
        "independent_positions": lambda: {},
        "independent_remaining": {},
        "reviewed_source_owners": {},
        "monitoring_category": None,
        "independently_reviewed": True,
        "backup_restore_certified": True,
        "broker_ledger_exits_certified": True,
    }
    kwargs[pin_field] = bad_pin
    with patch("bot.kraken_collector_connection.compose_authenticated_kraken_collector_sources") as compose, patch(
        "bot.kraken_collector_connection.install_reviewed_kraken_collector"
    ) as install:
        with pytest.raises(KrakenCollectorConnectionDenied, match="approved_identity_pins_required"):
            connect_reviewed_kraken_collector(**kwargs)
        compose.assert_not_called()
        install.assert_not_called()
