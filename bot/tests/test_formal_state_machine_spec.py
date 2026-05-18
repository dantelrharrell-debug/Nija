"""Tests for the formal state-machine specification contract."""

from __future__ import annotations

import json
import unittest

from bot.bootstrap_state_machine import BootstrapState, _VALID_TRANSITIONS as BOOTSTRAP_VALID_TRANSITIONS
from bot.capital_flow_state_machine import (
    CapitalBootstrapStateMachine,
    CapitalRuntimeStateMachine,
)
from bot.execution_state_controller import ExecutionOrderState
from bot.formal_state_machine_spec import get_formal_state_machine_spec
from bot.nonce_fsm import _State as NonceState
from bot.nonce_fsm import _TRANSITIONS as NONCE_VALID_TRANSITIONS
from bot.startup_coordinator import StartupCoordinatorState
from bot.trading_state_machine import ExecutionProgressState, TradingState, TradingStateMachine


class TestFormalStateMachineSpec(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = get_formal_state_machine_spec()

    def test_spec_is_json_serializable(self) -> None:
        payload = self.spec.as_dict()
        rendered = json.dumps(payload, sort_keys=True)
        self.assertIn("startup_coordinator", rendered)
        self.assertIn("execution_state_controller", rendered)

    def test_trading_spec_matches_runtime_transition_table(self) -> None:
        machine = self.spec.machine("trading_state_machine")
        self.assertEqual(machine.initial_state, TradingState.OFF.value)
        self.assertEqual(set(machine.states), {state.value for state in TradingState})
        self.assertEqual(
            {src: set(dsts) for src, dsts in machine.transition_map().items()},
            {
                state.value: {target.value for target in targets}
                for state, targets in TradingStateMachine.VALID_TRANSITIONS.items()
            },
        )

    def test_bootstrap_spec_matches_runtime_transition_table(self) -> None:
        machine = self.spec.machine("bootstrap_state_machine")
        self.assertEqual(set(machine.states), {state.value for state in BootstrapState})
        self.assertEqual(
            {src: set(dsts) for src, dsts in machine.transition_map().items()},
            {
                state.value: {target.value for target in targets}
                for state, targets in BOOTSTRAP_VALID_TRANSITIONS.items()
            },
        )

    def test_capital_specs_match_runtime_transition_tables(self) -> None:
        bootstrap_machine = self.spec.machine("capital_bootstrap_state_machine")
        runtime_machine = self.spec.machine("capital_runtime_state_machine")
        self.assertEqual(
            {src: set(dsts) for src, dsts in bootstrap_machine.transition_map().items()},
            {
                state.value: {target.value for target in targets}
                for state, targets in CapitalBootstrapStateMachine._VALID_TRANSITIONS.items()
            },
        )
        self.assertEqual(
            {src: set(dsts) for src, dsts in runtime_machine.transition_map().items()},
            {
                state.value: {target.value for target in targets}
                for state, targets in CapitalRuntimeStateMachine._VALID_TRANSITIONS.items()
            },
        )

    def test_nonce_spec_matches_runtime_transition_table(self) -> None:
        machine = self.spec.machine("nonce_fsm")
        self.assertEqual(set(machine.states), {state.value for state in NonceState})
        self.assertEqual(
            {src: set(dsts) for src, dsts in machine.transition_map().items()},
            {
                state.value: {target.value for target in targets}
                for state, targets in NONCE_VALID_TRANSITIONS.items()
            },
        )

    def test_startup_and_execution_specs_cover_current_runtime_states(self) -> None:
        startup_machine = self.spec.machine("startup_coordinator")
        authority_machine = self.spec.machine("execution_authority_convergence")
        controller_machine = self.spec.machine("execution_state_controller")

        self.assertEqual(set(startup_machine.states), {state.value for state in StartupCoordinatorState})
        self.assertEqual(set(authority_machine.states), {state.value for state in ExecutionProgressState})
        self.assertEqual(set(controller_machine.states), {state.value for state in ExecutionOrderState})
        self.assertIn(
            ("ACTIVATION_CONVERGING", "DISPATCH_ENABLED"),
            {(edge.source, edge.target) for edge in startup_machine.transitions},
        )
        self.assertIn(
            ("CONVERGING", "AUTHORIZED"),
            {(edge.source, edge.target) for edge in authority_machine.transitions},
        )
        self.assertIn(
            ("SUBMITTING", "HALTED_AUTH"),
            {(edge.source, edge.target) for edge in controller_machine.transitions},
        )

    def test_cross_machine_invariants_include_order_dispatch_contract(self) -> None:
        cross_rules = {rule.rule_id: rule.expression for rule in self.spec.cross_machine_invariants}
        self.assertIn("X1", cross_rules)
        self.assertIn("LIVE_ACTIVE", cross_rules["X1"])
        self.assertIn("DISPATCH_ENABLED", cross_rules["X1"])
        self.assertIn("X9", cross_rules)


if __name__ == "__main__":
    unittest.main()
