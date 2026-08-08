from __future__ import annotations

import importlib.util
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

PATCH_PATH = Path(__file__).resolve().parents[1] / "capital_publication_convergence_v43_patch.py"


def _load_patch():
    name = "test_capital_publication_convergence_v43_patch"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, PATCH_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Snapshot:
    real_capital: float
    usable_capital: float
    risk_capital: float
    open_exposure_usd: float
    reserve_pct: float
    broker_balances: dict[str, float]
    broker_count: int
    expected_brokers: int
    computed_at: datetime


class Observation:
    def __init__(self, value: float, age_s: float = 0.0):
        self.value = value
        self.observed_monotonic = time.monotonic() - age_s


class FakeCA:
    _AUTHORIZED_WRITER_ID = "mabm_capital_refresh_coordinator"

    def __init__(self):
        self._lock = threading.RLock()
        self._last_typed_snapshot = None
        self._broker_balances = {}
        self._last_updated_total = 0.0
        self.last_updated = None
        self._hydrated = False
        self._warm_start = False
        self.accepted = None

    def publish_snapshot(self, snapshot, writer_id: str):
        if writer_id != self._AUTHORIZED_WRITER_ID:
            return False
        self._last_typed_snapshot = snapshot
        self._broker_balances = dict(snapshot.broker_balances)
        self.last_updated = snapshot.computed_at
        self._hydrated = True
        self.accepted = snapshot
        return True



def _snapshot() -> Snapshot:
    return Snapshot(
        real_capital=95.1159355748,
        usable_capital=93.213616863304,
        risk_capital=93.213616863304,
        open_exposure_usd=0.0,
        reserve_pct=0.02,
        broker_balances={"coinbase": 95.1159355748},
        broker_count=1,
        expected_brokers=3,
        computed_at=datetime.now(timezone.utc),
    )


def _install_guard(monkeypatch, *, okx_age=5.0, kraken_age=5.0):
    guard = ModuleType("bot.capital_refresh_stall_guard_v35")
    guard._OBSERVATIONS = {
        "okx": Observation(144.96287318737, okx_age),
        "kraken": Observation(228.17, kraken_age),
    }
    guard._OBSERVATION_LOCK = threading.Lock()
    guard._freshness_ttl_seconds = lambda: 90.0
    monkeypatch.setitem(sys.modules, "bot.capital_refresh_stall_guard_v35", guard)
    monkeypatch.setitem(sys.modules, "capital_refresh_stall_guard_v35", guard)
    return guard


def _install_brokers(monkeypatch, *, okx_connected=True, kraken_connected=False):
    broker_mod = ModuleType("bot.broker_manager")
    okx = SimpleNamespace(connected=okx_connected, account_type="platform", name="okx")
    kraken = SimpleNamespace(connected=kraken_connected, account_type="platform", name="kraken")
    broker_mod._PLATFORM_BROKER_INSTANCES = {"okx": okx, "kraken": kraken}
    broker_mod.GLOBAL_PLATFORM_BROKERS = broker_mod._PLATFORM_BROKER_INSTANCES
    monkeypatch.setitem(sys.modules, "bot.broker_manager", broker_mod)
    monkeypatch.setitem(sys.modules, "broker_manager", broker_mod)
    return broker_mod


def test_augments_connected_fresh_okx_only(monkeypatch):
    patch = _load_patch()
    _install_guard(monkeypatch)
    _install_brokers(monkeypatch, okx_connected=True, kraken_connected=False)
    repaired, additions = patch._augment_snapshot(_snapshot())
    assert set(repaired.broker_balances) == {"coinbase", "okx"}
    assert abs(repaired.real_capital - 240.07880876217) < 1e-6
    assert repaired.broker_count == 2
    assert "okx" in additions
    assert "kraken" not in additions


def test_stale_okx_not_promoted(monkeypatch):
    patch = _load_patch()
    _install_guard(monkeypatch, okx_age=120.0)
    _install_brokers(monkeypatch, okx_connected=True, kraken_connected=False)
    repaired, additions = patch._augment_snapshot(_snapshot())
    assert repaired == _snapshot() or repaired.broker_balances == {"coinbase": 95.1159355748}
    assert additions == {}


