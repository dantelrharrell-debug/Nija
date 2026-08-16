from __future__ import annotations

import types

from bot import kraken_position_sync_prereq_v122_patch as v122
from bot import position_sync_timeout_v98_patch as v98


class FakeBroker:
    pass


def _fake_v108_module():
    module = types.ModuleType("bot.platform_position_sync_v108_patch")
    kraken = FakeBroker()
    coinbase = FakeBroker()

    def discovered(_manager):
        return [("kraken", kraken), ("coinbase", coinbase)]

    module._connected_unsynced_platform_brokers = discovered
    return module, kraken, coinbase


def test_v122_blocks_only_kraken_when_v121_not_ready(monkeypatch):
    monkeypatch.delenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", raising=False)
    module, _kraken, coinbase = _fake_v108_module()

    assert v122._patch_v108(module) is True
    assert module._connected_unsynced_platform_brokers(object()) == [("coinbase", coinbase)]


def test_v122_allows_kraken_after_v121_ready(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", "1")
    module, kraken, coinbase = _fake_v108_module()

    assert v122._patch_v108(module) is True
    assert module._connected_unsynced_platform_brokers(object()) == [
        ("kraken", kraken),
        ("coinbase", coinbase),
    ]


def test_v98_installs_v121_and_v122_before_v108(monkeypatch):
    order = []
    monkeypatch.setattr(v98, "_INSTALLED", False)
    monkeypatch.setattr(v98, "_install_module", lambda name: order.append(name) or True)

    assert v98.install() is True

    i121 = order.index("kraken_read_timeout_v121_patch")
    i122 = order.index("kraken_position_sync_prereq_v122_patch")
    i108 = order.index("platform_position_sync_v108_patch")
    assert i121 < i122 < i108


def test_v122_does_not_fabricate_v121_readiness(monkeypatch):
    monkeypatch.delenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", raising=False)
    assert v122._v121_ready() is False

    monkeypatch.setenv("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", "1")
    assert v122._v121_ready() is True
