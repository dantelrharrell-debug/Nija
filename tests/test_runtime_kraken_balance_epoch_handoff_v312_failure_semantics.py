from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot import runtime_kraken_balance_epoch_handoff_v312_patch as v312


def test_failed_timeout_handoff_preserves_original_timeout(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")
    with v312._LOCK:
        v312._OBSERVATIONS.clear()

    monkeypatch.setattr(v312, "_credential_key", lambda _broker: ("credential:test", True))

    def original(_broker):
        assert v312._record_observation(
            broker,
            {"error": [], "result": {"XXBT": "0.001"}},
        )
        raise TimeoutError("original authoritative Balance timeout")

    def broken_builder(_broker, _result):
        raise ValueError("row adoption failed")

    fake_v286 = SimpleNamespace(
        _authoritative_positions=original,
        _build_authoritative_rows=broken_builder,
        _record_snapshot_success=lambda _broker, _rows: True,
    )
    monkeypatch.setattr(v312, "_v286", lambda: fake_v286)

    assert v312._patch_v286_authoritative_positions() is True
    with pytest.raises(TimeoutError, match="original authoritative Balance timeout"):
        fake_v286._authoritative_positions(broker)
