"""Exercise Docker-filtered startup with no network, real credentials or runtime."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN groupadd -r nija && useradd -r -g nija -u 1000 nija && chown -R nija:nija /app
USER nija
"""

# Only the final start.sh execution is intercepted. Both production shell front
# doors, all source patchers, syntax checks and the liveness server run normally.
CONTAINER_PROBE = r'''
import os
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="startup-fixture-") as directory:
    fixture = Path(directory)
    boundary = fixture / "boundary.py"
    boundary.write_text("""
import json
import os
import signal
import urllib.request

try:
    assert os.environ["KRAKEN_PLATFORM_API_KEY"] == "offline-fixture-key"
    assert os.environ["KRAKEN_PLATFORM_API_SECRET"] == "b2ZmbGluZS1maXh0dXJl"
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
    assert os.environ["NIJA_WRITER_LEASE_ACQUIRED"] == "0"
    assert os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] == "0"
    assert "NIJA_WRITER_FENCING_TOKEN" not in os.environ
    assert "NIJA_WRITER_LEASE_GENERATION" not in os.environ
    for flag in ("STRICT_REDIS_WRITER_LOCK", "NIJA_REQUIRE_REDIS_FOR_LIVE"):
        assert os.environ[flag] == "true"
    with urllib.request.urlopen("http://127.0.0.1:5000/healthz", timeout=5) as response:
        assert response.status == 200
        assert json.load(response)["status"] == "alive"
    print("ISOLATED_STARTUP_BOUNDARY_REACHED runtime_started=false orders_submitted=false")
finally:
    os.kill(int(os.environ["NIJA_RENDER_LIVENESS_PID"]), signal.SIGTERM)
""")
    shell = fixture / "bash"
    shell.write_text(
        '#!/bin/bash\n'
        'if [[ "${1:-}" == "/app/start.sh" ]]; then\n'
        '    exec python3 -S "$STARTUP_FIXTURE_BOUNDARY"\n'
        'fi\n'
        'exec /bin/bash "$@"\n'
    )
    shell.chmod(0o700)
    env = {
        "PATH": str(fixture) + os.pathsep + os.defpath + ":/usr/local/bin",
        "HOME": directory,
        "STARTUP_FIXTURE_BOUNDARY": str(boundary),
        "RENDER": "true",
        "RENDER_SERVICE_ID": "isolated-offline-fixture",
        "RENDER_GIT_BRANCH": "isolated-offline-fixture",
        "RENDER_GIT_COMMIT": "isolated-offline-fixture",
        "KRAKEN_API_KEY": "offline-fixture-key",
        "KRAKEN_API_SECRET": "b2ZmbGluZS1maXh0dXJl",
        "LIVE_TRADING": "false",
        "LIVE_CAPITAL_VERIFIED": "false",
        "STRICT_REDIS_WRITER_LOCK": "true",
        "NIJA_REQUIRE_REDIS_FOR_LIVE": "true",
        "NIJA_RUNTIME_EXECUTION_AUTHORITY": "0",
        "NIJA_RUNTIME_TRADING_STATE": "OFF",
    }
    result = subprocess.run(
        ["/bin/bash", sys.argv[1]], env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90,
    )
    print(result.stdout)
    raise SystemExit(result.returncode)
'''


class RenderContainerStartupTests(unittest.TestCase):
    """Require the actual Docker context to support both production front doors."""

    @classmethod
    def setUpClass(cls) -> None:
        """Build a dependency-free Python 3.11 startup image using .dockerignore."""
        if shutil.which("docker") is None:
            raise RuntimeError("Docker is required for the container startup regression")
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=30)
        cls.image = "nija-startup-regression:" + uuid.uuid4().hex
        build = subprocess.run(
            ["docker", "build", "--quiet", "--tag", cls.image, "--file", "-", "."],
            input=DOCKERFILE, cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
        if build.returncode:
            raise RuntimeError("Container fixture build failed:\n" + build.stdout + build.stderr)
        cls.addClassCleanup(
            subprocess.run, ["docker", "image", "rm", cls.image],
            check=True, capture_output=True, timeout=30,
        )

    def _assert_startup(self, entrypoint: str) -> None:
        name = "nija-startup-probe-" + uuid.uuid4().hex
        try:
            result = subprocess.run(
                [
                    "docker", "run", "--rm", "--name", name,
                    "--network=none", "--cap-drop=ALL",
                    "--security-opt=no-new-privileges", self.image,
                    "python3", "-S", "-c", CONTAINER_PROBE, entrypoint,
                ],
                capture_output=True, text=True, timeout=120,
            )
        finally:
            subprocess.run(
                ["docker", "rm", "--force", name], capture_output=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ISOLATED_STARTUP_BOUNDARY_REACHED", result.stdout)
        self.assertIn("Early Render liveness confirmed", result.stdout)
        self.assertNotIn("offline-fixture-key", result.stdout + result.stderr)
        self.assertNotIn("b2ZmbGluZS1maXh0dXJl", result.stdout + result.stderr)

    def test_render_entrypoint_completes_shell_preflight(self) -> None:
        """Reach the runtime boundary after the real Render preflight and bootstrap."""
        self._assert_startup("scripts/render_entrypoint.sh")

    def test_production_bootstrap_completes_shell_preflight(self) -> None:
        """The direct production front door must include the same credential helper."""
        self._assert_startup("scripts/production_bootstrap.sh")

    def test_production_build_checks_credential_helper(self) -> None:
        """A missing or invalid sourced helper must fail the production image build."""
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("bash -n /app/scripts/kraken_credential_aliases.sh", dockerfile)
        self.assertIn("test -f /app/scripts/kraken_credential_aliases.sh", dockerfile)


if __name__ == "__main__":
    unittest.main()
