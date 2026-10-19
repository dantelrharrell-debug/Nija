"""Regression contract for canonical capital refresh single-writer semantics.

AST inspection deliberately avoids importing the trading engine or brokers.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "multi_account_broker_manager.py"


def _refresh_source():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    manager = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "MultiAccountBrokerManager")
    refresh = next(n for n in manager.body if isinstance(n, ast.FunctionDef)
                   and n.name == "refresh_capital_authority")
    return refresh, ast.unparse(refresh)


def _missing_coordinator_guard(refresh):
    """Match both conditions regardless of AST parentheses inserted by unparse."""
    return next(
        n for n in ast.walk(refresh) if isinstance(n, ast.If)
        and "self._capital_coordinator is not None" in ast.unparse(n.test)
        and "snapshot is None" in ast.unparse(n.test)
    )


class TestCanonicalCapitalRefreshSingleWriter(unittest.TestCase):
    def test_coordinator_null_snapshot_is_explicitly_fail_closed(self):
        _, source = _refresh_source()
        self.assertIn("self._capital_coordinator is not None", source)
        self.assertIn("snapshot is None", source)
        self.assertIn("'coordinator_snapshot_missing': 1.0", source)
        self.assertIn("self._capital_ready = False", source)

    def test_null_coordinator_snapshot_returns_before_legacy_authority_refresh(self):
        refresh, _ = _refresh_source()
        guard = _missing_coordinator_guard(refresh)
        self.assertTrue(any(isinstance(n, ast.Return) for n in guard.body))
        self.assertFalse(any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("refresh", "update")
            for node in guard.body for n in ast.walk(node)
        ))

    def test_legacy_fallback_not_used_on_coordinator_failure(self):
        refresh, source = _refresh_source()
        guard = _missing_coordinator_guard(refresh)
        first_return = next(n for n in ast.walk(guard) if isinstance(n, ast.Return))
        fallback = source.find("authority.refresh(")
        self.assertGreater(fallback, 0)
        self.assertLess(guard.lineno, next(
            n.lineno for n in ast.walk(refresh) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "refresh"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "authority"
        ))
        self.assertIsNotNone(first_return)

    def test_no_ready_or_nonzero_capital_claimed_from_missing_snapshot(self):
        refresh, _ = _refresh_source()
        guard = _missing_coordinator_guard(refresh)
        ret = next(n for n in guard.body if isinstance(n, ast.Return))
        output = ast.literal_eval(ret.value)
        self.assertEqual(output["ready"], 0.0)
        self.assertEqual(output["total_capital"], 0.0)
        self.assertEqual(output["valid_brokers"], 0.0)
        self.assertEqual(output["pending"], 1.0)


if __name__ == "__main__":
    unittest.main()
