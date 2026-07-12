from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "final_runtime_convergence_patch_test_module",
    ROOT / "final_runtime_convergence_patch.py",
)
assert SPEC and SPEC.loader
patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch)


def test_none_scan_result_is_coerced_to_contract():
    result = patch._coerce_scan_result(None)
    assert result.symbols_scored == 0
    assert result.entries_taken == 0
    assert result.entries_blocked == 1
    assert result.exits_taken == 0
    assert result.next_interval >= 5
    assert result.metadata["duplicate_scan"] is True


def test_tuple_scan_result_is_coerced_to_contract():
    result = patch._coerce_scan_result((2, 1, 1, {"next_interval": 30, "exits_taken": 1}))
    assert result.symbols_scored == 2
    assert result.entries_blocked == 1
    assert result.entries_taken == 1
    assert result.exits_taken == 1
    assert result.next_interval == 30


def test_auth_repair_uses_loaded_module_without_import(monkeypatch):
    calls: list[str] = []
    auth = ModuleType("broker_auth_recovery_patch")
    auth.normalize_coinbase_environment = lambda: calls.append("coinbase") or True
    auth.normalize_okx_environment = lambda: calls.append("okx") or True
    monkeypatch.setitem(sys.modules, "broker_auth_recovery_patch", auth)

    patch._safe_normalize("coinbase")
    broker = SimpleNamespace(base_url="https://us.okx.com")
    monkeypatch.setenv("OKX_BASE_URL", "https://www.okx.com")
    patch._safe_normalize("okx", broker)

    assert calls == ["coinbase", "okx"]
    assert broker.base_url == "https://www.okx.com"


def test_core_loop_wrapper_never_returns_none():
    module = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        def run_scan_phase(self, *args, **kwargs):
            return None

    module.NijaCoreLoop = NijaCoreLoop
    assert patch._patch_core_loop(module) is True
    result = NijaCoreLoop().run_scan_phase(broker=SimpleNamespace(account_id="platform", broker_name="kraken"))
    assert result.symbols_scored == 0
    assert result.entries_blocked == 1


def test_okx_endpoint_updates_live_instance(monkeypatch):
    broker = SimpleNamespace(base_url="https://us.okx.com", endpoint="https://us.okx.com")
    patch._set_okx_endpoint(broker, "https://www.okx.com")
    assert os.environ["OKX_BASE_URL"] == "https://www.okx.com"
    assert broker.base_url == "https://www.okx.com"
    assert broker.endpoint == "https://www.okx.com"
