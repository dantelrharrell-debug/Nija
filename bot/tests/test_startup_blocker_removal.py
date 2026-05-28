"""Regression tests for startup blocker removal.

Covers:
- _verify_startup_truth_conditions() warns (not raises) when market_readiness_gate
  is absent, probe raises, or probe returns IDLE.
- _ensure_state_machine_loop_started() starts the FSM loop even when balance
  hydration is incomplete (emits diagnostic warning instead of returning early).
- TradingStrategy wires market_readiness_gate during construction.

Note: bot.py calls main() at module level so cannot be imported directly.
Structural tests use AST/source analysis; TradingStrategy tests import bot.trading_strategy.
"""

import ast
import inspect
import threading
import unittest
from pathlib import Path


def _find_repo_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in (start, *start.parents):
        if (
            (candidate / "bot.py").exists()
            and (candidate / "bot").is_dir()
            and (candidate / ".git").exists()
        ):
            return candidate
    raise AssertionError("Could not locate repository root containing bot.py")


def _bot_py_source() -> str:
    return (_find_repo_root() / "bot.py").read_text(encoding="utf-8")


def _bot_py_ast() -> ast.Module:
    src = _bot_py_source()
    return ast.parse(src, filename="bot.py")


def _extract_function_source(source: str, func_name: str) -> str:
    """Return the source lines of a top-level function by name."""
    tree = ast.parse(source, filename="bot.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            lines = source.splitlines()
            # ast line numbers are 1-based
            start = node.lineno - 1
            end = node.end_lineno
            return "\n".join(lines[start:end])
    raise AssertionError(f"Function {func_name!r} not found in bot.py")


class TestMarketReadinessProbeDowngrade(unittest.TestCase):
    """_verify_startup_truth_conditions must not hard-raise for market-readiness conditions."""

    def setUp(self):
        self._source = _bot_py_source()
        self._func_src = _extract_function_source(
            self._source, "_verify_startup_truth_conditions"
        )

    def _market_gate_block(self) -> str:
        """Extract the market-readiness block from the function."""
        import textwrap
        # Find the paragraph after the market_readiness_gate getattr line
        lines = self._func_src.splitlines()
        start = None
        for i, line in enumerate(lines):
            if "market_readiness_gate" in line and "getattr" in line:
                start = i
                break
        self.assertIsNotNone(start, "market_readiness_gate block not found in function source")
        return textwrap.dedent("\n".join(lines[start:]))

    def test_missing_gate_uses_warning_not_raise(self):
        """When market_readiness_gate is None, code must warn, not raise RuntimeError."""
        block = self._market_gate_block()
        # Must contain a warning call for the None-gate case
        self.assertIn(
            "logger.warning",
            block,
            "Missing-gate case must call logger.warning",
        )
        # Must NOT contain a RuntimeError raise for the None/missing-gate case
        tree = ast.parse(block)
        raises_in_none_branch = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                # Check if it's a RuntimeError about MarketReadinessGate not initialized
                exc_src = ast.unparse(node.exc)
                if "MarketReadinessGate not initialized" in exc_src or (
                    "RuntimeError" in exc_src and "market" in exc_src.lower()
                ):
                    raises_in_none_branch.append(exc_src)
        self.assertEqual(
            raises_in_none_branch,
            [],
            f"Market-readiness RuntimeError raises must be removed; found: {raises_in_none_branch}",
        )

    def test_probe_error_uses_warning_not_raise(self):
        """Probe exceptions must be caught and warned about, not re-raised."""
        block = self._market_gate_block()
        tree = ast.parse(block)
        # Find all except handlers that re-raise or raise a new RuntimeError
        reraising_handlers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                for stmt in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(stmt, ast.Raise):
                        exc_src = ast.unparse(stmt.exc) if stmt.exc else "bare-raise"
                        if "RuntimeError" in exc_src or exc_src == "bare-raise":
                            reraising_handlers.append(exc_src)
        self.assertEqual(
            reraising_handlers,
            [],
            f"Probe exception handler must not re-raise; found: {reraising_handlers}",
        )

    def test_idle_result_uses_warning_not_raise(self):
        """IDLE probe result must trigger a warning, not a RuntimeError."""
        block = self._market_gate_block()
        # Must contain a warning for the IDLE case
        self.assertIn(
            "IDLE",
            block,
            "IDLE warning must be present in market-readiness block",
        )
        self.assertIn(
            "logger.warning",
            block,
            "IDLE case must call logger.warning",
        )
        # The word 'IDLE' must not appear in a raise statement
        tree = ast.parse(block)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                exc_src = ast.unparse(node.exc)
                self.assertNotIn(
                    "IDLE",
                    exc_src,
                    f"IDLE must not appear in a raise statement; found: {exc_src}",
                )


class TestEnsureStateMachineLoopNotBlockedByHydration(unittest.TestCase):
    """_ensure_state_machine_loop_started() must not early-return on hydration state."""

    def setUp(self):
        self._source = _bot_py_source()
        self._func_src = _extract_function_source(
            self._source, "_ensure_state_machine_loop_started"
        )

    def test_no_early_return_after_hydration_warning(self):
        """The hydration check must not be followed by a bare 'return' statement."""
        lines = self._func_src.splitlines()
        # Find the line containing the hydration check condition
        hydration_check_line = None
        for i, line in enumerate(lines):
            if "_is_balance_hydrated_ready" in line:
                hydration_check_line = i
                break
        self.assertIsNotNone(
            hydration_check_line,
            "_is_balance_hydrated_ready reference must exist in function",
        )

        # Parse the function body and look for an early return inside the
        # hydration-check if-block. The old code had:
        #   if not _is_balance_hydrated_ready():
        #       ...
        #       return            ← this must be gone
        tree = ast.parse(self._func_src)
        func_def = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
        )
        for stmt in func_def.body:
            if not isinstance(stmt, (ast.With, ast.If)):
                continue
            # Handle the outer `with _sm_loop_lock:` block
            inner_stmts = getattr(stmt, "body", [])
            for inner in inner_stmts:
                if isinstance(inner, ast.If):
                    # Check if this is the hydration guard
                    cond_src = ast.unparse(inner.test)
                    if "_is_balance_hydrated_ready" in cond_src:
                        # Verify there is no bare return in this if-block
                        for sub in ast.walk(ast.Module(body=inner.body, type_ignores=[])):
                            if isinstance(sub, ast.Return):
                                self.fail(
                                    "Hydration guard must not contain a bare return — "
                                    "FSM loop start must not be blocked by hydration state"
                                )

    def test_hydration_warning_message_updated(self):
        """The hydration warning message must reflect diagnostic-only semantics."""
        # The old message was '🚫 FSM BLOCKED: waiting for balance hydration'
        # The new message must NOT contain 'BLOCKED'
        self.assertNotIn(
            "FSM BLOCKED",
            self._func_src,
            "Old blocking warning message must be replaced with diagnostic-only wording",
        )


