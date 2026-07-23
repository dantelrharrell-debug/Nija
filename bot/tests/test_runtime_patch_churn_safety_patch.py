from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load_module():
    path = Path(__file__).resolve().parents[1] / "runtime_patch_churn_safety_patch.py"
    spec = importlib.util.spec_from_file_location(
        "runtime_patch_churn_safety_patch_test_target", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chain_marker_found_through_competing_wrapper_closure() -> None:
    module = _load_module()

    def base() -> bool:
        return True

    setattr(base, "_nija_marker", True)

    def competing() -> bool:
        return base()

    assert module._chain_has_attr(competing, "_nija_marker") is True


def test_writer_authority_requires_complete_lineage(monkeypatch) -> None:
    module = _load_module()
    for name in (
        "NIJA_WRITER_FENCING_TOKEN",
        "NIJA_WRITER_LEASE_GENERATION",
        "NIJA_WRITER_LEASE_ACQUIRED",
        "NIJA_LOCK_ACQUIRED",
        "NIJA_WRITER_HEARTBEAT_ACTIVE",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    assert module._strict_writer_authority_ready() is False

    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    assert module._strict_writer_authority_ready() is True


def test_kill_switch_probe_fails_closed(monkeypatch) -> None:
    module = _load_module()

    def broken_import(_name: str):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(module.importlib, "import_module", broken_import)
    assert module._strict_kill_switch_clear() is False


def test_capital_gate_requires_fresh_broker_backed_capital(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    authority = SimpleNamespace(
        is_hydrated=True,
        real_capital=225.0,
        usable_capital=200.0,
        valid_broker_count=1,
        is_fresh=lambda ttl_s=180.0: True,
    )
    capital_module = SimpleNamespace(get_capital_authority=lambda: authority)
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: capital_module)
    assert module._strict_capital_ready() is True

    authority.valid_broker_count = 0
    assert module._strict_capital_ready() is False


def test_chain_guard_prevents_alternating_rewrap() -> None:
    module = _load_module()
    target = ModuleType("target")

    class TradingStateMachine:
        def can_dispatch_trades(self) -> bool:
            return False

    target.TradingStateMachine = TradingStateMachine
    calls: list[str] = []
    patch_module = ModuleType("patch_module")
    patch_module._PATCHED = False

    def installer(target_module: ModuleType) -> bool:
        calls.append("wrapped")
        current = target_module.TradingStateMachine.can_dispatch_trades

        def wrapped(self) -> bool:
            return current(self)

        setattr(wrapped, "_nija_target_marker", True)
        target_module.TradingStateMachine.can_dispatch_trades = wrapped
        patch_module._PATCHED = True
        return True

    patch_module._install_on_module = installer
    assert module._guard_module_installer(
        patch_module,
        installer_name="_install_on_module",
        class_name="TradingStateMachine",
        method_name="can_dispatch_trades",
        marker_attr="_nija_target_marker",
        patched_flag="_PATCHED",
    ) is True

    assert patch_module._install_on_module(target) is True
    previous = target.TradingStateMachine.can_dispatch_trades

    def competitor(self) -> bool:
        return previous(self)

    target.TradingStateMachine.can_dispatch_trades = competitor
    assert patch_module._install_on_module(target) is True
    assert calls == ["wrapped"]


def test_exact_duplicate_filter_preserves_state_changes() -> None:
    module = _load_module()
    log_filter = module._ExactDuplicateInstallFilter()

    first = logging.LogRecord(
        name="nija.kraken_execution_floor_guard",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="KRAKEN_EXECUTION_FLOOR_ENV_NORMALIZED final_floor=$23.00",
        args=(),
        exc_info=None,
    )
    same = logging.LogRecord(
        name=first.name,
        level=first.levelno,
        pathname=__file__,
        lineno=2,
        msg=first.msg,
        args=(),
        exc_info=None,
    )
    changed = logging.LogRecord(
        name=first.name,
        level=first.levelno,
        pathname=__file__,
        lineno=3,
        msg="KRAKEN_EXECUTION_FLOOR_ENV_NORMALIZED final_floor=$24.00",
        args=(),
        exc_info=None,
    )

    assert log_filter.filter(first) is True
    assert log_filter.filter(same) is False
    assert log_filter.filter(changed) is True
