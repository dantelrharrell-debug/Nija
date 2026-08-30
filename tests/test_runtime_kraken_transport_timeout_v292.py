from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_kraken_transport_timeout_v292_patch as v292


class _Session:
    def __init__(self):
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, dict(kwargs)))
        return {"ok": True}


class _Broker:
    API_TIMEOUT_SECONDS = 12
    account_identifier = "USER:test"

    def __init__(self):
        self.api = SimpleNamespace(session=_Session())


def test_transport_timeout_binds_actual_session_request():
    broker = _Broker()
    assert v292._ensure_transport_timeout(broker) is True
    assert broker.api.session.request("POST", "https://example.invalid/private") == {"ok": True}
    assert broker.api.session.calls[-1][1]["timeout"] == 12.0


def test_explicit_transport_timeout_is_preserved():
    broker = _Broker()
    assert v292._ensure_transport_timeout(broker) is True
    broker.api.session.request("POST", "https://example.invalid/private", timeout=3.5)
    assert broker.api.session.calls[-1][1]["timeout"] == 3.5


def test_transport_timeout_patch_is_idempotent():
    broker = _Broker()
    assert v292._ensure_transport_timeout(broker) is True
    first = broker.api.session.request
    assert v292._ensure_transport_timeout(broker) is True
    second = broker.api.session.request
    assert first is second
    second("POST", "https://example.invalid/private")
    assert broker.api.session.calls[-1][1]["timeout"] == 12.0


def test_missing_direct_session_does_not_fabricate_success():
    broker = SimpleNamespace(API_TIMEOUT_SECONDS=12, account_identifier="gateway", api=None)
    assert v292._ensure_transport_timeout(broker) is False


def test_timeout_policy_uses_existing_configured_value():
    broker = _Broker()
    broker.API_TIMEOUT_SECONDS = 7
    assert v292._transport_timeout_s(broker) == 7.0
