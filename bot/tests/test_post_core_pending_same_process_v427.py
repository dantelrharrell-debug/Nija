from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def _load(relative_path: str, module_name: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_post_core_pending_waits_same_process_until_exact_proof(monkeypatch) -> None:
    module = _load("bot/bot_main.py", "nija_test_post_core_pending_v427")
    fake = ModuleType("bot.position_fetch_generation_v117_patch")
    calls = {"exact": 0, "request": 0, "clear": 0}

    def exact_ready(runtime, trading_thread):
        calls["exact"] += 1
        if calls["exact"] >= 3:
            return True, "canonical_execution_proof_complete"
        return False, "readiness_pending:execution_ready"

    fake._exact_execution_ready = exact_ready
    fake._writer_core_healthy = lambda runtime, trading_thread: True
    fake._shutdown_requested = lambda: False
    fake._bootstrap_state = lambda: "RUNNING_SUPERVISED"
    fake._request_normal_activation = lambda: calls.__setitem__(
        "request", calls["request"] + 1
    )
    fake._clear_start_gate_while_pending = lambda: calls.__setitem__(
        "clear", calls["clear"] + 1
    )

    monkeypatch.setitem(
        sys.modules, "bot.position_fetch_generation_v117_patch", fake
    )
    import bot

    monkeypatch.setattr(bot, "position_fetch_generation_v117_patch", fake, raising=False)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    ok = module._hold_recoverable_post_core_pending(
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert ok is True
    assert calls["exact"] >= 3
    assert calls["request"] >= 1
    assert calls["clear"] == 1
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_post_core_pending_keeps_true_writer_core_loss_fatal(monkeypatch) -> None:
    module = _load("bot/bot_main.py", "nija_test_post_core_pending_v427_fatal")
    fake = ModuleType("bot.position_fetch_generation_v117_patch")
    calls = {"request": 0}

    fake._exact_execution_ready = (
        lambda runtime, trading_thread: (False, "writer_or_core_not_healthy")
    )
    fake._writer_core_healthy = lambda runtime, trading_thread: False
    fake._shutdown_requested = lambda: False
    fake._bootstrap_state = lambda: "RUNNING_SUPERVISED"
    fake._request_normal_activation = lambda: calls.__setitem__(
        "request", calls["request"] + 1
    )
    fake._clear_start_gate_while_pending = lambda: None

    monkeypatch.setitem(
        sys.modules, "bot.position_fetch_generation_v117_patch", fake
    )
    import bot

    monkeypatch.setattr(bot, "position_fetch_generation_v117_patch", fake, raising=False)

    ok = module._hold_recoverable_post_core_pending(
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert ok is False
    assert calls["request"] == 0


def test_bot_main_uses_recoverable_hold_before_fatal_restart() -> None:
    source = (ROOT / "bot" / "bot_main.py").read_text(encoding="utf-8")
    convergence = source.index(
        "_convergence_ok = _perform_post_core_activation_convergence("
    )
    hold = source.index(
        "_convergence_ok = _hold_recoverable_post_core_pending(",
        convergence,
    )
    fatal = source.index(
        'raise RuntimeError(\n                    "Post-core activation convergence failed before dispatch enablement"',
        hold,
    )
    assert convergence < hold < fatal


def test_core_start_gate_hold_is_liveness_only_and_never_sets_ready() -> None:
    source = (ROOT / "bot" / "nija_core_loop.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_supervised_pending_start_gate_hold_allowed"
    )
    segment = ast.get_source_segment(source, target) or ""

    assert "RUNNING_SUPERVISED" in segment
    assert "LIVE_PENDING_CONFIRMATION" in segment
    assert "_exact_process_writer" in segment
    assert "NIJA_PROCESS_EXIT_REQUESTED" in segment
    assert "NIJA_RUNTIME_EXECUTION_AUTHORITY" not in segment
    assert "TRADING_ENGINE_READY.set" not in segment


def test_core_timeout_extends_only_on_proven_supervised_pending_state() -> None:
    source = (ROOT / "bot" / "nija_core_loop.py").read_text(encoding="utf-8")
    hold_call = source.index(
        "_hold_ok, _hold_reason = _supervised_pending_start_gate_hold_allowed()"
    )
    reset = source.index("_start_gate_t0 = time.monotonic()", hold_call)
    fail_closed = source.index(
        "trading worker remains fail-closed",
        reset,
    )
    assert hold_call < reset < fail_closed
