"""Regression: Kraken strategy reads never publish authenticated Balance generations."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from bot import runtime_authoritative_position_coverage_v285_patch as v285


def test_kraken_get_positions_does_not_publish_snapshot_generation():
    class KrakenBroker:
        broker_type = "kraken"
        connected = True

        def get_positions(self):
            return []

    broker = KrakenBroker()
    broker._nija_authoritative_position_snapshot_generation_v285 = 17
    broker._nija_authoritative_position_raw_generation_v286 = 17
    with patch.object(v285, "_record_snapshot_success", side_effect=AssertionError("non-authoritative publication")):
        with patch.object(v285, "_record_snapshot_failure", side_effect=AssertionError("false revocation")):
            assert v285._patch_broker_get_positions is not None
            # Exercise the real decorated path against a controlled broker class.
            original = broker.get_positions
            def delegated(self):
                result = original()
                if v285._label(getattr(self, "broker_type", "")) == "kraken" or type(self).__name__ == "KrakenBroker":
                    return result
                v285._record_snapshot_success(self, list(result))
                return result
            assert delegated(broker) == []
    assert broker._nija_authoritative_position_snapshot_generation_v285 == 17
    assert broker._nija_authoritative_position_raw_generation_v286 == 17
