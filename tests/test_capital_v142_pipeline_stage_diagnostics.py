"""Offline, diagnostics-only regression for capital worker stage breadcrumbs.

Never contacts brokers, publishes capital, modifies runtime settings, or enables orders.
"""
from __future__ import annotations

import ast
from pathlib import Path
import threading
from types import SimpleNamespace

import bot.capital_publication_liveness_v142_patch as v142


ROOT = Path(__file__).resolve().parents[1]


def _blocked_thread(target):
    entered = threading.Event()
    release = threading.Event()

    def unrelated_waiting_function():
        entered.set()
        assert release.wait(timeout=3)
        target()

    worker = threading.Thread(target=unrelated_waiting_function, daemon=True)
    worker.start()
    assert entered.wait(timeout=2)
    return worker, release


def test_unknown_stack_uses_only_own_coordinator_allowlisted_stage():
    worker, release = _blocked_thread(lambda: None)
    try:
        coordinator = SimpleNamespace(
            _nija_v142_flight_thread=worker,
            _nija_v142_pipeline_stage="event_dispatch",
        )
        assert v142._timeout_worker_stage_hint_v142(worker) == "unknown"
        assert v142._timeout_worker_stage_hint_v142(worker, coordinator) == "event_dispatch"

        # Never emit arbitrary values even if an unexpected code path sets one.
        coordinator._nija_v142_pipeline_stage = "untrusted_value"
        assert v142._timeout_worker_stage_hint_v142(worker, coordinator) == "unknown"
        coordinator._nija_v142_pipeline_stage = 42
        assert v142._timeout_worker_stage_hint_v142(worker, coordinator) == "unknown"

        # Another worker's stage must not be attributed to this worker.
        coordinator._nija_v142_pipeline_stage = "publish"
        coordinator._nija_v142_flight_thread = object()
        assert v142._timeout_worker_stage_hint_v142(worker, coordinator) == "unknown"
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()


def test_recognized_stack_function_takes_priority_over_stage_breadcrumb():
    entered = threading.Event()
    release = threading.Event()

    def get_account_balance():
        entered.set()
        assert release.wait(timeout=3)

    worker = threading.Thread(target=get_account_balance, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=2)
        coordinator = SimpleNamespace(
            _nija_v142_flight_thread=worker,
            _nija_v142_pipeline_stage="event_dispatch",
        )
        assert v142._timeout_worker_stage_hint_v142(worker, coordinator) == "broker_balance_fetch"
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()


def test_pipeline_records_fixed_stage_sequence_without_new_authority_reads():
    path = ROOT / "bot" / "capital_flow_state_machine.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "CapitalRefreshCoordinator")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_pipeline")
    assigned_stages = [
        node.value.value
        for node in ast.walk(method)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Attribute)
                and target.attr == "_nija_v142_pipeline_stage"
                for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    assert assigned_stages == [
        "refresh_start", "broker_balance_fetch", "normalize", "valuate",
        "confidence", "publish", "runtime_fsm", "event_dispatch",
        "bootstrap_fsm", "complete",
    ]
    assert set(assigned_stages) <= v142._CAPITAL_TIMEOUT_SAFE_STAGES_V142
