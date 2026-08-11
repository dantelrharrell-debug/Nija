from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, MAIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_canonical_fast_path_skips_legacy_main_fanout(monkeypatch) -> None:
    legacy_imports = {
        "bot.startup_runtime_safety",
        "bot.generation_sync_timing_patch",
        "bot.live_execution_authority_blocker_patch",
        "bot.current_capital_snapshot_freshness_repair_patch",
        "bot.live_broker_profit_exit_convergence_v25",
    }
    imported: list[str] = []
    handoff_calls: list[tuple[str, str | None]] = []
    original_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        imported.append(name)
        if name in legacy_imports:
            raise AssertionError(f"canonical pre-handoff must not import {name}")
        return original_import_module(name, package)

    def fake_run_module(
        mod_name: str,
        init_globals=None,
        run_name: str | None = None,
        alter_sys: bool = False,
    ):
        handoff_calls.append((mod_name, run_name))
        return {}

    monkeypatch.setenv("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH", "1")
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    monkeypatch.setenv("NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY", "1")
    monkeypatch.delenv("NIJA_MAIN_CANONICAL_PREHANDOFF_BOUNDED", raising=False)
    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    monkeypatch.setattr(runpy, "run_module", fake_run_module)

    module = _load("test_main_canonical_prehandoff_fast")

    assert module._canonical_fast_path_enabled() is True
    assert os.environ["NIJA_MAIN_CANONICAL_PREHANDOFF_BOUNDED"] == "1"
    assert handoff_calls == [("bot.bot", "__main__")]
    assert legacy_imports.isdisjoint(imported)


def test_legacy_preactivation_fanout_order_remains_supported(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH", "1")
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    monkeypatch.setenv("NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY", "1")
    monkeypatch.setattr(runpy, "run_module", lambda *args, **kwargs: {})
    module = _load("test_main_canonical_prehandoff_legacy")

    calls: list[str] = []
    ordered_steps = (
        "_install_global_runtime_startup_guards",
        "_install_preactivation_runtime_identity_guard_v36",
        "_install_logging_format_guard",
        "_install_runtime_auth_endpoint_repair",
        "_install_current_capital_snapshot_freshness_repair",
        "_install_authority_heartbeat_timeout_grace_repair",
        "_install_live_broker_profit_exit_v25",
        "_run_pre_startup_sanitization",
        "_install_strategy_publication",
        "_install_authority_readiness_repair",
        "_install_execution_bootstrap_authority_repair",
        "_install_forced_fallback_payload_repair",
        "_install_execution_pipeline_gate_repair",
        "_install_hard_controls_csm_repair",
        "_install_trading_state_dispatch_latch_repair",
        "_install_downstream_risk_governor_equity_repair",
        "_install_usdt_kraken_ecel_routing_repair",
        "_install_live_entry_completion_repair",
        "_normalize_runtime_startup_env",
        "_run_pre_startup_sanitization",
        "_install_generation_sync_timing_patch",
        "_install_live_execution_authority_blocker_patch",
    )

    for step in ordered_steps:
        monkeypatch.setattr(module, step, lambda step=step: calls.append(step))

    module._run_legacy_preactivation_fanout()

    assert calls == list(ordered_steps)
