import ast
import unittest
from pathlib import Path


class TestStartupBlockers(unittest.TestCase):
    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _bot_source(self) -> str:
        return (self._repo_root() / "bot.py").read_text(encoding="utf-8")

    def _bot_tree(self) -> ast.AST:
        return ast.parse(self._bot_source(), filename=str(self._repo_root() / "bot.py"))

    def test_trading_strategy_initializes_market_readiness_gate(self):
        strategy_path = self._repo_root() / "bot" / "trading_strategy.py"
        source = strategy_path.read_text(encoding="utf-8")
        self.assertIn("self.market_readiness_gate: Optional[Any] = None", source)
        self.assertIn("self.market_readiness_gate = MarketReadinessGate()", source)

    def test_startup_market_probe_is_non_blocking(self):
        source = self._bot_source()
        self.assertNotIn(
            'raise RuntimeError("Startup verification failed: MarketReadinessGate not initialized.")',
            source,
        )
        self.assertNotIn(
            'raise RuntimeError(f"Startup verification failed: market readiness gate probe error: {_gate_err}")',
            source,
        )
        self.assertNotIn(
            'raise RuntimeError(\n            f"Startup verification failed: relaxed market gate probe returned IDLE',
            source,
        )

    def test_state_machine_loop_start_is_not_hydration_blocked(self):
        tree = self._bot_tree()
        target = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_ensure_state_machine_loop_started"
        )

        hydration_blockers = []
        for node in ast.walk(target):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Call)
                and isinstance(test.operand.func, ast.Name)
                and test.operand.func.id == "_is_balance_hydrated_ready"
            ):
                continue
            if any(isinstance(child, ast.Return) for child in node.body):
                hydration_blockers.append(node.lineno)

        self.assertEqual(
            hydration_blockers,
            [],
            "_ensure_state_machine_loop_started must not return early while balance hydration is pending",
        )


if __name__ == "__main__":
    unittest.main()
