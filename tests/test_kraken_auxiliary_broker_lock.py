"""Exercise auxiliary serialization against the actual v293 lock registry."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sys
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

import kraken_private_nonce as auxiliary
from bot import runtime_kraken_credential_lock_scope_v293_patch as broker_locks


@pytest.mark.parametrize("existing_path", ["credential", "legacy"])
def test_auxiliary_waits_for_existing_transport_and_then_releases(existing_path):
    global_lock = threading.RLock()
    broker = SimpleNamespace(api=SimpleNamespace(key="shared-key"))
    scope = broker_locks._credential_scope_key(broker)
    scoped_lock = broker_locks._scoped_lock(scope)
    assert scope == hashlib.sha256(b"shared-key").hexdigest()
    fake_global = ModuleType("bot.global_kraken_nonce")
    fake_global.get_kraken_api_lock = lambda: global_lock
    held = scoped_lock if existing_path == "credential" else global_lock
    worker_started = threading.Event()
    entered = threading.Event()

    def worker():
        worker_started.set()
        with auxiliary._request_locks("shared-key"):
            entered.set()

    with patch.dict(sys.modules, {"bot.global_kraken_nonce": fake_global}):
        with ThreadPoolExecutor(max_workers=1) as pool:
            with held:
                future = pool.submit(worker)
                assert worker_started.wait(timeout=1)
                assert not entered.wait(timeout=0.1)
            future.result(timeout=1)
        assert entered.is_set()
        assert global_lock.acquire(blocking=False)
        global_lock.release()
        assert scoped_lock.acquire(blocking=False)
        scoped_lock.release()


def test_transport_failure_releases_both_locks():
    global_lock = threading.Lock()
    scoped_lock = threading.Lock()
    fake_global = ModuleType("bot.global_kraken_nonce")
    fake_global.get_kraken_api_lock = lambda: global_lock
    with patch.dict(sys.modules, {"bot.global_kraken_nonce": fake_global}), \
            patch.object(broker_locks, "_scoped_lock", return_value=scoped_lock):
        with pytest.raises(RuntimeError, match="transport_failed"):
            with auxiliary._request_locks("shared-key"):
                raise RuntimeError("transport_failed")
    assert global_lock.acquire(blocking=False)
    global_lock.release()
    assert scoped_lock.acquire(blocking=False)
    scoped_lock.release()
