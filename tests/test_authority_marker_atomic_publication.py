"""Concurrent marker publication must not lose a writer's temporary file."""
import ast
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch


def load_writer():
    """Load the actual writer without installing production import hooks."""
    path = Path(__file__).resolve().parents[1] / 'bot/runtime_execution_capital_integrity_v169_patch.py'
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_atomic_json_write']
    env = dict(Path=Path, Any=Any, json=json, tempfile=tempfile)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), env)
    return env['_atomic_json_write']


class AuthorityMarkerPublicationTests(unittest.TestCase):
    def test_concurrent_writers_publish_complete_payloads_without_missing_temp_files(self):
        writer = load_writer()
        barrier = threading.Barrier(2)
        replace = Path.replace
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'authority_heartbeat.flag'
            payloads = [{'writer': i, 'stage': 'AUTH_VERIFY', 'proof_kind': 'authority_liveness'} for i in range(2)]
            def synchronized_publish(source, target):
                barrier.wait(timeout=5)
                return replace(source, target)
            with patch.object(Path, 'replace', synchronized_publish), ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(writer, path, value) for value in payloads]
                for future in futures:
                    future.result(timeout=10)
            self.assertIn(json.loads(path.read_text()), payloads)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_failed_publication_preserves_old_marker_and_propagates_error(self):
        writer = load_writer()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'authority_heartbeat.flag'
            path.write_text('previous-marker')
            with patch.object(Path, 'replace', side_effect=OSError('publication blocked')):
                with self.assertRaises(OSError):
                    writer(path, {'stage': 'AUTH_VERIFY'})
            self.assertEqual(path.read_text(), 'previous-marker')
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_serialization_failure_does_not_publish_or_leave_a_temp_file(self):
        writer = load_writer()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'authority_heartbeat.flag'
            with self.assertRaises(TypeError):
                writer(path, {'unserializable': object()})
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
