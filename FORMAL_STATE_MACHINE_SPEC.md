# Formal State Machine Spec

NIJA now keeps its runtime safety contract in a machine-readable spec at:

- `/home/runner/work/Nija/Nija/bot/formal_state_machine_spec.py`

That spec captures:

- transition graphs
- safety invariants
- temporal validity rules
- cross-machine coupling invariants

Covered machines:

1. TradingStateMachine
2. BootstrapStateMachine
3. StartupCoordinator
4. ExecutionAuthorityConvergenceFSM
5. CapitalBootstrapStateMachine
6. CapitalRuntimeStateMachine
7. NonceFSM
8. ExecutionStateController

Validation lives in:

- `/home/runner/work/Nija/Nija/bot/tests/test_formal_state_machine_spec.py`

Use this spec as the canonical source when adding new states, transitions, or
runtime safety gates. Any implementation change should keep the spec and tests
in sync so illegal behavior becomes structurally detectable instead of relying
on ad hoc bug-fix iterations.
