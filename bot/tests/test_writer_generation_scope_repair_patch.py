from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

from bot import writer_generation_tracker


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
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "fixture-fence")

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
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "101")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION_LAST", "101")
    monkeypatch.delenv("NIJA_PLATFORM_NONCE_LEASE_GENERATION", raising=False)
    platform_id = hashlib.sha256(b"platform-secret").hexdigest()[:16]

    module = ModuleType("fake_nonce")

    class Backend:
        def _ensure_writer_lease(self, key_id):
            return 303

    module._PerKeyRedisBackend = Backend
    assert patch._patch_nonce_backend(module)
    assert Backend()._ensure_writer_lease(platform_id) == 303
    assert os.environ["NIJA_PLATFORM_NONCE_LEASE_GENERATION"] == "303"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "101"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] == "101"


def test_user_nonce_publisher_never_exposes_user_generation(monkeypatch):
    patch = _load_patch()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "platform-secret")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "101")
    observed = []

    module = ModuleType("fake_nonce")

    class Backend:
        def _publish_lock_acquired_state(self, lease_version):
            os.environ["NIJA_WRITER_LEASE_GENERATION"] = str(lease_version)
            observed.append(os.environ["NIJA_WRITER_LEASE_GENERATION"])

        def _ensure_writer_lease(self, key_id):
            self._publish_lock_acquired_state(202)
            return 202

    module._PerKeyRedisBackend = Backend
    assert patch._patch_nonce_backend(module)

    assert Backend()._ensure_writer_lease("user-key-id") == 202
    assert observed == []
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "101"


def test_tracker_reads_canonical_generation_key(monkeypatch):
    """The compatibility shim leaves the real process generation reader in place."""
    patch = _load_patch()
    monkeypatch.delenv("NIJA_LEASE_GENERATION_KEY", raising=False)
    client = Mock()
    client.get.return_value = "404"
    monkeypatch.setattr(writer_generation_tracker, "_connect_redis", Mock(return_value=(client, "")))
    original = writer_generation_tracker.get_redis_generation

    assert patch._patch_generation_tracker(writer_generation_tracker)
    assert writer_generation_tracker.get_redis_generation is original
    assert writer_generation_tracker.get_redis_generation() == (404, "")
    client.get.assert_called_once_with("nija:lease:generation")


def test_tracker_respects_nija_lease_generation_key_override(monkeypatch):
    patch = _load_patch()
    monkeypatch.setenv("NIJA_LEASE_GENERATION_KEY", "nija:custom:gen")
    client = Mock()
    client.get.return_value = "7"
    monkeypatch.setattr(writer_generation_tracker, "_connect_redis", Mock(return_value=(client, "")))

    assert patch._patch_generation_tracker(writer_generation_tracker)
    assert writer_generation_tracker.get_redis_generation() == (7, "")
    client.get.assert_called_once_with("nija:custom:gen")
