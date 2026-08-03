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
    """Patched get_redis_generation must read from NIJA_LEASE_GENERATION_KEY.

    The previous implementation read from the per-key nonce lease version
    ("nija:kraken:writer:lease_version:{key_id}"), which caused
    ``platform_lease_version_missing`` even when the canonical generation
    counter ("nija:lease:generation") was healthy.  The patch now reads from
    the same key that entrypoint_writer_authority increments atomically.
    """
    patch = _load_patch()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "platform-secret")
    # Use the default key (no NIJA_LEASE_GENERATION_KEY override).
    monkeypatch.delenv("NIJA_LEASE_GENERATION_KEY", raising=False)
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
    # Must use the canonical lease generation key, NOT the per-key nonce key.
    assert requested == ["nija:lease:generation"], (
        f"Expected ['nija:lease:generation'] but got {requested!r}. "
        "The patched get_redis_generation must read from NIJA_LEASE_GENERATION_KEY "
        "(default nija:lease:generation), not nija:kraken:writer:lease_version:..."
    )


def test_tracker_respects_nija_lease_generation_key_override(monkeypatch):
    """NIJA_LEASE_GENERATION_KEY override must be honoured."""
    patch = _load_patch()
    monkeypatch.setenv("NIJA_LEASE_GENERATION_KEY", "nija:custom:gen")
    requested = []

    class Client:
        def get(self, key):
            requested.append(key)
            return "7"

    tracker = ModuleType("fake_tracker")
    tracker.get_redis_generation = lambda: (999, "")
    tracker._connect_redis = lambda timeout_s=2: (Client(), "")

    assert patch._patch_generation_tracker(tracker)
    gen, err = tracker.get_redis_generation()
    assert err == "", f"Unexpected error: {err}"
    assert gen == 7
    assert requested == ["nija:custom:gen"], (
        f"Expected ['nija:custom:gen'] but got {requested!r}"
    )

