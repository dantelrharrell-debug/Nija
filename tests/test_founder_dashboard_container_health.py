"""Run the real dashboard image probe against an isolated loopback server."""

import http.server
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import threading
import unittest


class TestFounderDashboardContainerHealth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile.dashboard"
        text = dockerfile.read_text(encoding="utf-8")
        cls.probe = re.search(r"(?m)^HEALTHCHECK [^\n]*\\\n\s*CMD (.+)$", text).group(1)

    def run_probe(self, port):
        command = (
            json.loads(self.probe) if self.probe.startswith("[")
            else shlex.split(self.probe.split(" || ", 1)[0])
        )
        self.assertEqual(command[0], "python")
        self.assertEqual(command[-2], "-c")
        self.assertIn("localhost", command[-1])
        self.assertIn("/api/health", command[-1])
        command[-1] = command[-1].replace("5001", str(port))
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, *command[1:]],
            env=env,
            capture_output=True,
            timeout=6,
            check=False,
        ).returncode

    def test_http_status_controls_container_health(self):
        for status, healthy in ((200, True), (204, False), (302, False), (401, False), (404, False), (503, False)):
            with self.subTest(status=status):
                class Handler(http.server.BaseHTTPRequestHandler):
                    def do_GET(self):
                        self.send_response(404 if self.path != "/api/health" else status)
                        if status == 302:
                            self.send_header("Location", "/login")
                        self.end_headers()

                    def log_message(self, *_args):
                        pass

                with http.server.HTTPServer(("127.0.0.1", 0), Handler) as server:
                    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
                    worker.start()
                    try:
                        self.assertEqual(self.run_probe(server.server_port) == 0, healthy)
                    finally:
                        server.shutdown()
                        worker.join(timeout=2)

    def test_socket_without_listener_is_unhealthy(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.assertNotEqual(self.run_probe(sock.getsockname()[1]), 0)
