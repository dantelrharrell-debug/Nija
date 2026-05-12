import ast
import unittest
from pathlib import Path


class TestStartupReadinessOrder(unittest.TestCase):
    def _find_repo_root(self, start: Path) -> Path:
        for candidate in (start, *start.parents):
            if (
                (candidate / "bot.py").exists()
                and (candidate / "bot").is_dir()
                and (candidate / ".git").exists()
                and (candidate / "requirements.txt").exists()
            ):
                return candidate
        raise AssertionError("Could not locate repository root containing bot.py")

    def test_bootstrap_ready_before_barrier(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        bootstrap_ready_calls = []
        init_complete_transitions = []
        prethread_barriers = []

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_rt_mark_ready"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "bootstrap_ready"
            ):
                bootstrap_ready_calls.append(node)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_bfsm_transition"
                and node.args
                and isinstance(node.args[0], ast.Attribute)
                and isinstance(node.args[0].value, ast.Name)
                and node.args[0].value.id == "_BootstrapState"
                and node.args[0].attr == "INIT_COMPLETE"
            ):
                init_complete_transitions.append(node)
            elif (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)
                and isinstance(node.test.operand, ast.Call)
                and isinstance(node.test.operand.func, ast.Name)
                and node.test.operand.func.id == "_rt_is_ready"
                and any(isinstance(child, ast.Raise) for child in node.body)
            ):
                prethread_barriers.append(node)

        if len(bootstrap_ready_calls) != 1:
            self.fail("Expected exactly one bootstrap_ready mark in bot.py")
        if len(init_complete_transitions) != 1:
            self.fail("Expected exactly one INIT_COMPLETE transition in bot.py")
        if len(prethread_barriers) != 1:
            self.fail("Expected exactly one pre-thread readiness barrier in bot.py")
        self.assertGreater(
            bootstrap_ready_calls[0].lineno,
            init_complete_transitions[0].lineno,
            "bootstrap_ready must be marked after INIT_COMPLETE",
        )
        self.assertLess(
            bootstrap_ready_calls[0].lineno,
            prethread_barriers[0].lineno,
            "bootstrap_ready must be marked before the pre-thread readiness barrier",
        )


if __name__ == "__main__":
    unittest.main()
