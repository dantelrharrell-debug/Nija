from __future__ import annotations

from types import SimpleNamespace

from bot import kraken_position_sync_prereq_v122_patch as v122


def _fake_v108():
    return SimpleNamespace(
        _connected_unsynced_platform_brokers=lambda _manager: [
            ("coinbase", object()),
            ("kraken", object()),
            ("okx", object()),
        ]
    )


def _set_flags(monkeypatch, *, v121: bool, v311: bool, v312: bool):
    values = {
        "NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED": "1" if v121 else "0",
        "NIJA_KRAKEN_EARLY_READ_CONVERGENCE_V311_READY": "1" if v311 else "0",
        "NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1" if v312 else "0",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_kraken_dispatch_requires_v121_v311_and_v312(monkeypatch):
    manager = object()

    for flags in (
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ):
        fake = _fake_v108()
        _set_flags(monkeypatch, v121=flags[0], v311=flags[1], v312=flags[2])
        assert v122._patch_v108(fake) is True
        names = [name for name, _broker in fake._connected_unsynced_platform_brokers(manager)]
        assert names == ["coinbase", "okx"]


def test_kraken_dispatch_allowed_only_when_complete_early_stack_ready(monkeypatch):
    fake = _fake_v108()
    _set_flags(monkeypatch, v121=True, v311=True, v312=True)

    assert v122._patch_v108(fake) is True
    names = [name for name, _broker in fake._connected_unsynced_platform_brokers(object())]

    assert names == ["coinbase", "kraken", "okx"]
