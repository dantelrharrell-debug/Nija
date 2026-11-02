"""Exercise production Redis nonce Lua against isolated synthetic ownership."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import redis

from bot.distributed_nonce_manager import _PerKeyRedisBackend


class RedisNonceConcurrencyTests(unittest.TestCase):
    """No production Redis, credentials, lease acquisition or Kraken calls."""

    @classmethod
    def setUpClass(cls) -> None:
        executable = shutil.which("redis-server")
        if executable is None:
            raise RuntimeError("redis-server required for isolated nonce integration tests")
        cls.directory = tempfile.TemporaryDirectory(prefix="nija-nonce-test-")
        cls.addClassCleanup(cls.directory.cleanup)
        socket = str(Path(cls.directory.name) / "redis.sock")
        cls.server = subprocess.Popen(
            [
                executable, "--port", "0", "--unixsocket", socket,
                "--unixsocketperm", "600", "--save", "", "--appendonly", "no",
                "--daemonize", "no", "--dir", cls.directory.name,
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.addClassCleanup(cls.stop_server)
        cls.client = redis.Redis(unix_socket_path=socket, decode_responses=True, socket_timeout=1)
        cls.addClassCleanup(cls.client.close)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if cls.client.ping():
                    return
            except redis.ConnectionError:
                if cls.server.poll() is not None:
                    break
                time.sleep(0.02)
        raise RuntimeError("isolated Redis did not become responsive")

    @classmethod
    def stop_server(cls) -> None:
        """Stop only the exact child owned by this test."""
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def setUp(self) -> None:
        self.key = self._testMethodName
        self.owner_key = _PerKeyRedisBackend._LEASE_OWNER_PREFIX + self.key
        self.version_key = _PerKeyRedisBackend._LEASE_VERSION_PREFIX + self.key
        self.client.set(self.owner_key, "synthetic-owner", px=60000)
        self.client.set(self.version_key, 7, px=60000)

    def backend(self, owner: str = "synthetic-owner", generation: int = 7) -> _PerKeyRedisBackend:
        """Bind the actual production Lua; do not mock its atomic operations."""
        backend = _PerKeyRedisBackend.__new__(_PerKeyRedisBackend)
        backend._owner_id = owner
        backend._next_with_fence_script = self.client.register_script(
            _PerKeyRedisBackend._NEXT_WITH_FENCE_LUA
        )
        # Ownership is synthetic test setup; the production parent authority
        # guard is tested separately and never acquired by this fixture.
        backend._ensure_writer_lease = lambda key: generation
        return backend

    def test_concurrent_requests_have_unique_strictly_increasing_nonces(self) -> None:
        backends = [self.backend(), self.backend()]
        high_water = int(time.time() * 1000) + 600000
        self.client.set(_PerKeyRedisBackend._KEY_PREFIX + self.key, high_water)
        with ThreadPoolExecutor(max_workers=16) as pool:
            values = list(pool.map(lambda index: backends[index % 2].next_nonce(self.key), range(1000)))
        self.assertEqual(len(values), 1000)
        self.assertEqual(len(set(values)), 1000)
        ordered = sorted(values)
        self.assertEqual(ordered, list(range(high_water + 1, high_water + 1001)))
        self.assertGreater(self.backend().next_nonce(self.key), ordered[-1])

    def test_independent_processes_share_the_same_fenced_counter(self) -> None:
        code = """
import json
import sys
import redis
from bot.distributed_nonce_manager import _PerKeyRedisBackend
client = redis.Redis(unix_socket_path=sys.argv[1], decode_responses=True, socket_timeout=1)
backend = _PerKeyRedisBackend.__new__(_PerKeyRedisBackend)
backend._owner_id = "synthetic-owner"
backend._next_with_fence_script = client.register_script(_PerKeyRedisBackend._NEXT_WITH_FENCE_LUA)
backend._ensure_writer_lease = lambda key: 7
print(json.dumps([backend.next_nonce(sys.argv[2]) for _ in range(100)]))
client.close()
"""
        high_water = int(time.time() * 1000) + 600000
        self.client.set(_PerKeyRedisBackend._KEY_PREFIX + self.key, high_water)
        children = []
        try:
            for _ in range(4):
                children.append(subprocess.Popen(
                    [sys.executable, "-c", code, str(Path(self.directory.name) / "redis.sock"), self.key],
                    cwd=Path(__file__).resolve().parents[1],
                    env={"NIJA_DEFER_RUNTIME_SITE_HOOKS": "1", "PYTHONDONTWRITEBYTECODE": "1"},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ))
            values = []
            for child in children:
                stdout, stderr = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, stderr)
                values.extend(json.loads(stdout))
            self.assertEqual(sorted(values), list(range(high_water + 1, high_water + 401)))
            self.assertGreater(self.backend().next_nonce(self.key), high_water + 400)
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)

    def test_restart_and_writer_handoff_never_lower_the_high_water_mark(self) -> None:
        first = self.backend()
        previous = first.next_nonce(self.key)
        self.assertGreater(self.backend().next_nonce(self.key), previous)
        high_water = int(self.client.get(_PerKeyRedisBackend._KEY_PREFIX + self.key))
        self.client.set(self.owner_key, "replacement-owner", px=60000)
        self.client.set(self.version_key, 8, px=60000)
        with self.assertRaisesRegex(RuntimeError, "Redis fencing check rejected"):
            first.next_nonce(self.key)
        self.assertEqual(int(self.client.get(_PerKeyRedisBackend._KEY_PREFIX + self.key)), high_water)
        self.assertGreater(self.backend("replacement-owner", 8).next_nonce(self.key), high_water)

    def test_changed_generation_and_expired_owner_cannot_issue(self) -> None:
        backend = self.backend()
        previous = backend.next_nonce(self.key)
        self.client.set(self.version_key, 8, px=60000)
        with self.assertRaisesRegex(RuntimeError, "VERSION_MISMATCH"):
            backend.next_nonce(self.key)
        self.client.delete(self.owner_key)
        with self.assertRaisesRegex(RuntimeError, "OWNER_MISMATCH"):
            backend.next_nonce(self.key)
        self.assertEqual(int(self.client.get(_PerKeyRedisBackend._KEY_PREFIX + self.key)), previous)
