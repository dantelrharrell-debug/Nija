from types import SimpleNamespace

import bot.runtime_platform_stale_snapshot_recovery_v355_patch as v355


def test_v355_delegates_v108_discovery_to_v285_strong_candidates(monkeypatch):
    manager = object()
    stale_broker = object()
    fake_v108 = SimpleNamespace(
        _connected_unsynced_platform_brokers=lambda _manager: []
    )
    fake_v285 = SimpleNamespace(
        _platform_candidates=lambda received: [("kraken", stale_broker)] if received is manager else []
    )
    monkeypatch.setattr(v355, "_v108", lambda: fake_v108)
    monkeypatch.setattr(v355, "_v285", lambda: fake_v285)

    assert v355._patch_discovery() is True
    assert fake_v108._connected_unsynced_platform_brokers(manager) == [("kraken", stale_broker)]


def test_v355_preserves_previous_fail_closed_discovery_if_v285_missing(monkeypatch):
    manager = object()
    original_broker = object()
    fake_v108 = SimpleNamespace(
        _connected_unsynced_platform_brokers=lambda received: [("coinbase", original_broker)] if received is manager else []
    )
    fake_v285 = SimpleNamespace(_platform_candidates=None)
    monkeypatch.setattr(v355, "_v108", lambda: fake_v108)
    monkeypatch.setattr(v355, "_v285", lambda: fake_v285)

    assert v355._patch_discovery() is True
    assert fake_v108._connected_unsynced_platform_brokers(manager) == [("coinbase", original_broker)]


def test_v355_does_not_modify_snapshot_ttl_or_readiness(monkeypatch):
    manager = object()
    current_broker = object()
    fake_v108 = SimpleNamespace(
        _connected_unsynced_platform_brokers=lambda _manager: [("legacy", current_broker)]
    )
    fake_v285 = SimpleNamespace(_platform_candidates=lambda _manager: [])
    monkeypatch.setattr(v355, "_v108", lambda: fake_v108)
    monkeypatch.setattr(v355, "_v285", lambda: fake_v285)

    assert v355._patch_discovery() is True
    assert fake_v108._connected_unsynced_platform_brokers(manager) == []
