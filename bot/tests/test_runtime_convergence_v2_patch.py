from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_convergence_v2_patch_test_module",
    ROOT / "runtime_convergence_v2_patch.py",
)
assert SPEC and SPEC.loader
patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch)


def test_identity_does_not_depend_on_core_loop_object():
    broker = SimpleNamespace(account_id="USER:tania_gilbert", broker_name="kraken")
    assert patch._identity(broker) == "user:tania_gilbert:kraken"


def test_duplicate_scans_for_same_account_are_blocked(monkeypatch):
    patch._SCAN_LOCKS.clear()
    module = ModuleType("bot.nija_core_loop")
    entered = threading.Event()
    release = threading.Event()

    class NijaCoreLoop:
        def run_scan_phase(self, broker):
            entered.set()
            release.wait(2)
            return (1, 0, 1, {})

    module.NijaCoreLoop = NijaCoreLoop
    monkeypatch.setenv("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "0.05")
    assert patch._patch_core_loop(module) is True
    broker = SimpleNamespace(account_id="platform", broker_name="kraken")
    first_result = []
    first = threading.Thread(target=lambda: first_result.append(NijaCoreLoop().run_scan_phase(broker)))
    first.start()
    assert entered.wait(1)
    second = NijaCoreLoop().run_scan_phase(broker)
    assert second == (0, 1, 0, {"duplicate_scan": 1})
    release.set()
    first.join(1)
    assert first_result == [(1, 0, 1, {})]


def test_coinbase_constructor_normalizes_before_client_creation(monkeypatch):
    calls: list[str] = []
    fake_auth = ModuleType("broker_auth_recovery_patch")
    fake_auth.normalize_coinbase_environment = lambda: calls.append("normalize") or True
    fake_auth.normalize_okx_environment = lambda: True
    real_import = patch.importlib.import_module
    monkeypatch.setattr(
        patch.importlib,
        "import_module",
        lambda name: fake_auth if name == "broker_auth_recovery_patch" else real_import(name),
    )
    module = ModuleType("bot.broker_integration")

    class CoinbaseBrokerAdapter:
        def __init__(self):
            calls.append("construct")
            self.position_tracker = None

    module.CoinbaseBrokerAdapter = CoinbaseBrokerAdapter
    assert patch._patch_broker_classes(module) is True
    CoinbaseBrokerAdapter()
    assert calls == ["normalize", "construct"]


def test_shared_tracker_is_rebound_to_account_scoped_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NIJA_POSITION_STATE_DIR", str(tmp_path))

    class Tracker:
        def __init__(self, storage_file="positions.json"):
            self.storage_file = storage_file

    broker = SimpleNamespace(
        account_id="USER:daivon_frazier",
        broker_name="kraken",
        position_tracker=Tracker(),
    )
    assert patch._rebind_tracker(broker) is True
    assert broker.position_tracker.storage_file.endswith("positions_user_daivon_frazier_kraken.json")
