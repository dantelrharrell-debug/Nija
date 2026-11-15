"""Execute actual diagnostic functions without starting a bot or Redis client."""
import ast
import os
from pathlib import Path
import re
import secrets
import subprocess
from types import CodeType, FunctionType
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _functions(path: str, names: tuple[str, ...], namespace: dict) -> dict:
    """Load exact function bodies only; never execute runtime module startup."""
    tree = ast.parse((ROOT / path).read_text())
    definitions = [node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(definitions) != len(names):
        raise AssertionError("diagnostic function boundary changed")
    isolated = ast.Module(body=definitions, type_ignores=[])
    compiled = compile(isolated, path, "exec")
    # Construct only the selected function objects. Do not execute module code,
    # decorators, annotations, startup hooks or any module-level statement.
    for code in compiled.co_consts:
        if isinstance(code, CodeType) and code.co_name in names:
            namespace[code.co_name] = FunctionType(code, namespace)
    return namespace


class RedisConfigurationErrorPrivacyTests(unittest.TestCase):
    """Malformed values must deny configuration without disclosing any bytes."""

    def setUp(self) -> None:
        """Generate disposable markers rather than committing credential values."""
        self.marker = secrets.token_hex(16)
        self.invalid = [
            self.marker,
            "https://example.invalid/" + self.marker,
            "https://operator:" + self.marker + "@example.invalid/",
            "https://example.invalid/?access_token=" + self.marker,
            "https://operator@example.invalid/?access_token=" + self.marker,
            "https://operator@example.invalid/#" + self.marker,
            "https://operator@@example.invalid/" + self.marker,
            self.marker + "\nINJECTED_LOG_LINE",
            self.marker * 8,
        ]
        namespace = _functions("bot/startup_env.py", ("normalize_optional_env_value",), {})
        namespace["os"] = os
        self.helper = _functions(
            "bot/redis_env.py", ("_strip_wrapping_quotes", "get_nija_url_format_error"), namespace,
        )["get_nija_url_format_error"]
        self.runtime = _functions(
            "bot.py", ("_validate_nija_redis_env",),
            {"os": os, "_force_redis_tls": False, "_redis_url": ""},
        )["_validate_nija_redis_env"]

    def test_shared_helper_withholds_entire_invalid_value(self) -> None:
        """Neither raw strings nor URL suffixes belong in diagnostic messages."""
        messages = set()
        for value in self.invalid:
            with self.subTest(value_index=self.invalid.index(value)):
                with patch.dict(os.environ, {"NIJA_REDIS_URL": value}, clear=True):
                    message = self.helper()
                self.assertIn("not a valid Redis", message)
                self.assertNotIn(self.marker, message)
                self.assertNotIn("INJECTED_LOG_LINE", message)
                messages.add(message)
        self.assertEqual(len(messages), 1)

    def test_runtime_validator_still_denies_without_echo(self) -> None:
        """Execute the real nested validator, not the bot's outer startup."""
        for value in self.invalid:
            with self.subTest(value_index=self.invalid.index(value)):
                with patch.dict(os.environ, {"NIJA_REDIS_URL": value}, clear=True):
                    with self.assertRaises(RuntimeError) as denied:
                        self.runtime()
                self.assertNotIn(self.marker, str(denied.exception))
                self.assertNotIn("INJECTED_LOG_LINE", str(denied.exception))

    def test_supported_schemes_and_unset_values_preserve_behavior(self) -> None:
        """Message changes must not alter the existing scheme decision."""
        for value in ("", "redis://example.invalid:6379/0", "rediss://example.invalid:6379/0"):
            with self.subTest(scheme=value.partition(":")[0]):
                with patch.dict(os.environ, {"NIJA_REDIS_URL": value}, clear=True):
                    self.assertEqual(self.helper(), "")
                    self.assertIsNone(self.runtime())

    def test_runtime_whitespace_and_wrapping_quotes_still_deny(self) -> None:
        """Keep the stricter runtime formatting checks intact."""
        for value in (" redis://example.invalid", '"redis://example.invalid"'):
            with patch.dict(os.environ, {"NIJA_REDIS_URL": value}, clear=True):
                with self.assertRaises(RuntimeError):
                    self.runtime()

    def _shell_validation(self, value: str) -> subprocess.CompletedProcess:
        source = (ROOT / "start.sh").read_text()
        match = re.search(
            r"^_validate_redis_not_http_endpoint\(\) \{\n.*?^\}", source, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        script = (
            '_resolve_redis_url() { printf "%s" "$NIJA_REDIS_URL"; }\n'
            "exit_config_error() { exit 78; }\n"
            + match.group() + "\n_validate_redis_not_http_endpoint\n"
        )
        return subprocess.run(
            ["bash", "-c", script], env={"PATH": os.defpath, "NIJA_REDIS_URL": value},
            capture_output=True, text=True, timeout=5,
        )

    def test_shell_rejects_http_without_exposing_connection(self) -> None:
        """The actual shell function exits before any runtime/client startup."""
        for value in self.invalid[1:7]:
            with self.subTest(value_index=self.invalid.index(value)):
                result = self._shell_validation(value)
                self.assertEqual(result.returncode, 78)
                output = result.stdout + result.stderr
                self.assertIn("CRITICAL", output)
                self.assertNotIn(self.marker, output)
                self.assertNotIn("operator@", output)

    def test_shell_keeps_redis_scheme_decision(self) -> None:
        """The HTTP-specific gate retains its accepted Redis scheme behavior."""
        for value in ("", "redis://example.invalid:6379", "rediss://example.invalid:6379"):
            self.assertEqual(self._shell_validation(value).returncode, 0)


if __name__ == "__main__":
    unittest.main()
