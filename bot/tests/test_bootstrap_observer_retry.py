"""Regression coverage for bootstrap observer retry handling."""

from __future__ import annotations

import ast
import os
import types
import unittest
from pathlib import Path


class _FakeLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, tuple[object, ...]]] = []

    def critical(self, message: str, *args: object) -> None:
        self.records.append(("critical", (message, *args)))

    def error(self, message: str, *args: object) -> None:
        self.records.append(("error", (message, *args)))

    def warning(self, message: str, *args: object) -> None:
        self.records.append(("warning", (message, *args)))


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _load_wait_for_bootstrap_observer_ready():
    bot_path = Path(__file__).resolve().parents[2] / "bot.py"
    source = bot_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(bot_path))
    fn_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_wait_for_bootstrap_observer_ready"
    )
    module = ast.Module(body=[fn_node], type_ignores=[])
    ast.fix_missing_locations(module)

    fake_logger = _FakeLogger()
    fake_time = _FakeTime()
    state = {"values": ["RUNNING_SUPERVISED"]}

    namespace = {
        "os": os,
        "time": fake_time,
        "logger": fake_logger,
        "_BOOTSTRAP_OBSERVER_TIMEOUT_S": 5.0,
        "_BOOTSTRAP_OBSERVER_POLL_INTERVAL_S": 0.1,
        "_bootstrap_state_value": lambda: state["values"].pop(0) if len(state["values"]) > 1 else state["values"][0],
    }
    exec(compile(module, str(bot_path), "exec"), namespace)
    return types.SimpleNamespace(
        fn=namespace["_wait_for_bootstrap_observer_ready"],
        logger=fake_logger,
        time=fake_time,
        state=state,
    )


class TestBootstrapObserverRetry(unittest.TestCase):
    def test_boot_failed_retry_keeps_waiting_for_recovery(self):
        harness = _load_wait_for_bootstrap_observer_ready()
        harness.state["values"] = [
            "BOOT_FAILED_RETRY",
            "PLATFORM_CONNECTING",
            "RUNNING_SUPERVISED",
        ]

        ok, state = harness.fn(context="unit-test")

        self.assertTrue(ok)
        self.assertEqual(state, "RUNNING_SUPERVISED")
        self.assertTrue(
            any(level == "warning" and "BOOTSTRAP_OBSERVER_RETRYING" in record[0] for level, record in harness.logger.records)
        )
        self.assertFalse(
            any(level == "error" and "BOOTSTRAP_OBSERVER_BLOCKED" in record[0] for level, record in harness.logger.records)
        )

    def test_terminal_states_still_abort_startup(self):
        harness = _load_wait_for_bootstrap_observer_ready()
        harness.state["values"] = ["EXTERNAL_RESTART_REQUIRED"]

        ok, state = harness.fn(context="unit-test")

        self.assertFalse(ok)
        self.assertEqual(state, "EXTERNAL_RESTART_REQUIRED")


if __name__ == "__main__":
    unittest.main()
