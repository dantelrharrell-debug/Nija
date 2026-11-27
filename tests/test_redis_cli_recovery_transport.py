"""Exercise CLI launch arguments without running recovery or contacting Redis."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


class RedisCliRecoveryTransportTests(unittest.TestCase):
    def invoke(self, endpoint, result=None):
        root = Path(__file__).resolve().parents[1]
        tail = (root / "start.sh").read_text().split("_redis_cli_run() {", 1)[1]
        source = tail.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        namespace = {}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"NIJA_REDIS_CLI_URL": endpoint,
                                     "REDISCLI_AUTH": "unrelated-test-value"}, clear=True), \
             patch.object(sys, "argv", ["-", "PING"]), \
             patch.object(subprocess, "run", return_value=result) as run, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as stopped:
                exec(compile(source, "start.sh:redis-cli", "exec"), namespace)
        return stopped.exception.code, stdout.getvalue(), stderr.getvalue(), run

    def test_tls_and_auth_stay_out_of_process_arguments(self):
        result = subprocess.CompletedProcess([], 0, "PONG\n", "")
        code, out, err, run = self.invoke("rediss://tester:d%75mmy@redis.example:6380/2", result)
        self.assertEqual((code, out, err), (0, "PONG\n", ""))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd, ["redis-cli", "-h", "redis.example", "-p", "6380",
                               "-n", "2", "--user", "tester", "--tls", "--sni",
                               "redis.example", "PING"])
        self.assertEqual(run.call_args.kwargs["env"]["REDISCLI_AUTH"], "dummy")
        self.assertNotIn("NIJA_REDIS_CLI_URL", run.call_args.kwargs["env"])

    def test_plain_private_redis_does_not_inherit_another_password(self):
        result = subprocess.CompletedProcess([], 0, "PONG\n", "")
        code, _, _, run = self.invoke("redis://redis.internal:6379", result)
        self.assertEqual(code, 0)
        self.assertNotIn("--tls", run.call_args.args[0])
        self.assertNotIn("REDISCLI_AUTH", run.call_args.kwargs["env"])

    def test_invalid_endpoint_and_provider_error_do_not_echo_credentials(self):
        invalid_code, invalid_out, invalid_err, invalid_call = self.invoke(
            "rediss://tester:dummy@redis.example:bad"
        )
        self.assertEqual(invalid_code, 1)
        invalid_call.assert_not_called()
        self.assertNotIn("dummy", invalid_out + invalid_err)
        failed = subprocess.CompletedProcess([], 1, "dummy", "dummy")
        code, out, err, _ = self.invoke("rediss://tester:dummy@redis.example:6380", failed)
        self.assertEqual(code, 1)
        self.assertNotIn("dummy", out + err)