def test_disconnected_okx_not_promoted(monkeypatch):
    patch = _load_patch()
    _install_guard(monkeypatch)
    _install_brokers(monkeypatch, okx_connected=False, kraken_connected=False)
    repaired, additions = patch._augment_snapshot(_snapshot())
    assert repaired.broker_balances == {"coinbase": 95.1159355748}
    assert additions == {}


def test_current_snapshot_value_wins(monkeypatch):
    patch = _load_patch()
    guard = _install_guard(monkeypatch)
    guard._OBSERVATIONS["coinbase"] = Observation(1.0, 1.0)
    _install_brokers(monkeypatch, okx_connected=True, kraken_connected=False)
    repaired, _ = patch._augment_snapshot(_snapshot())
    assert abs(repaired.broker_balances["coinbase"] - 95.1159355748) < 1e-9


def test_recomputes_usable_and_risk(monkeypatch):
    patch = _load_patch()
    _install_guard(monkeypatch)
    _install_brokers(monkeypatch, okx_connected=True, kraken_connected=False)
    snap = Snapshot(**{**_snapshot().__dict__, "open_exposure_usd": 10.0})
    repaired, _ = patch._augment_snapshot(snap)
    assert abs(repaired.usable_capital - repaired.real_capital * 0.98) < 1e-9
    assert abs(repaired.risk_capital - (repaired.usable_capital - 10.0)) < 1e-9


def test_patch_publish_commits_canonical_snapshot(monkeypatch):
    patch = _load_patch()
    _install_guard(monkeypatch)
    _install_brokers(monkeypatch, okx_connected=True, kraken_connected=False)
    module = ModuleType("bot.capital_authority")
    module.CapitalAuthority = FakeCA
    assert patch._patch_capital_authority(module)
    ca = FakeCA()
    assert ca.publish_snapshot(_snapshot(), writer_id=ca._AUTHORIZED_WRITER_ID)
    assert abs(ca.accepted.real_capital - 240.07880876217) < 1e-6
    assert abs(ca.total_capital - ca.accepted.real_capital) < 1e-9
    assert ca._last_updated_total == ca.accepted.real_capital


def test_unauthorized_writer_not_augmented(monkeypatch):
    patch = _load_patch()
    _install_guard(monkeypatch)
    _install_brokers(monkeypatch, okx_connected=True, kraken_connected=False)
    module = ModuleType("bot.capital_authority")
    module.CapitalAuthority = FakeCA
    patch._patch_capital_authority(module)
    ca = FakeCA()
    assert ca.publish_snapshot(_snapshot(), writer_id="other_writer") is False
    assert ca.accepted is None


def test_total_capital_ignores_unattributed_updated_total(monkeypatch):
    patch = _load_patch()
    module = ModuleType("bot.capital_authority")
    module.CapitalAuthority = FakeCA
    patch._patch_capital_authority(module)
    ca = FakeCA()
    ca._last_typed_snapshot = _snapshot()
    ca._broker_balances = {"coinbase": 95.1159355748, "okx": 144.96287318737}
    ca._last_updated_total = 9999.0
    assert abs(ca.total_capital - _snapshot().real_capital) < 1e-9


def test_live_v2_late_patch_is_recanonicalized(monkeypatch):
    patch = _load_patch()
    ca_module = ModuleType("bot.capital_authority")
    ca_module.CapitalAuthority = FakeCA
    patch._patch_capital_authority(ca_module)

    live = ModuleType("bot.capital_authority_live_total_v2_patch")
    def legacy_patch(target):
        def legacy_total(self):
            return 9999.0
        target.CapitalAuthority.total_capital = property(legacy_total)
        return True
    live._patch_module = legacy_patch
    assert patch._patch_live_total_v2(live)
    assert live._patch_module(ca_module)
    ca = FakeCA()
    ca._last_typed_snapshot = _snapshot()
    assert abs(ca.total_capital - _snapshot().real_capital) < 1e-9
