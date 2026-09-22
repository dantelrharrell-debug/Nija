from __future__ import annotations

import inspect

from bot.broker_manager import KrakenBroker
from bot.execution_dispatch_contract import is_internal_dispatch_failure


def test_kraken_local_volume_validation_preserves_pre_dispatch_provenance():
    source = inspect.getsource(KrakenBroker.place_market_order)

    marker = '"error": "INTERNAL_DISPATCH_FAILURE: pre-dispatch:VOLUME_TOO_SMALL"'
    assert marker in source
    assert '"broker_dispatch": False' in source
    assert '"v2_pre_submit_proven": True' in source

    validation_idx = source.index("KRAKEN ORDER VALIDATION FAILED")
    add_order_idx = source.index("_kraken_private_call('AddOrder'", validation_idx)
    marker_idx = source.index(marker, validation_idx)

    # Provenance is emitted in the local validator branch before any AddOrder.
    assert validation_idx < marker_idx < add_order_idx
    assert is_internal_dispatch_failure(
        "INTERNAL_DISPATCH_FAILURE: pre-dispatch:VOLUME_TOO_SMALL"
    )


def test_bare_volume_too_small_remains_unknown_or_exchange_originated():
    # Do not weaken the global kill switch: a bare venue error is still counted.
    assert not is_internal_dispatch_failure("VOLUME_TOO_SMALL")
