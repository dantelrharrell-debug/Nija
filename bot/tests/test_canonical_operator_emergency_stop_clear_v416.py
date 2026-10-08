from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_canonical_launcher_invokes_existing_fail_closed_operator_clear(monkeypatch):
    launcher = _load("test_canonical_operator_clear_v416")
    calls = []

    fake = types.SimpleNamespace(run_once=lambda: calls.append("run_once") or 2)
    monkeypatch.setattr(
        launcher,
        "_canonical_import",
        lambda name: fake if name == "bot.operator_emergency_stop_clear_patch" else None,
    )

    cleared = launcher._run_operator_emergency_stop_clear_pre_runtime()

    assert cleared == 2
    assert calls == ["run_once"]


def test_operator_clear_runs_after_writer_bootstrap_before_runtime_provenance():
    source = LAUNCHER.read_text(encoding="utf-8")
    main_start = source.index("def main() -> int:")
    body = source[main_start:]
    writer = body.index("bot_entry, bot_main = _bootstrap_writer_first()")
    clear = body.index("_run_operator_emergency_stop_clear_pre_runtime()")
    provenance = body.index("_install_exchange_rejection_provenance_before_runtime()")
    runtime = body.index("_run_main_single_identity(bot_entry, bot_main)")

    assert writer < clear < provenance < runtime


def test_operator_clear_wrapper_does_not_grant_authority_or_force_activation():
    source = LAUNCHER.read_text(encoding="utf-8")
    start = source.index("def _run_operator_emergency_stop_clear_pre_runtime()")
    end = source.index("def main() -> int:", start)
    body = source[start:end]

    assert "NIJA_RUNTIME_EXECUTION_AUTHORITY" not in body
    assert "NIJA_FORCE_ACTIVATION" not in body
    assert "FORCE_TRADE" not in body
    assert "orders_submitted=false" in body
    assert "safety_gates_bypassed=false" in body
