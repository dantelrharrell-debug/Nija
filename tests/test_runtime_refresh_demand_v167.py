from __future__ import annotations

import importlib
import os
from types import SimpleNamespace


def _module():
    return importlib.import_module("bot.runtime_execution_convergence_v32")


def test_v167_marker_and_reconciliation_guard_present():
    module = _module()
    assert module.REFRESH_DEMAND_MARKER == "20260819-runtime-refresh-demand-v167"
    assert getattr(module._request_runtime_reconciliation, "_nija_runtime_refresh_demand_v167", False)


def test_routine_refresh_is_owned_by_v137(monkeypatch):
    module = _module()
    manager = SimpleNamespace(_nija_capital_publication_deadline_v137_started=True)
    monkeypatch.setenv("NIJA_CAPITAL_PUBLICATION_DEADLINE_V137_INSTALLED", "1")

    fake_v137 = SimpleNamespace(
        _publication_refresh_due=lambda *a, **k: (False, {}),
        _execute_deadline_refresh=lambda *a, **k: True,
    )
    real_import = module.importlib.import_module

    def fake_import(name: str):
        if name == "bot.capital_publication_deadline_v137_patch":
            return fake_v137
        return real_import(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import)
    assert module._routine_refresh_owned_by_v137(manager) is True


def test_startup_refresh_not_ready_without_registration(monkeypatch):
    module = _module()

    class Event:
        def is_set(self):
            return False

    manager = SimpleNamespace(_broker_registration_complete=Event(), _startup_lock_released=False)
    assert module._startup_runtime_refresh_ready(manager) is False


def test_monitor_interval_has_no_immediate_zero_tick(monkeypatch):
    module = _module()
    monkeypatch.setenv("NIJA_RUNTIME_CONVERGENCE_INTERVAL_S", "30")
    assert module._monitor_interval_seconds() == 30.0
    monkeypatch.setenv("NIJA_RUNTIME_CONVERGENCE_INTERVAL_S", "1")
    assert module._monitor_interval_seconds() == 10.0


def test_install_sets_v167_prebot_attestation(monkeypatch):
    module = _module()
    monkeypatch.delenv("NIJA_RUNTIME_REFRESH_DEMAND_V167_PREBOT_READY", raising=False)
    assert module.install_import_hook() is True
    assert os.environ["NIJA_RUNTIME_REFRESH_DEMAND_V167_PREBOT_READY"] == "1"


def test_v167_attestation_bounds_periodic_fallback(monkeypatch):
    patch = importlib.import_module("bot.runtime_refresh_demand_v167_patch")
    v166 = importlib.import_module("bot.runtime_capital_refresh_ownership_v166_patch")

    original = v166._is_proactive_trigger
    monkeypatch.setattr(v166, "_is_proactive_trigger", original)
    assert patch._patch_v166_periodic_fallback() is True
    assert v166._is_proactive_trigger("periodic_runtime_convergence") is True
    assert v166._is_proactive_trigger("periodic_runtime_convergence:retry") is True
    assert v166._is_proactive_trigger("publication_deadline_v137") is True


def test_v167_install_registers_release_manifest(monkeypatch):
    patch = importlib.import_module("bot.runtime_refresh_demand_v167_patch")
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    monkeypatch.setattr(manifest, "_REQUIRED_FLAGS", dict(manifest._REQUIRED_FLAGS))
    monkeypatch.delenv("NIJA_RUNTIME_REFRESH_DEMAND_V167_READY", raising=False)

    assert patch.install() is True
    assert os.environ["NIJA_RUNTIME_REFRESH_DEMAND_V167_READY"] == "1"
    assert manifest._REQUIRED_FLAGS["runtime_refresh_demand_v167"] == (
        "NIJA_RUNTIME_REFRESH_DEMAND_V167_READY"
    )


def test_v167_install_chain_includes_v174(monkeypatch):
    patch = importlib.import_module("bot.runtime_refresh_demand_v167_patch")
    calls: list[tuple[str, str]] = []

    def fake_install_named(module_name: str, label: str) -> bool:
        calls.append((module_name, label))
        return True

    monkeypatch.setattr(patch, "_install_named", fake_install_named)
    assert patch._install_v174_kraken_capital_observation_admission() is True
    assert calls == [
        (
            "bot.runtime_kraken_capital_observation_admission_v174_patch",
            "RUNTIME_KRAKEN_CAPITAL_OBSERVATION_ADMISSION_V174",
        )
    ]


def test_v167_install_chain_includes_v175(monkeypatch):
    patch = importlib.import_module("bot.runtime_refresh_demand_v167_patch")
    calls: list[tuple[str, str]] = []

    def fake_install_named(module_name: str, label: str) -> bool:
        calls.append((module_name, label))
        return True

    monkeypatch.setattr(patch, "_install_named", fake_install_named)
    assert patch._install_v175_authority_position_convergence() is True
    assert calls == [
        (
            "bot.runtime_authority_position_convergence_v175_patch",
            "RUNTIME_AUTHORITY_POSITION_CONVERGENCE_V175",
        )
    ]


def test_v167_install_chain_includes_v176(monkeypatch):
    patch = importlib.import_module("bot.runtime_refresh_demand_v167_patch")
    calls: list[tuple[str, str]] = []

    def fake_install_named(module_name: str, label: str) -> bool:
        calls.append((module_name, label))
        return True

    monkeypatch.setattr(patch, "_install_named", fake_install_named)
    assert patch._install_v176_capital_pipeline_completion() is True
    assert calls == [
        (
            "bot.runtime_capital_pipeline_completion_v176_patch",
            "RUNTIME_CAPITAL_PIPELINE_COMPLETION_V176",
        )
    ]


def test_post_import_convergence_installs_v167(monkeypatch):
    post = importlib.import_module("bot.runtime_post_import_convergence_patch")
    calls: list[tuple[str, str, str]] = []

    def fake_install_named(module_name: str, missing_reason: str, log_prefix: str) -> bool:
        calls.append((module_name, missing_reason, log_prefix))
        return True

    monkeypatch.setattr(post, "_install_named", fake_install_named)
    assert post._install_v167_refresh_demand() is True
    assert calls == [
        (
            "bot.runtime_refresh_demand_v167_patch",
            "v167_install_missing",
            "RUNTIME_REFRESH_DEMAND_V167_INSTALL_ERROR",
        )
    ]
