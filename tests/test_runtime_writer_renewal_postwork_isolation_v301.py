from __future__ import annotations

import threading
import time
from types import ModuleType, SimpleNamespace

import bot.runtime_heartbeat_marker_convergence_v238_patch as v238


def _runtime(generation: int = 5012, token: str = "3699"):
    return SimpleNamespace(
        acquired=True,
        lost=False,
        _generation=generation,
        _token=token,
        _nija_lease_renewal_health=lambda: (True, "renewal_healthy", 0.1, 11.25),
    )


def _join_worker(runtime, timeout: float = 2.0):
    worker = getattr(runtime, v238._POSTWORK_THREAD_ATTR, None)
    if worker is not None:
        worker.join(timeout=timeout)
    return worker


def test_postwork_dispatch_is_nonblocking_and_single_flight(monkeypatch):
    runtime = _runtime()
    entered = threading.Event()
    release = threading.Event()
    calls = {"rearm": 0, "wake": 0}

    def rearm(*, allow_publication_arm=False):
        assert allow_publication_arm is True
        calls["rearm"] += 1
        entered.set()
        assert release.wait(2.0)
        return False, "strategy_not_published:publication_monitor_armed"

    def wake(source):
        calls["wake"] += 1
        assert source == "entrypoint_writer_renewal_async_v301"
        return False

    monkeypatch.setattr(v238, "_rearm_genuine_heartbeat", rearm)
    monkeypatch.setattr(v238, "_wake_activation_after_genuine_marker", wake)

    start = time.monotonic()
    dispatched, detail = v238._dispatch_writer_renewal_postwork(runtime)
    elapsed = time.monotonic() - start

    assert dispatched is True
    assert detail == "postwork_dispatched"
    assert elapsed < 0.25
    assert entered.wait(1.0)

    dispatched2, detail2 = v238._dispatch_writer_renewal_postwork(runtime)
    assert dispatched2 is False
    assert detail2 == "postwork_in_flight"
    assert calls["rearm"] == 1

    release.set()
    worker = _join_worker(runtime)
    assert worker is not None and not worker.is_alive()
    assert calls == {"rearm": 1, "wake": 1}


def test_stale_generation_suppresses_activation_after_rearm(monkeypatch):
    runtime = _runtime()
    rearm_entered = threading.Event()
    rearm_release = threading.Event()
    wake_calls = []

    def rearm(*, allow_publication_arm=False):
        rearm_entered.set()
        assert rearm_release.wait(2.0)
        return True, "scheduler_alive"

    monkeypatch.setattr(v238, "_rearm_genuine_heartbeat", rearm)
    monkeypatch.setattr(
        v238,
        "_wake_activation_after_genuine_marker",
        lambda source: wake_calls.append(source) or True,
    )

    dispatched, _ = v238._dispatch_writer_renewal_postwork(runtime)
    assert dispatched is True
    assert rearm_entered.wait(1.0)

    runtime._generation = 5013
    runtime._token = "3700"
    rearm_release.set()
    worker = _join_worker(runtime)

    assert worker is not None and not worker.is_alive()
    assert wake_calls == []


def test_worker_exception_never_changes_writer_epoch(monkeypatch):
    runtime = _runtime()
    original = (runtime.acquired, runtime.lost, runtime._generation, runtime._token)

    monkeypatch.setattr(
        v238,
        "_rearm_genuine_heartbeat",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic-test-error")),
    )
    monkeypatch.setattr(
        v238,
        "_wake_activation_after_genuine_marker",
        lambda source: (_ for _ in ()).throw(AssertionError("wake must not run")),
    )

    dispatched, _ = v238._dispatch_writer_renewal_postwork(runtime)
    assert dispatched is True
    worker = _join_worker(runtime)

    assert worker is not None and not worker.is_alive()
    assert (runtime.acquired, runtime.lost, runtime._generation, runtime._token) == original


def test_heartbeat_wrapper_returns_while_postwork_is_blocked(monkeypatch):
    module = ModuleType("fake_entrypoint_writer_authority_v301")
    renewal_returned = threading.Event()
    postwork_entered = threading.Event()
    postwork_release = threading.Event()

    class Authority:
        def __init__(self):
            self.acquired = True
            self.lost = False
            self._generation = 5012
            self._token = "3699"

        def _nija_lease_renewal_health(self):
            return True, "renewal_healthy", 0.0, 11.25

        def _heartbeat_tick(self):
            renewal_returned.set()
            return True, ""

    module.EntrypointWriterAuthority = Authority

    monkeypatch.setattr(v238.importlib, "import_module", lambda name: module)

    def blocking_postwork(runtime):
        def worker():
            postwork_entered.set()
            postwork_release.wait(2.0)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return True, "postwork_dispatched"

    monkeypatch.setattr(v238, "_dispatch_writer_renewal_postwork", blocking_postwork)

    assert v238._patch_entrypoint_writer() is True
    runtime = Authority()
    result_box = []

    def invoke():
        result_box.append(runtime._heartbeat_tick())

    caller = threading.Thread(target=invoke, name="entrypoint-writer-lock-heartbeat")
    caller.start()
    caller.join(timeout=0.5)

    assert renewal_returned.is_set()
    assert postwork_entered.wait(0.5)
    assert not caller.is_alive()
    assert result_box == [(True, "")]
    postwork_release.set()


def test_worker_does_not_start_for_noncurrent_epoch():
    runtime = _runtime()
    runtime.lost = True
    dispatched, detail = v238._dispatch_writer_renewal_postwork(runtime)
    assert dispatched is False
    assert detail == "writer_epoch_not_current"


def test_v301_manifest_registration(monkeypatch):
    required = {}
    manifest = SimpleNamespace(_REQUIRED_FLAGS=required)
    original_import = v238.importlib.import_module

    def fake_import(name):
        if name == "bot.runtime_release_manifest_patch":
            return manifest
        return original_import(name)

    monkeypatch.setattr(v238.importlib, "import_module", fake_import)

    assert v238._register_v301_manifest() is True
    assert required["runtime_writer_renewal_postwork_isolation_v301"] == v238.V301_READY_FLAG
