from __future__ import annotations

from types import ModuleType, SimpleNamespace

import bot.platform_position_sync_v108_patch as v108
import bot.runtime_position_fetch_proof_v182_patch as v182


def test_v108_reasserts_exact_refresh_hook_when_marker_was_only_copied(monkeypatch):
    calls: list[str] = []

    def later_wrapper(self, *args, **kwargs):
        return "refresh-ok"

    # Simulate functools.wraps copying v108's marker onto a later wrapper even
    # though the exact v108 owner is no longer in the active call chain.
    setattr(later_wrapper, v108._PATCH_ATTR, True)

    fake_module = ModuleType("bot.multi_account_broker_manager")

    class MultiAccountBrokerManager:
        refresh_capital_authority = later_wrapper

    fake_module.MultiAccountBrokerManager = MultiAccountBrokerManager

    assert v108._chain_has_exact_refresh_hook(later_wrapper) is False
    monkeypatch.setattr(
        v108,
        "dispatch_platform_position_sync",
        lambda manager, *, trigger: calls.append(trigger) or 1,
    )

    assert v108._patch_mabm(fake_module) is True
    active = MultiAccountBrokerManager.refresh_capital_authority
    assert v108._chain_has_exact_refresh_hook(active) is True

    manager = MultiAccountBrokerManager()
    assert manager.refresh_capital_authority(trigger="v254-test") == "refresh-ok"
    assert calls == ["v254-test"]


def test_v108_does_not_double_wrap_when_exact_hook_is_present(monkeypatch):
    fake_module = ModuleType("bot.multi_account_broker_manager")

    class MultiAccountBrokerManager:
        def refresh_capital_authority(self, *args, **kwargs):
            return "ok"

    fake_module.MultiAccountBrokerManager = MultiAccountBrokerManager
    monkeypatch.setattr(v108, "dispatch_platform_position_sync", lambda *args, **kwargs: 0)

    assert v108._patch_mabm(fake_module) is True
    first = MultiAccountBrokerManager.refresh_capital_authority
    assert v108._chain_has_exact_refresh_hook(first) is True

    assert v108._patch_mabm(fake_module) is True
    assert MultiAccountBrokerManager.refresh_capital_authority is first


def test_v182_reasserts_and_verifies_v108_refresh_dispatch(monkeypatch):
    fake_mabm_module = ModuleType("bot.multi_account_broker_manager")

    class MultiAccountBrokerManager:
        def refresh_capital_authority(self, *args, **kwargs):
            return None

    fake_mabm_module.MultiAccountBrokerManager = MultiAccountBrokerManager
    active_refresh = MultiAccountBrokerManager.refresh_capital_authority

    fake_v108 = SimpleNamespace(
        _patch_loaded=lambda: True,
        _chain_has_exact_refresh_hook=lambda candidate: candidate is active_refresh,
    )
    monkeypatch.setattr(v182, "_v108_module", lambda: fake_v108)

    real_import = v182.importlib.import_module

    def fake_import(name: str):
        if name == "bot.multi_account_broker_manager":
            return fake_mabm_module
        if name == "multi_account_broker_manager":
            raise ImportError(name)
        return real_import(name)

    monkeypatch.setattr(v182.importlib, "import_module", fake_import)

    ready, detail = v182._reassert_v108_dispatch_hook()
    assert ready is True
    assert detail == "exact_v108_refresh_hook_ready"


def test_v182_fails_closed_when_v108_refresh_dispatch_cannot_be_reasserted(monkeypatch):
    fake_v108 = SimpleNamespace(
        _patch_loaded=lambda: False,
        _chain_has_exact_refresh_hook=lambda candidate: False,
    )
    monkeypatch.setattr(v182, "_v108_module", lambda: fake_v108)

    ready, detail = v182._reassert_v108_dispatch_hook()
    assert ready is False
    assert detail == "v108_mabm_not_loaded_or_patch_failed"