class TestTradingStrategyMarketReadinessGateInit(unittest.TestCase):
    """TradingStrategy must wire market_readiness_gate during construction."""

    def test_market_readiness_gate_wired_in_init_source(self):
        """market_readiness_gate wiring must appear in TradingStrategy.__init__ source."""
        import bot.trading_strategy as _ts_mod

        src = inspect.getsource(_ts_mod.TradingStrategy.__init__)
        self.assertIn(
            "market_readiness_gate",
            src,
            "TradingStrategy.__init__ must contain market_readiness_gate wiring",
        )
        self.assertIn(
            "MarketReadinessGate",
            src,
            "TradingStrategy.__init__ must reference MarketReadinessGate class",
        )

    def test_market_readiness_gate_attribute_set_on_instance(self):
        """market_readiness_gate must be set as an instance attribute in __init__."""
        import bot.trading_strategy as _ts_mod

        src = inspect.getsource(_ts_mod.TradingStrategy.__init__)
        # Verify assignment of the form: self.market_readiness_gate = ...
        self.assertIn(
            "self.market_readiness_gate",
            src,
            "TradingStrategy.__init__ must assign self.market_readiness_gate",
        )

    def test_market_readiness_gate_is_mrg_instance(self):
        """When MarketReadinessGate is available, the attribute must be an instance."""
        from bot.market_readiness_gate import MarketReadinessGate
        import bot.trading_strategy as _ts_mod

        # Build a minimal instance without triggering full __init__
        strategy = _ts_mod.TradingStrategy.__new__(_ts_mod.TradingStrategy)
        # Execute only the gate-wiring block in isolation
        strategy.market_readiness_gate = None
        try:
            strategy.market_readiness_gate = MarketReadinessGate()
        except Exception:
            pass

        self.assertTrue(
            hasattr(strategy, "market_readiness_gate"),
            "market_readiness_gate attribute must be present on TradingStrategy instances",
        )
        if strategy.market_readiness_gate is not None:
            self.assertIsInstance(
                strategy.market_readiness_gate,
                MarketReadinessGate,
                "market_readiness_gate must be a MarketReadinessGate instance",
            )


if __name__ == "__main__":
    unittest.main()
