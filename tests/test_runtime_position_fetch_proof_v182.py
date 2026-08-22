from __future__ import annotations

import threading
from types import ModuleType, SimpleNamespace

import bot.runtime_position_fetch_proof_v182_patch as v182


class BrokerType:
    def __init__(self, value: str):
        self.value = value


class Broker:
    def __init__(self, *, connected=True, adopted=False, fetch_ok=None):
        self.connected = connected
        self._startup_position_sync_adopted = adopted
        self._startup_position_sync_fetch_ok = fetch_ok
        self._startup_position_sync_error = None


def test_exact_v98_detection_ignores_wraps_copied_marker():
    def unrelated_wrapper(*args, **kwargs):
        return None

    setattr(unrelated_wrapper, "_nija_position_sync_failure_truth_v98", True)
    assert v182._chain_has_exact_v98_wrapper(unrelated_wrapper) is False


def test_reassert_v98_clears_copied_marker_and_installs_exact_owner(monkeypatch):
    sync = ModuleType("bot.startup_position_sync")

    def base_adopt(broker, broker_name, eps):
        broker._startup_position_sync_adopted = True
        return 0

    setattr(base_adopt, "_nija_position_sync_failure_truth_v98", True)
    sync._adopt_broker_positions = base_adopt

    fake_v98 = ModuleType("bot.position_sync_failure_truth_v98_patch")
    fake_v98.MARKER = "20260815-position-sync-failure-truth-v98"
    fake_v98._ADOPT_ATTR = "_nija_position_sync_failure_truth_v98"
    exec(
        """
from functools import wraps

def _patch_startup_sync(module):
    current = module._adopt_broker_positions
    if getattr(current, _ADOPT_ATTR, False):
        return True
    original = current
    @wraps(original)
    def adopt_broker_positions_v98(broker, broker_name, eps):
        broker._startup_position_sync_adopted = False
        broker._startup_position_sync_fetch_ok = None
        result = int(original(broker, broker_name, eps) or 0)
        if getattr(broker, '_startup_position_sync_adopted', False):
            broker._startup_position_sync_fetch_ok = True
        return result
    setattr(adopt_broker_positions_v98, _ADOPT_ATTR, True)
    setattr(adopt_broker_positions_v98, '__wrapped__', original)
    module._adopt_broker_positions = adopt_broker_positions_v98
    return True
""",
        fake_v98.__dict__,
    )

    monkeypatch.setattr(v182, "_startup_sync_module", lambda: sync)
    monkeypatch.setattr(v182, "_v98_module", lambda: fake_v98)

    ok, detail = v182._reassert_v98_adopter()
    assert ok is True
    assert detail == "v98_reasserted"
    assert v182._chain_has_exact_v98_wrapper(sync._adopt_broker_positions) is True

    broker = Broker(adopted=True, fetch_ok=None)
    sync._adopt_broker_positions(broker, "platform:coinbase", None)
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_fetch_ok is True


def test_discovery_requires_adoption_and_authoritative_fetch_proof():
    coinbase = Broker(adopted=True, fetch_ok=None)
    okx = Broker(adopted=True, fetch_ok=True)
    kraken = Broker(connected=False, adopted=False, fetch_ok=False)
    manager = SimpleNamespace(
        platform_brokers={
            BrokerType("coinbase"): coinbase,
            BrokerType("okx"): okx,
            BrokerType("kraken"): kraken,
        }
    )

    pending = v182._connected_platform_brokers_requiring_proof(manager)
    assert pending == [("coinbase", coinbase)]


def test_worker_revokes_adopted_without_fetch_proof(monkeypatch):
    published: list[str] = []
    active: set[tuple[int, int]] = set()

    def unsafe_legacy_worker(manager, broker_name, broker, key, trigger):
        broker._startup_position_sync_adopted = True
        broker._startup_position_sync_fetch_ok = None
        active.discard(key)

    fake_v108 = SimpleNamespace(
        _worker=unsafe_legacy_worker,
        _ACTIVE=active,
        _LOCK=threading.RLock(),
        _publish_readiness=lambda manager, source: published.append(source),
    )
    monkeypatch.setattr(v182, "_v108_module", lambda: fake_v108)
    monkeypatch.setattr(v182, "_reassert_v98_adopter", lambda: (True, "exact_v98_already_present"))

    assert v182._patch_worker() is True

    broker = Broker(adopted=False, fetch_ok=None)
    manager = object()
    key = (id(manager), id(broker))
    active.add(key)
    fake_v108._worker(manager, "coinbase", broker, key, "test")

    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert broker._startup_position_sync_error == "adopted_without_authoritative_fetch_proof"
    assert key not in active
    assert any("adopted_without_authoritative_fetch_proof" in source for source in published)


def test_worker_blocks_when_exact_v98_cannot_be_proven(monkeypatch):
    calls: list[str] = []
    published: list[str] = []
    active: set[tuple[int, int]] = set()

    def original_worker(manager, broker_name, broker, key, trigger):
        calls.append(broker_name)

    fake_v108 = SimpleNamespace(
        _worker=original_worker,
        _ACTIVE=active,
        _LOCK=threading.RLock(),
        _publish_readiness=lambda manager, source: published.append(source),
    )
    monkeypatch.setattr(v182, "_v108_module", lambda: fake_v108)
    monkeypatch.setattr(v182, "_reassert_v98_adopter", lambda: (False, "exact_v98_not_in_chain_after_repatch"))

    assert v182._patch_worker() is True

    broker = Broker(adopted=True, fetch_ok=True)
    manager = object()
    key = (id(manager), id(broker))
    active.add(key)
    fake_v108._worker(manager, "okx", broker, key, "test")

    assert calls == []
    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert "v98_fetch_proof_wrapper_unavailable" in broker._startup_position_sync_error
    assert key not in active


def test_release_manifest_attests_v182(monkeypatch):
    required = {}
    fake_manifest = SimpleNamespace(_REQUIRED_FLAGS=required)
    real_import = v182.importlib.import_module

    def fake_import(name: str):
        if name == "bot.runtime_release_manifest_patch":
            return fake_manifest
        return real_import(name)

    monkeypatch.setattr(v182.importlib, "import_module", fake_import)
    assert v182._patch_release_manifest() is True
    assert required["runtime_position_fetch_proof_v182"] == (
        "NIJA_RUNTIME_POSITION_FETCH_PROOF_V182_READY"
    )
