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

    def test_execution_enablement_waits_for_running_supervised(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        startup_fn = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_run_bot_startup_and_trading":
                startup_fn = node
                break

        if startup_fn is None:
            self.fail("Expected _run_bot_startup_and_trading() in bot.py")

        running_supervised_calls = []
        execution_unlock_calls = []
        for node in ast.walk(startup_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_ensure_running_supervised":
                    running_supervised_calls.append(node)
                elif node.func.id == "_enable_execution_after_bootstrap_supervised":
                    execution_unlock_calls.append(node)

        if len(running_supervised_calls) != 1:
            self.fail("Expected exactly one _ensure_running_supervised() call in _run_bot_startup_and_trading")
        if len(execution_unlock_calls) != 1:
            self.fail(
                "Expected exactly one _enable_execution_after_bootstrap_supervised() call in "
                "_run_bot_startup_and_trading"
            )

        self.assertGreater(
            execution_unlock_calls[0].lineno,
            running_supervised_calls[0].lineno,
            "execution enablement must occur after the RUNNING_SUPERVISED handoff",
        )

        adjacent_pair_found = False
        for node in ast.walk(startup_fn):
            for field_name in ("body", "orelse", "finalbody"):
                statements = getattr(node, field_name, None)
                if not isinstance(statements, list):
                    continue
                for idx in range(len(statements) - 1):
                    first_stmt = statements[idx]
                    second_stmt = statements[idx + 1]
                    if not (
                        isinstance(first_stmt, ast.Expr)
                        and isinstance(first_stmt.value, ast.Call)
                        and isinstance(first_stmt.value.func, ast.Name)
                        and first_stmt.value.func.id == "_ensure_running_supervised"
                    ):
                        continue
                    if (
                        isinstance(second_stmt, ast.If)
                        and isinstance(second_stmt.test, ast.UnaryOp)
                        and isinstance(second_stmt.test.op, ast.Not)
                        and isinstance(second_stmt.test.operand, ast.Call)
                        and isinstance(second_stmt.test.operand.func, ast.Name)
                        and second_stmt.test.operand.func.id == "_enable_execution_after_bootstrap_supervised"
                    ):
                        adjacent_pair_found = True
                        break
                if adjacent_pair_found:
                    break

        self.assertTrue(
            adjacent_pair_found,
            "execution enablement must be checked in the immediately following statement after "
            "_ensure_running_supervised within the same control-flow block",
        )

    def test_transition_verification_occurs_after_execution_enablement(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        startup_fn = next(
            (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run_bot_startup_and_trading"),
            None,
        )
        if startup_fn is None:
            self.fail("Expected _run_bot_startup_and_trading() in bot.py")

        execution_unlock_calls = []
        transition_verify_calls = []
        for node in ast.walk(startup_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_enable_execution_after_bootstrap_supervised":
                    execution_unlock_calls.append(node)
                elif node.func.id == "_verify_runtime_transition_states":
                    transition_verify_calls.append(node)

        self.assertEqual(
            len(execution_unlock_calls),
            1,
            "Expected exactly one _enable_execution_after_bootstrap_supervised() call in _run_bot_startup_and_trading",
        )
        self.assertEqual(
            len(transition_verify_calls),
            1,
            "Expected exactly one _verify_runtime_transition_states() call in _run_bot_startup_and_trading",
        )
        self.assertGreater(
            transition_verify_calls[0].lineno,
            execution_unlock_calls[0].lineno,
            "_verify_runtime_transition_states must run after execution enablement",
        )

    def test_capital_ready_is_decoupled_from_execution_authority_guard(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        hydrate_fn = next(
            (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_hydrate_startup_balances"),
            None,
        )
        if hydrate_fn is None:
            self.fail("Expected _hydrate_startup_balances() in bot.py")

        authority_calls = []
        capital_ready_calls = []
        for node in ast.walk(hydrate_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_require_startup_execution_authority":
                    authority_calls.append(node)
                elif (
                    node.func.id == "_rt_mark_ready"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "capital_ready"
                ):
                    capital_ready_calls.append(node)

        self.assertEqual(
            len(authority_calls),
            0,
            "Capability flag capital_ready must not be gated by execution authority in _hydrate_startup_balances()",
        )
        self.assertGreaterEqual(len(capital_ready_calls), 1, "Expected CAPITAL_READY marks in _hydrate_startup_balances()")

    def test_strategy_readiness_is_decoupled_from_execution_authority_guard(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        publish_fn = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_publish_strategy_runtime_readiness"
            ),
            None,
        )
        if publish_fn is None:
            self.fail("Expected _publish_strategy_runtime_readiness() in bot.py")

        authority_calls = []
        strategy_ready_calls = []
        for node in ast.walk(publish_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_require_startup_execution_authority":
                    authority_calls.append(node)
                elif (
                    node.func.id == "_rt_mark_ready"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "strategy_ready"
                ):
                    strategy_ready_calls.append(node)

        self.assertEqual(
            len(authority_calls),
            0,
            "Capability flags in _publish_strategy_runtime_readiness() must not be blocked on authority guard",
        )
        self.assertEqual(
            len(strategy_ready_calls),
            1,
            "Expected exactly one strategy_ready mark in _publish_strategy_runtime_readiness()",
        )

    def test_execution_unlock_does_not_set_legacy_live_flags(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        unlock_fn = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_enable_execution_after_bootstrap_supervised"
            ),
            None,
        )
        if unlock_fn is None:
            self.fail("Expected _enable_execution_after_bootstrap_supervised() in bot.py")

        forbidden_live_flags = {
            "LIVE_CAPITAL_VERIFIED",
            "LIVE_TRADING",
            "ALLOW_EXECUTION",
            "BLOCK_EXECUTION",
            "DRY_RUN_MODE",
            "SUPERVISOR_MODE",
        }
        mutated_flags = set()

        for node in ast.walk(unlock_fn):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                if not (
                    isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "os"
                    and target.value.attr == "environ"
                ):
                    continue
                if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                    if target.slice.value in forbidden_live_flags:
                        mutated_flags.add(target.slice.value)

        self.assertEqual(
            mutated_flags,
            set(),
            f"_enable_execution_after_bootstrap_supervised must not mutate legacy live-mode flags: {sorted(mutated_flags)}",
        )

    def test_execution_unlock_promotes_capital_bootstrap_to_running_before_commit_loop(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        unlock_fn = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_enable_execution_after_bootstrap_supervised"
            ),
            None,
        )
        if unlock_fn is None:
            self.fail("Expected _enable_execution_after_bootstrap_supervised() in bot.py")

        running_transition_calls = []
        commit_activation_calls = []
        for node in ast.walk(unlock_fn):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "transition"
                and node.args
                and isinstance(node.args[0], ast.Attribute)
                and isinstance(node.args[0].value, ast.Name)
                and node.args[0].value.id == "_CapitalBootstrapState"
                and node.args[0].attr == "RUNNING"
            ):
                running_transition_calls.append(node)
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "commit_activation"
            ):
                commit_activation_calls.append(node)

        self.assertEqual(
            len(running_transition_calls),
            1,
            "Expected exactly one CapitalBootstrapFSM RUNNING transition in _enable_execution_after_bootstrap_supervised()",
        )
        self.assertGreaterEqual(
            len(commit_activation_calls),
            1,
            "Expected commit_activation retries inside _enable_execution_after_bootstrap_supervised()",
        )
        self.assertLess(
            running_transition_calls[0].lineno,
            commit_activation_calls[0].lineno,
            "CapitalBootstrapFSM must reach RUNNING before execution convergence retries begin",
        )

    def test_startup_pre_init_blocks_strict_observer_instances(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        startup_fn = next(
            (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run_bot_startup_and_trading"),
            None,
        )
        if startup_fn is None:
            self.fail("Expected _run_bot_startup_and_trading() in bot.py")

        authority_status_calls = [
            node for node in ast.walk(startup_fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_startup_execution_authority_status"
        ]
        self.assertGreaterEqual(
            len(authority_status_calls),
            1,
            "_run_bot_startup_and_trading must evaluate startup execution authority before write-capable init",
        )

        standby_runtime_error = False
        for node in ast.walk(startup_fn):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            if not (isinstance(node.exc.func, ast.Name) and node.exc.func.id == "RuntimeError"):
                continue
            if not node.exc.args:
                continue
            first_arg = node.exc.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                if "STARTUP_OBSERVER_STANDBY" in first_arg.value:
                    standby_runtime_error = True
                    break
            if isinstance(first_arg, ast.JoinedStr):
                text_parts = [
                    value.value for value in first_arg.values
                    if isinstance(value, ast.Constant) and isinstance(value.value, str)
                ]
                if any("STARTUP_OBSERVER_STANDBY" in part for part in text_parts):
                    standby_runtime_error = True
                    break

        self.assertTrue(
            standby_runtime_error,
            "_run_bot_startup_and_trading must fail closed with STARTUP_OBSERVER_STANDBY when strict authority is missing",
        )

    def test_strategy_fallback_requires_startup_authority_precheck(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        bot_path = repo_root / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(bot_path))

        fallback_fn = next(
            (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_ensure_strategy_fallback_published"),
            None,
        )
        if fallback_fn is None:
            self.fail("Expected _ensure_strategy_fallback_published() in bot.py")

        authority_call_lines = []
        trading_strategy_call_lines = []
        for node in ast.walk(fallback_fn):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "_startup_execution_authority_status":
                authority_call_lines.append(node.lineno)
            if isinstance(node.func, ast.Name) and node.func.id == "TradingStrategy":
                trading_strategy_call_lines.append(node.lineno)

        self.assertGreaterEqual(
            len(authority_call_lines),
            1,
            "_ensure_strategy_fallback_published must evaluate startup authority before fallback constructor",
        )
        self.assertEqual(
            len(trading_strategy_call_lines),
            1,
            "Expected exactly one TradingStrategy fallback constructor in _ensure_strategy_fallback_published",
        )
        self.assertLess(
            min(authority_call_lines),
            trading_strategy_call_lines[0],
            "Startup authority precheck must run before TradingStrategy fallback construction",
        )

    def test_kraken_connect_checks_writer_authority_before_nonce_manager_init(self):
        repo_root = self._find_repo_root(Path(__file__).resolve())
        broker_path = repo_root / "bot" / "broker_integration.py"
        source = broker_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(broker_path))

        kraken_class = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == "KrakenBrokerAdapter"
            ),
            None,
        )
        if kraken_class is None:
            self.fail("Expected KrakenBrokerAdapter in bot/broker_integration.py")

        connect_fn = next(
            (
                node
                for node in kraken_class.body
                if isinstance(node, ast.FunctionDef) and node.name == "connect"
            ),
            None,
        )
        if connect_fn is None:
            self.fail("Expected KrakenBrokerAdapter.connect() in bot/broker_integration.py")

        writer_guard_calls = []
        nonce_manager_calls = []
        for node in ast.walk(connect_fn):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "assert_startup_write_authority":
                writer_guard_calls.append(node.lineno)
            if isinstance(node.func, ast.Name) and node.func.id == "_get_distributed_nonce_manager":
                nonce_manager_calls.append(node.lineno)

        self.assertGreaterEqual(
            len(writer_guard_calls),
            1,
            "KrakenBrokerAdapter.connect() must verify startup write authority before nonce manager init",
        )
        self.assertEqual(
            len(nonce_manager_calls),
            1,
            "Expected exactly one _get_distributed_nonce_manager() call in KrakenBrokerAdapter.connect()",
        )
        self.assertLess(
            min(writer_guard_calls),
            nonce_manager_calls[0],
            "KrakenBrokerAdapter.connect() must check startup write authority before nonce manager initialization",
        )


if __name__ == "__main__":
    unittest.main()
