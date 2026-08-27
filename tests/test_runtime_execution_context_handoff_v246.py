from __future__ import annotations

import concurrent.futures
import contextvars
import os
from types import SimpleNamespace

import bot.runtime_execution_context_handoff_v246_patch as v246


def test_executor_propagates_existing_contextvar():
    probe = contextvars.ContextVar("probe", default="none")
    token = probe.set("HEARTBEAT_TRADE")
    try:
        with v246._ContextPropagatingThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(probe.get).result(timeout=2.0) == "HEARTBEAT_TRADE"
    finally:
        probe.reset(token)


def test_executor_does_not_invent_context():
    probe = contextvars.ContextVar("probe_default", default="none")
    with v246._ContextPropagatingThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(probe.get).result(timeout=2.0) == "none"


def test_stdlib_executor_is_not_globally_replaced():
    assert concurrent.futures.ThreadPoolExecutor is not v246._ContextPropagatingThreadPoolExecutor


def test_patch_is_local_to_execution_pipeline_module():
    fake_concurrent = SimpleNamespace(futures=concurrent.futures)
    fake_pipeline = SimpleNamespace(concurrent=fake_concurrent)

    assert v246._patch_execution_pipeline(fake_pipeline) is True
    assert fake_pipeline.concurrent.futures.ThreadPoolExecutor is v246._ContextPropagatingThreadPoolExecutor
    assert concurrent.futures.ThreadPoolExecutor is not v246._ContextPropagatingThreadPoolExecutor


def test_patch_is_idempotent():
    fake_concurrent = SimpleNamespace(futures=concurrent.futures)
    fake_pipeline = SimpleNamespace(concurrent=fake_concurrent)

    assert v246._patch_execution_pipeline(fake_pipeline) is True
    patched = fake_pipeline.concurrent
    assert v246._patch_execution_pipeline(fake_pipeline) is True
    assert fake_pipeline.concurrent is patched


def test_provenance_installer_is_required(monkeypatch):
    calls = []
    fake_v228 = SimpleNamespace(install=lambda: calls.append("v228") or True)
    real_import = v246.importlib.import_module

    def fake_import(name: str):
        if name == "bot.exchange_reject_dispatch_provenance_v228_patch":
            return fake_v228
        return real_import(name)

    monkeypatch.setattr(v246.importlib, "import_module", fake_import)
    assert v246._install_exchange_rejection_provenance() is True
    assert calls == ["v228"]


def test_provenance_failure_keeps_v246_fail_closed(monkeypatch):
    calls = []

    monkeypatch.setattr(v246, "_install_exchange_rejection_provenance", lambda: calls.append("provenance") or False)
    monkeypatch.setattr(v246, "_patch_execution_pipeline", lambda: calls.append("pipeline") or True)
    monkeypatch.setattr(v246, "_register_manifest", lambda: calls.append("manifest") or True)

    old = os.environ.get(v246._FLAG)
    try:
        assert v246.install() is False
        assert os.environ.get(v246._FLAG) == "0"
        assert calls == ["provenance", "manifest"]
    finally:
        if old is None:
            os.environ.pop(v246._FLAG, None)
        else:
            os.environ[v246._FLAG] = old


def test_install_orders_provenance_before_pipeline(monkeypatch):
    calls = []

    monkeypatch.setattr(v246, "_install_exchange_rejection_provenance", lambda: calls.append("provenance") or True)
    monkeypatch.setattr(v246, "_patch_execution_pipeline", lambda: calls.append("pipeline") or True)
    monkeypatch.setattr(v246, "_register_manifest", lambda: calls.append("manifest") or True)

    old = os.environ.get(v246._FLAG)
    try:
        assert v246.install() is True
        assert os.environ.get(v246._FLAG) == "1"
        assert calls == ["provenance", "pipeline", "manifest"]
    finally:
        if old is None:
            os.environ.pop(v246._FLAG, None)
        else:
            os.environ[v246._FLAG] = old


def test_manifest_registration_is_bounded(monkeypatch):
    required = {}
    installers = tuple()
    fake_manifest = SimpleNamespace(_REQUIRED_FLAGS=required, _INSTALLERS=installers)
    real_import = v246.importlib.import_module

    def fake_import(name: str):
        if name == "bot.runtime_release_manifest_patch":
            return fake_manifest
        return real_import(name)

    monkeypatch.setattr(v246.importlib, "import_module", fake_import)
    assert v246._register_manifest() is True
    assert required["runtime_execution_context_handoff_v246"] == v246._FLAG
    assert fake_manifest._INSTALLERS.count(
        ("bot.runtime_execution_context_handoff_v246_patch", "install_import_hook")
    ) == 1
    assert v246._register_manifest() is True
    assert fake_manifest._INSTALLERS.count(
        ("bot.runtime_execution_context_handoff_v246_patch", "install_import_hook")
    ) == 1
