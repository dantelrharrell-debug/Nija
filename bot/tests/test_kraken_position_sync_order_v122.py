from __future__ import annotations

import os
from types import SimpleNamespace

from bot import kraken_position_sync_order_v122_patch as v122


class BrokerType:
    def __init__(self, value: str):
        self.value = value


class Broker:
    def __init__(self):
        self.connected = True
        self._startup_position_sync_adopted = False


def test_timeout_layer_flag_is_required(monkeypatch):
    monkeypatch.delenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", raising=False)
    assert v122._timeout_layer_ready() is False
    monkeypatch.setenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", "1")
    assert v122._timeout_layer_ready() is True


def test_v108_guard_blocks_only_kraken_when_timeout_layer_missing(monkeypatch):
    import bot.platform_position_sync_v108_patch as v108

    kraken = Broker()
    coinbase = Broker()
    manager = SimpleNamespace(
        platform_brokers={
            BrokerType("kraken"): kraken,
            BrokerType("coinbase"): coinbase,
        }
    )

    original = v108._connected_unsynced_platform_brokers
    try:
        assert v122._patch_v108() is True
        monkeypatch.delenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", raising=False)
        found = v108._connected_unsynced_platform_brokers(manager)
        assert ("kraken", kraken) not in found
        assert ("coinbase", coinbase) in found

        monkeypatch.setenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", "1")
        found = v108._connected_unsynced_platform_brokers(manager)
        assert ("kraken", kraken) in found
        assert ("coinbase", coinbase) in found
    finally:
        v108._connected_unsynced_platform_brokers = original


def test_v98_installs_v121_and_v122_before_v108():
    from pathlib import Path

    source = Path("bot/position_sync_timeout_v98_patch.py").read_text(encoding="utf-8")
    p121 = source.index('(\"kraken_read_timeout_v121_patch\", \"V121\")')
    p122 = source.index('(\"kraken_position_sync_order_v122_patch\", \"V122\")')
    p108 = source.index('(\"platform_position_sync_v108_patch\", \"V108\")')
    assert p121 < p122 < p108


def test_install_refuses_without_v121(monkeypatch):
    monkeypatch.delenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", raising=False)
    monkeypatch.delenv("NIJA_KRAKEN_POSITION_SYNC_ORDER_V122_INSTALLED", raising=False)
    assert v122.install() is False
    assert os.environ.get("NIJA_KRAKEN_POSITION_SYNC_ORDER_V122_INSTALLED") != "1"
