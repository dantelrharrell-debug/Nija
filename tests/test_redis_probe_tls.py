"""Offline transport tests: authenticate Redis only after certificate verification."""
import ast
from pathlib import Path
import socket
import ssl
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse, urlunparse


def isolated_probe() -> types.ModuleType:
    """Load probe functions without importing the bot startup package."""
    source = Path(__file__).resolve().parents[1] / "scripts/redis_endpoint_probe.py"
    tree = ast.parse(source.read_text())
    names = {"_ping_once", "_resp", "_read_line", "_read_resp", "_tls_auto_insecure"}
    selected = ast.Module(body=[node for node in tree.body
                                if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    module = types.ModuleType("isolated_redis_probe")
    module.__dict__.update(socket=socket, ssl=ssl, urlparse=urlparse)
    exec(compile(ast.fix_missing_locations(selected), str(source), "exec"), module.__dict__)
    return module


class RedisProbeTLSTests(unittest.TestCase):
    """Prevent credential transmission after TLS verification failures."""

    def probe_url(self) -> str:
        """Build an offline fixture with a reserved example host and fake password."""
        return urlunparse(("rediss", "default:synthetic@redis.example:6379", "", "", "", ""))

    def test_certificate_failure_closes_socket_without_auth_or_fallback(self) -> None:
        """A rejected certificate must abort before Redis credentials are sent."""
        probe = isolated_probe()
        raw = Mock()
        context = Mock()
        context.wrap_socket.side_effect = ssl.SSLCertVerificationError("untrusted test certificate")
        with patch.object(socket, "create_connection", return_value=raw) as connect, \
                patch.object(ssl, "create_default_context", return_value=context), \
                patch.object(probe, "_tls_auto_insecure", return_value=True), \
                patch.object(probe, "_read_resp") as read:
            with self.assertRaises(ssl.SSLCertVerificationError):
                probe._ping_once(self.probe_url())
        connect.assert_called_once()
        context.wrap_socket.assert_called_once_with(raw, server_hostname="redis.example")
        raw.sendall.assert_not_called()
        read.assert_not_called()
        raw.close.assert_called_once()

    def test_verified_tls_authenticates_and_pings_then_closes_both_sockets(self) -> None:
        """Successful TLS keeps Redis AUTH/PING behavior and socket cleanup."""
        probe = isolated_probe()
        raw, wrapped, context = Mock(), Mock(), Mock()
        context.wrap_socket.return_value = wrapped
        with patch.object(socket, "create_connection", return_value=raw), \
                patch.object(ssl, "create_default_context", return_value=context), \
                patch.object(probe, "_read_resp", side_effect=["OK", "PONG"]):
            self.assertEqual(probe._ping_once(self.probe_url()), "PONG")
        context.wrap_socket.assert_called_once_with(raw, server_hostname="redis.example")
        self.assertEqual(wrapped.sendall.call_count, 2)
        raw.sendall.assert_not_called()
        wrapped.close.assert_called_once()
        raw.close.assert_called_once()

    def test_default_context_requires_valid_certificate_and_hostname(self) -> None:
        """Use the standard trust store, required verification and hostname checks."""
        context = ssl.create_default_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__ == "__main__":
    unittest.main()
