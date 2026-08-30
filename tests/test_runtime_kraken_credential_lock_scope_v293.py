from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from bot import runtime_kraken_credential_lock_scope_v293_patch as v293


class _Broker:
    def __init__(self, key: str | None):
        self.api = SimpleNamespace(key=key) if key is not None else SimpleNamespace()
        self.account_identifier = key or "unknown"


def _reset_state() -> None:
    with v293._LOCK:
        v293._SCOPE_LOCKS.clear()
    for name in ("lock", "scope"):
        try:
            delattr(v293._SCOPE_LOCAL, name)
        except AttributeError:
            pass


def test_credential_scope_key_is_stable_non_plaintext_fingerprint():
    first = _Broker("same-key")
    second = _Broker("same-key")
    other = _Broker("other-key")

    first_scope = v293._credential_scope_key(first)
    assert first_scope
    assert first_scope == v293._credential_scope_key(second)
    assert first_scope != v293._credential_scope_key(other)
    assert "same-key" not in first_scope


def test_missing_credential_identity_does_not_create_scope():
    assert v293._credential_scope_key(_Broker(None)) == ""


def test_same_key_reuses_lock_and_different_key_gets_different_lock():
    _reset_state()
    scope_a = v293._credential_scope_key(_Broker("key-a"))
    scope_b = v293._credential_scope_key(_Broker("key-b"))

    lock_a1 = v293._scoped_lock(scope_a)
    lock_a2 = v293._scoped_lock(scope_a)
    lock_b = v293._scoped_lock(scope_b)

    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b


def test_active_credential_scope_is_visible_to_lock_dispatch(monkeypatch):
    _reset_state()
    fallback = threading.RLock()
    monkeypatch.setattr(v293, "_ORIGINAL_GET_LOCK", lambda: fallback)
    broker = _Broker("key-a")
    observed = []

    def call():
        observed.append(v293._scoped_get_kraken_api_lock())
        return "ok"

    assert v293._invoke_with_credential_scope(broker, call) == "ok"
    assert observed == [v293._scoped_lock(v293._credential_scope_key(broker))]
    assert v293._scoped_get_kraken_api_lock() is fallback


def test_same_key_private_calls_serialize_while_distinct_keys_can_overlap():
    _reset_state()
    same_a = _Broker("shared-key")
    same_b = _Broker("shared-key")
    other = _Broker("other-key")
    shared_scope = v293._credential_scope_key(same_a)
    other_scope = v293._credential_scope_key(other)

    active_total = 0
    peak_total = 0
    active_by_scope = {shared_scope: 0, other_scope: 0}
    peak_by_scope = {shared_scope: 0, other_scope: 0}
    gate = threading.Lock()
    started = threading.Barrier(3)

    def work(broker):
        nonlocal active_total, peak_total
        started.wait(timeout=2.0)
        scope = v293._credential_scope_key(broker)

        def inside():
            nonlocal active_total, peak_total
            scope_lock = v293._scoped_get_kraken_api_lock()
            with scope_lock:
                with gate:
                    active_total += 1
                    active_by_scope[scope] += 1
                    peak_total = max(peak_total, active_total)
                    peak_by_scope[scope] = max(peak_by_scope[scope], active_by_scope[scope])
                time.sleep(0.04)
                with gate:
                    active_by_scope[scope] -= 1
                    active_total -= 1

        v293._invoke_with_credential_scope(broker, inside)

    threads = [
        threading.Thread(target=work, args=(same_a,)),
        threading.Thread(target=work, args=(same_b,)),
        threading.Thread(target=work, args=(other,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    assert peak_by_scope[shared_scope] == 1
    assert peak_by_scope[other_scope] == 1
    assert peak_total <= 2
    assert peak_total >= 1
    assert active_total == 0
