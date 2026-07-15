from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace

import runtime_module_identity_convergence_patch as identity
import bot.empty_position_sync_success_patch as empty_sync
import bot.secondary_credential_quarantine_patch as quarantine
import bot.runtime_release_manifest_patch as manifest


def test_v13_release_id():
    assert manifest.RELEASE_ID == "20260715-runtime-convergence-v13"


def test_identity_ignores_stale_latch_when_current_graph_is_clean(monkeypatch):
    monkeypatch.setenv("NIJA_DUPLICATE_PATCH_MODULE_DETECTED", "1")
    monkeypatch.setattr(identity, "recover_unregistered_patch_modules_from_threads", lambda: {})
    monkeypatch.setattr(identity, "_current_duplicates", lambda: [])

    ready, details = identity.canonicalize_loaded_patch_modules()

    assert ready is True
    assert details["current_duplicate_modules"] == "none"
    assert os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] == "0"


def test_identity_rejects_current_duplicate(monkeypatch):
    monkeypatch.setattr(identity, "recover_unregistered_patch_modules_from_threads", lambda: {})
    monkeypatch.setattr(identity, "_current_duplicates", lambda: ["nija_patch->bot.patch"])

    ready, details = identity.canonicalize_loaded_patch_modules()

    assert ready is False
    assert details["current_duplicate_modules"] == "nija_patch->bot.patch"
    assert os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] == "1"


def test_successful_empty_snapshot_is_marked_synchronized(monkeypatch):
    module = ModuleType("bot.startup_position_sync")

    def original(broker, broker_name, eps):
        broker._startup_position_sync_adopted = False
        return 0

    module._adopt_broker_positions = original
    assert empty_sync._patch(module) is True
    broker = SimpleNamespace(connected=True, get_positions=lambda: [])

    assert module._adopt_broker_positions(broker, "user:test:kraken", None) == 0
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_symbols == tuple()


def test_empty_snapshot_fetch_error_remains_unsynchronized():
    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = lambda broker, broker_name, eps: 0
    empty_sync._patch(module)

    def fail():
        raise RuntimeError("network")

    broker = SimpleNamespace(connected=True, get_positions=fail)
    module._adopt_broker_positions(broker, "user:test:kraken", None)
    assert not bool(getattr(broker, "_startup_position_sync_adopted", False))


def test_okx_fatal_codes_are_quarantinable():
    assert quarantine._fatal_code({"code": "50111"}) == "50111"
    assert quarantine._fatal_code({"code": "50119"}) == "50119"
    assert quarantine._fatal_code({"code": "0"}) == ""


def test_okx_private_requests_stop_after_fatal_credentials(monkeypatch):
    module = ModuleType("bot.broker_manager")
    calls = []

    class Rest:
        def _request(self, method, path, *args, **kwargs):
            calls.append(path)
            return {"code": "50111", "msg": "Invalid OK-ACCESS-KEY"}

    module._OKXRestClient = Rest
    assert quarantine._patch_rest(module) is True
    rest = Rest()

    first = rest._request("GET", "/api/v5/account/balance", private=True)
    second = rest._request("GET", "/api/v5/account/balance", private=True)

    assert first["code"] == "50111"
    assert second["quarantined"] is True
    assert calls == ["/api/v5/account/balance"]
    assert os.environ["NIJA_OKX_CREDENTIALS_QUARANTINED"] == "1"
    assert os.environ["NIJA_OKX_TRADING_READY"] == "0"
