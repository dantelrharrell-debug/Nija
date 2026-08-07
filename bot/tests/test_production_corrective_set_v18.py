from __future__ import annotations

import importlib.util
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

PATCH_PATH = Path(__file__).resolve().parents[1] / "production_corrective_set_v18_patch.py"
spec = importlib.util.spec_from_file_location("v18_under_test", PATCH_PATH)
assert spec and spec.loader
v18 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v18
spec.loader.exec_module(v18)


class FakeRedis:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.writes = []
        self.expire_calls = []
        self.delete_calls = []

    def get(self, key): return self.data.get(key)
    def set(self, key, value, **kwargs): self.writes.append((key, value, kwargs)); self.data[key] = value; return True
    def expire(self, key, ttl): self.expire_calls.append((key, ttl)); return True
    def delete(self, key): self.delete_calls.append(key); self.data.pop(key, None); return 1


def _env_writer(monkeypatch, generation="42", token="tok42"):
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", token)
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", generation)
    monkeypatch.setenv("NIJA_WRITER_GENERATION", generation)
    monkeypatch.setenv("NIJA_WRITER_LOCK_KEY", "nija:writer_lock:test")
    monkeypatch.setenv("NIJA_LEASE_GENERATION_KEY", "nija:lease:generation")


def test_execution_authority_missing_lock_is_read_only(monkeypatch):
    _env_writer(monkeypatch)
    client = FakeRedis({"nija:lease:generation": "42"})
    module = ModuleType("execution_authority_context")
    module.get_redis_url = lambda: "rediss://example"
    module._connect_redis_for_authority = lambda url, timeout_s=2: client
    module._read_current_lease_generation = lambda: (42, "")
    module._FENCE_VERIFY_LOCK = threading.Lock()
    module._FENCE_LAST_CHECK_TS = 0.0; module._FENCE_LAST_OK = False; module._FENCE_LAST_ERR = ""
    assert v18._patch_execution_authority_context(module)
    try:
        module.assert_distributed_writer_authority()
    except RuntimeError as exc:
        assert "lock missing" in str(exc)
    else:
        raise AssertionError("missing process lock must fail closed")
    assert client.writes == [] and client.expire_calls == [] and client.delete_calls == []


def test_authority_heartbeat_writes_only_heartbeat(monkeypatch):
    _env_writer(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_INSTANCE_ID", "instance-a")
    client = FakeRedis({"nija:lease:generation": "42", "nija:writer_lock:test": "tok42:owner"})
    eac = ModuleType("bot.execution_authority_context")
    eac.get_redis_url = lambda: "rediss://example"
    eac._connect_redis_for_authority = lambda url, timeout_s=2: client
    sys.modules["bot.execution_authority_context"] = eac
    sys.modules["execution_authority_context"] = eac
    module = ModuleType("authority_heartbeat")
    module._check_authority_once = lambda timeout_s: (True, "")
    class Monitor: pass
    module.AuthorityHeartbeatMonitor = Monitor
    assert v18._patch_authority_heartbeat(module)
    Monitor()._write_heartbeat_to_redis()
    assert len(client.writes) == 1 and client.writes[0][0] == "nija:writer_heartbeat_active"
    assert client.expire_calls == [] and client.delete_calls == []
    assert client.data["nija:writer_lock:test"] == "tok42:owner"


def test_capital_authority_does_not_auto_enable_writer_bypass(monkeypatch):
    monkeypatch.delenv("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", raising=False)
    module = ModuleType("capital_authority")
    def legacy(real_capital, broker_count):
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
        os.environ["NIJA_" + "FORCE_LOCAL_WRITER_LOCK_FALLBACK"] = "true"
    module._maybe_auto_enable_live_mode = legacy
    assert v18._patch_capital_authority(module)
    module._maybe_auto_enable_live_mode(100.0, 1)
    assert os.environ.get("LIVE_CAPITAL_VERIFIED") == "true"
    assert "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK" not in os.environ


def test_entry_price_store_is_scoped_by_broker():
    module = ModuleType("entry_price_store")
    @dataclass
    class Record:
        price: float; timestamp: int; source: str; quantity: float = 0.0
    class Store:
        def __init__(self): self._records = {}; self._lock = threading.Lock()
        def _persist(self): pass
    module.EntryPriceRecord = Record; module.EntryPriceStore = Store
    assert v18._patch_entry_price_store(module)
    store = Store()
    store.save_scoped("platform:coinbase", "ETH-USD", 1742.92, source="api", quantity=0.006)
    store.save_scoped("platform:okx", "ETH-USD", 1800.0, source="api", quantity=0.0000002)
    cb = store.get_scoped("platform:coinbase", "ETH-USD"); okx = store.get_scoped("platform:okx", "ETH-USD")
    assert cb.price == 1742.92 and cb.quantity == 0.006
    assert okx.price == 1800.0 and okx.quantity == 0.0000002 and cb is not okx


def test_scan_wrapper_recognizes_runtime_v2_owner():
    module = ModuleType("scan_wrapper_convergence_repair_patch")
    module._KNOWN_WRAPPER_MARKERS = ("_nija_scan_wrapper_canonical_v2",); module._MARKER = "scan-marker"
    assert v18._patch_scan_wrapper(module)
    assert "_nija_scan_identity_lock_v2" in module._KNOWN_WRAPPER_MARKERS


def test_writer_epoch_missing_lock_does_not_resurrect(tmp_path):
    path = Path(__file__).resolve().parents[1] / "entrypoint_writer_epoch_recovery_v19_patch.py"
    spec2 = importlib.util.spec_from_file_location("writer_epoch_v19_test", path)
    mod = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(mod)
    ewa = ModuleType("entrypoint_writer_authority")
    class Redis:
        def __init__(self): self.writes=[]
        def get(self, key): return None
        def set(self, *a, **k): self.writes.append((a,k)); return True
    class EWA:
        def __init__(self): self._local_fallback=False; self._client=Redis(); self._lock_key="lock"; self._lock_value="7:owner"
        def _heartbeat_tick(self): self._client.set(self._lock_key, self._lock_value); return True, ""
    ewa.EntrypointWriterAuthority = EWA
    assert mod._patch(ewa)
    runtime=EWA(); ok, reason=runtime._heartbeat_tick()
    assert ok is False and reason == "lock_missing_and_fencing_token_mismatch"
    assert runtime._client.writes == []
