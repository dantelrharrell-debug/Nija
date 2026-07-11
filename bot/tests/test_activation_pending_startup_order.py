from __future__ import annotations

import ast
import importlib
import logging
import sys
import threading
from pathlib import Path


def test_activation_monitor_has_no_synchronous_startup_repair_install() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (
        root / "bot" / "activation_pending_commit_monitor_patch.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    top_level_calls: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        if isinstance(fn, ast.Name):
            top_level_calls.append(fn.id)

    assert "_install_startup_execution_repairs" not in top_level_calls
    assert "ensure_startup_execution_repairs_ready" in source
    assert "synchronous_imports=false" in source


def test_activation_monitor_observes_runtime_without_importing_it(monkeypatch) -> None:
    module = importlib.import_module("bot.activation_pending_commit_monitor_patch")

    for name in (
        "bot.trading_state_machine",
        "trading_state_machine",
        "bot.capital_authority",
        "capital_authority",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)

    calls: list[str] = []

    def forbidden_import(name: str):
        calls.append(name)
        raise AssertionError(f"unexpected eager runtime import: {name}")

    monkeypatch.setattr(module.importlib, "import_module", forbidden_import)

    assert module._state_machine() is None
    ready, detail = module._capital_ready_snapshot()
    assert ready is False
    assert detail["reason"] == "capital_authority_unavailable"
    assert calls == []


def test_duplicate_okx_late_bind_logs_are_throttled() -> None:
    module = importlib.import_module("bot.activation_pending_commit_monitor_patch")
    log_filter = module._VenueBindDuplicateFilter()

    record = logging.LogRecord(
        name="nija.venue_readiness_execution_repair",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="OKX_LATE_BIND_COMPLETE marker=20260710ae router_patched=False order_classes=['x']",
        args=(),
        exc_info=None,
    )

    assert log_filter.filter(record) is True
    assert log_filter.filter(record) is False

    other = logging.LogRecord(
        name="nija.venue_readiness_execution_repair",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="VENUE_READINESS_REPAIR_STATE marker=20260710ae capital=False scan=False okx=True",
        args=(),
        exc_info=None,
    )
    assert log_filter.filter(other) is True


def test_startup_repairs_wait_for_broker_manager(monkeypatch) -> None:
    module = importlib.import_module("bot.activation_pending_commit_monitor_patch")
    ready_event = threading.Event()

    monkeypatch.setattr(module, "_STARTUP_REPAIRS_READY", ready_event)
    monkeypatch.setattr(module, "install_import_hook", lambda: None)
    monkeypatch.setattr(module, "_broker_manager_module_loaded", lambda: False)

    called: list[bool] = []
    monkeypatch.setattr(
        module,
        "_install_startup_execution_repairs",
        lambda: called.append(True) or True,
    )

    assert module.ensure_startup_execution_repairs_ready(timeout_s=0.0) is False
    assert called == []
