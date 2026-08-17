from __future__ import annotations

import importlib
import os
import sys
from types import ModuleType, SimpleNamespace


def _fresh_module():
    sys.modules.pop("bot.canonical_publication_direct_v127_patch", None)
    return importlib.import_module("bot.canonical_publication_direct_v127_patch")


def test_loaded_connected_brokers_uses_only_loaded_connected_objects():
    mod = _fresh_module()

    disconnected = SimpleNamespace(connected=False, exit_only_mode=False, broker_type="kraken")
    connected = SimpleNamespace(connected=True, exit_only_mode=False, broker_type="coinbase")
    manager = SimpleNamespace(platform_brokers={"kraken": disconnected, "coinbase": connected})
    fake = ModuleType("bot.multi_account_broker_manager")
    fake.multi_account_broker_manager = manager
    old = sys.modules.get("bot.multi_account_broker_manager")
    sys.modules["bot.multi_account_broker_manager"] = fake
    try:
        result = mod._loaded_connected_brokers(disconnected)
        assert "coinbase" in result
        assert result["coinbase"]["broker"] is connected
        assert all(meta["broker"] is not disconnected for meta in result.values())
    finally:
        if old is None:
            sys.modules.pop("bot.multi_account_broker_manager", None)
        else:
            sys.modules["bot.multi_account_broker_manager"] = old


def test_connected_entry_broker_rejects_exit_only():
    mod = _fresh_module()
    assert mod._connected_entry_broker(SimpleNamespace(connected=True, exit_only_mode=False))
    assert not mod._connected_entry_broker(SimpleNamespace(connected=True, exit_only_mode=True))
    assert not mod._connected_entry_broker(SimpleNamespace(connected=False, exit_only_mode=False))


def test_release_id_and_flag_are_v127():
    mod = _fresh_module()
    assert mod.RELEASE_ID == "20260816-runtime-convergence-v127"
    assert mod.MARKER == "20260816-canonical-publication-direct-v127"
    assert mod._FLAG == "NIJA_CANONICAL_PUBLICATION_DIRECT_V127_INSTALLED"


def test_installer_is_fail_closed_when_helper_patch_fails(monkeypatch):
    mod = _fresh_module()
    monkeypatch.setattr(mod, "_patch_bot_main_helper", lambda: False)
    monkeypatch.setattr(mod, "_patch_release_manifest", lambda: True)
    mod._INSTALLED = False
    os.environ.pop(mod._FLAG, None)
    assert mod.install() is False
    assert os.environ.get(mod._FLAG) != "1"
