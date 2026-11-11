"""Real filesystem failure tests; no bot startup, exchange or credentials."""
from __future__ import annotations

import ast
from datetime import datetime
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FRAGMENTS = {'data/alpha_validation/alpha_validation_20260218_141638.json': b'{\n  "status": "statistical_fail",\n  "step1_passed": ', 'data/stability_analysis/stability_analysis_20260215_010835.json': b'{\n  "timestamp": "2026-02-15T01:08:35.166063",\n  "stability": {\n    "is_stable": false,\n    "stability_score": 0.8,\n    "confidence_level": 0.95\n  },\n  "tests": {\n    "ks_test": '}
SPEC = importlib.util.spec_from_file_location("analysis_report_json_under_test", ROOT / "bot/report_json.py")
REPORT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT_MODULE)
write_report_json = REPORT_MODULE.write_report_json


def load_writer(filename: str, method: str):
    """Exercise the exact production method without importing its runtime graph."""
    tree = ast.parse((ROOT / filename).read_text())
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == method)
    scope = {"Path": Path, "datetime": datetime, "json": json,
             "write_report_json": write_report_json, "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), scope)
    return scope[method]


class ReportIntegrityTests(unittest.TestCase):
    def test_complete_finite_report_round_trips_without_value_changes(self):
        payload = {"ready": False, "metrics": [0, -1.25, 3], "notes": "educational analysis"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_report_json(path, payload)
            self.assertEqual(json.loads(path.read_text()), payload)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_serialization_failure_preserves_existing_bytes(self):
        for bad in (object(), float("nan"), float("inf"), -float("inf")):
            with self.subTest(kind=type(bad).__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "report.json"
                original = b'{"ready": false}\n'
                path.write_bytes(original)
                with self.assertRaises((TypeError, ValueError)):
                    write_report_json(path, {"metric": bad})
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_invalid_first_report_creates_no_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with self.assertRaises(TypeError):
                write_report_json(path, {"metric": object()})
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_replace_failure_preserves_previous_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text('{"ready": false}\n')
            with patch.object(REPORT_MODULE.os, "replace", side_effect=OSError("fixture failure")):
                with self.assertRaises(OSError):
                    write_report_json(path, {"ready": False, "metric": 12})
            self.assertEqual(path.read_text(), '{"ready": false}\n')
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_flush_failure_never_replaces_previous_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text('{"ready": false}\n')
            with patch.object(REPORT_MODULE.os, "fsync", side_effect=OSError("fixture failure")):
                with self.assertRaises(OSError):
                    write_report_json(path, {"ready": True})
            self.assertEqual(path.read_text(), '{"ready": false}\n')
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_alpha_writer_uses_strict_persistence(self):
        method = load_writer("bot/alpha_validation_framework.py", "_save_result")
        with tempfile.TemporaryDirectory() as directory:
            result = SimpleNamespace(validation_timestamp=datetime(2026, 1, 1),
                                     to_dict=lambda: {"ready_for_capital_scaling": False})
            method(SimpleNamespace(results_dir=Path(directory)), result)
            path = next(Path(directory).glob("*.json"))
            before = path.read_bytes()
            result.to_dict = lambda: {"metric": object()}
            with self.assertRaises(TypeError):
                method(SimpleNamespace(results_dir=Path(directory)), result)
            self.assertEqual(path.read_bytes(), before)

    def test_stability_writer_uses_strict_persistence(self):
        method = load_writer("bot/trade_distribution_stability.py", "export_results")
        result = SimpleNamespace(timestamp="fixture", is_stable=False, stability_score=0.2,
                                 confidence_level=0.95, mean_return_change_pct=0,
                                 volatility_change_pct=0, win_rate_change_pct=0,
                                 warnings=[], recommendations=[])
        for name in ("ks_test", "chi_square_test", "t_test", "variance_test"):
            setattr(result, name, SimpleNamespace(is_stable=False))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(method(None, result, directory))
            before = path.read_bytes()
            result.mean_return_change_pct = float("inf")
            with self.assertRaises(ValueError):
                method(None, result, directory)
            self.assertEqual(path.read_bytes(), before)

    def test_historical_fragments_remain_exact_and_uncertifiable(self):
        for path in ("data/alpha_validation/alpha_validation_20260218_141638.json",
                     "data/stability_analysis/stability_analysis_20260215_010835.json"):
            with self.subTest(path=path):
                record = json.loads((ROOT / path).read_text())
                original = EXPECTED_FRAGMENTS[path]
                restored = record["original_fragment_utf8"].encode("utf-8")
                self.assertEqual(restored, original)
                self.assertEqual(record["original_fragment_bytes"], len(original))
                self.assertIs(record["valid_for_certification"], False)
                self.assertEqual(record["report_status"], "incomplete_historical_report")


if __name__ == "__main__":
    unittest.main()
