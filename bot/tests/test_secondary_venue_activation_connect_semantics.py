from __future__ import annotations

from types import SimpleNamespace

import secondary_venue_activation_patch as patch


class _Broker:
    def __init__(self, result):
        self.connected = False
        self.result = result

    def connect(self):
        self.connected = True
        return self.result


def test_connect_accepts_none_when_adapter_sets_connected_true():
    broker = _Broker(None)
    venue = patch.VENUES[0]
    assert patch._connect(venue, broker, "fingerprint") is True


def test_connect_accepts_false_when_adapter_sets_connected_true():
    broker = _Broker(False)
    venue = patch.VENUES[1]
    assert patch._connect(venue, broker, "fingerprint") is True


def test_connect_rejects_truthy_result_without_connected_state():
    broker = SimpleNamespace(connected=False, connect=lambda: True)
    venue = patch.VENUES[0]
    assert patch._connect(venue, broker, "fingerprint") is False
