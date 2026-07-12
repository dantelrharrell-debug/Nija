from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT / "writer_generation_scope_repair_patch.py"


def _load_patch():
    spec = importlib.util.spec_from_file_location("writer_generation_scope_repair_patch_test", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_key_id_uses_platform_key(monkeypatch):
    patch = _load_patch()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "platform-secret")
    monkeypatch.setenv("KRAKEN_API_KEY", "fallback-secret")
    assert patch._platform_key_id() == hashlib.sha256(b"platform-secret").hexdigest()[:16]


def test_user_nonce_lease_does_not_overwrite_platform_generation(monkeypatch):
    patch = _load_patch()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "platform-secret")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "101")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION_LAST", "101")

    module = ModuleType("fake_nonce")

    class Backend:
        def _ensure_writer_lease(self, key_id):
            os.environ["NIJA_WRITER_LEASE_GENERATION"] = "202"
            os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = "202"
            return 202

    module._PerKeyRedisBackend = Backend
    assert patch._patch_nonce_backend(module)
    backend = Backend()
    assert backend._ensure_writer_lease("user-key-id") == 202
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "101"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] == "101"


def test_platform_nonce_lease_publishes_platform_generation(monkeypatch):
    patch = _load_patch()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "platform-secret")
    platform_id = hashlib.sha256(b"platform-secret").hexdigest()[:16]

    module = ModuleType("fake_nonce")

    class Backend:
        def _ensure_writer_lease(self, key_id):
            return 303

    module._PerKeyRedisBackend = Backend
    assert patch._patch_nonce_backend(module)
    assert Backend()._ensure_writer_lease(platform_id) == 303
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "303"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] == "303"


def test_tracker_reads_platform_per_key_version(monkeypatch):
    patch = _load_patch()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "platform-secret")
    platform_id = hashlib.sha256(b"platform-secret").hexdigest()[:16]
    requested = []

    class Client:
        def get(self, key):
            requested.append(key)
            return "404"

    tracker = ModuleType("fake_tracker")
    tracker.get_redis_generation = lambda: (999, "")
    tracker._connect_redis = lambda timeout_s=2: (Client(), "")

    assert patch._patch_generation_tracker(tracker)
    assert tracker.get_redis_generation() == (404, "")
    assert requested == [f"nija:kraken:writer:lease_version:{platform_id}"]
