from __future__ import annotations

import inspect
import os
import threading
import time
import types

from bot import final_production_activation_repair_v60_patch as repair


def test_risk_compat_requires_canonical_risk_proof(monkeypatch):
    monkeypatch.delenv("NIJA_RISK_SYSTEM_READY", raising=False)
    repair._publish_risk_compat({"risk_ready": False})
    assert os.environ.get("NIJA_RISK_SYSTEM_READY") != "1"

    monkeypatch.setenv("NIJA_PRE_DISPATCH_RISK_SIZING_READY", "1")
    monkeypatch.setenv("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED", "1")
    monkeypatch.setenv("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED", "1")
    repair._publish_risk_compat({"risk_ready": True})
    assert os.environ["NIJA_RISK_SYSTEM_READY"] == "1"


def test_request_activation_is_single_flight_and_nonblocking(monkeypatch):
    release = threading.Event()
    entered = threading.Event()

    def blocked_worker(trigger: str) -> None:
        entered.set()
        release.wait(2.0)

    monkeypatch.setattr(repair, "_live_mode", lambda: True)
    monkeypatch.setattr(repair, "_activation_worker", blocked_worker)
    monkeypatch.setattr(repair, "_ACTIVATION_THREAD", None)
    monkeypatch.setattr(repair, "_ACTIVATION_STARTED_AT", 0.0)
    monkeypatch.setattr(repair, "_ACTIVATION_TRIGGER", "")

    assert repair.request_activation("first") is True
    assert entered.wait(0.5)
    started = time.monotonic()
    assert repair.request_activation("second") is False
    elapsed = time.monotonic() - started
    assert elapsed < 0.25
    release.set()
    worker = repair._ACTIVATION_THREAD
    if worker is not None:
        worker.join(timeout=1.0)


def test_capital_gate_is_observational_and_never_refreshes(monkeypatch):
    import bot.trading_state_machine as tsm

    class FakeCA:
        is_hydrated = True
        total_capital = 467.28

        def is_stale(self):
            return False

        def get_real_capital(self):
            return 467.28

        def refresh(self, *_args, **_kwargs):
            raise AssertionError("activation gate must never perform broker refresh")

    original_gate = tsm._capital_readiness_gate
    original_getter = tsm._get_capital_authority_instance
    try:
        monkeypatch.setattr(tsm, "_get_capital_authority_instance", lambda: FakeCA())
        assert repair._patch_capital_readiness_observer() is True
        ok, detail = tsm._capital_readiness_gate()
        assert ok is True
        assert detail == "ok"
    finally:
        tsm._capital_readiness_gate = original_gate
        tsm._get_capital_authority_instance = original_getter


def test_strict_runtime_ready_requires_every_readiness_proof(monkeypatch):
    fake_table = types.SimpleNamespace(snapshot=lambda: {
        "balance_hydrated": True,
        "capital_ready": True,
        "risk_ready": False,
        "strategy_ready": True,
        "execution_ready": True,
        "nonce_ready": True,
        "authority_ready": True,
        "bootstrap_ready": True,
    })
    real_import = repair.importlib.import_module

    class Core:
        def is_alive(self):
            return True

    runtime = types.SimpleNamespace(acquired=True, lost=False)

    def fake_import(name: str):
        if name == "bot.readiness_table":
            return fake_table
        if name == "bot.trading_state_machine":
            sm = types.SimpleNamespace(
                get_current_state=lambda: "LIVE_ACTIVE",
                get_activation_committed=lambda: True,
                can_execute=lambda: True,
            )
            return types.SimpleNamespace(get_state_machine=lambda: sm)
        return real_import(name)

    monkeypatch.setattr(repair.importlib, "import_module", fake_import)
    allowed, blockers = repair._strict_runtime_ready(runtime, Core())
    assert allowed is False
    assert "readiness.risk_ready" in blockers


def test_v60_source_has_no_force_activation_or_threshold_mutation():
    source = inspect.getsource(repair)
    forbidden = (
        "FORCE_TRADE =",
        "NIJA_FORCE_ACTIVATION =",
        "MIN_ENTRY_SCORE =",
        "MIN_TRADE_USD =",
        "MINIMUM_TRADING_BALANCE =",
    )
    for assignment in forbidden:
        assert assignment not in source


def test_v60_nonblocking_patches_do_not_commit_inline():
    v15_source = inspect.getsource(repair._patch_v15_nonblocking)
    v16_source = inspect.getsource(repair._patch_v16_nonblocking)
    bot_main_source = inspect.getsource(repair._patch_bot_main_nonblocking)
    for source in (v15_source, v16_source, bot_main_source):
        assert "commit_activation(" not in source
        assert "_commit_once(" not in source
        assert "request_activation(" in source


def test_execution_and_exit_repairs_are_explicitly_wired():
    source = inspect.getsource(repair._install_execution_and_exit_repairs)
    assert "bot.live_entry_completion_repair_patch" in source
    assert "bot.live_broker_profit_exit_convergence_v25" in source
    assert "bot.live_engine_profit_exit_convergence_v25" in source
    assert "bot.execution_pipeline_gate_repair_patch" in source
    assert "bot.trading_state_dispatch_latch_repair_patch" in source


def test_v60_is_last_canonical_fast_path_installer():
    bot_path = os.path.join(os.path.dirname(__file__), "..", "bot.py")
    source = open(bot_path, encoding="utf-8").read()
    v59 = source.index("bot.final_production_activation_repair_v59_patch")
    v60 = source.index("bot.final_production_activation_repair_v60_patch")
    end = source.index("_FAST_PATH_COMPAT_OPTIONAL_GUARDS")
    assert v59 < v60 < end
