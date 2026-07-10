from __future__ import annotations

import importlib.util
import logging
import os
import sys
import threading
import types
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "post_lock_capital_refresh_patch.py"


def _load_patch(name: str = "test_post_lock_capital_refresh_patch_module"):
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_quoted_true_is_normalized_without_enabling_missing_switches(
    monkeypatch: pytest.MonkeyPatch,
):
    patch = _load_patch("post_lock_normalization")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", ' "TRUE" ')
    monkeypatch.delenv("DRY_RUN_MODE", raising=False)

    changed, state, _ = patch._normalize_explicit_boolean("LIVE_CAPITAL_VERIFIED")
    missing_changed, missing_state, _ = patch._normalize_explicit_boolean("DRY_RUN_MODE")

    assert changed is True
    assert state == "true"
    assert os.environ["LIVE_CAPITAL_VERIFIED"] == "true"
    assert missing_changed is False
    assert missing_state == "missing"
    assert "DRY_RUN_MODE" not in os.environ


def test_invalid_live_switch_remains_fail_closed(monkeypatch: pytest.MonkeyPatch):
    patch = _load_patch("post_lock_invalid")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "maybe")

    changed, state, cleaned = patch._normalize_explicit_boolean("LIVE_CAPITAL_VERIFIED")

    assert changed is False
    assert state == "invalid"
    assert cleaned == "maybe"
    assert os.environ["LIVE_CAPITAL_VERIFIED"] == "maybe"
    assert patch._truthy_env("LIVE_CAPITAL_VERIFIED") is False


def test_capital_result_accepts_object_and_mapping_shapes():
    patch = _load_patch("post_lock_capital_result")

    class Snapshot:
        ready = 1
        total_capital = 125.50
        valid_brokers = 2
        snapshot_source = "live_exchange"

    object_result = patch._capital_result(Snapshot())
    mapping_result = patch._capital_result(
        {"ready": 1.0, "total_capital": 88.0, "valid_brokers": 1}
    )

    assert object_result["total_capital"] == 125.50
    assert object_result["valid_brokers"] == 2
    assert object_result["snapshot_source"] == "live_exchange"
    assert mapping_result["total_capital"] == 88.0


def test_patch_noise_filter_keeps_first_and_suppresses_duplicate(
    monkeypatch: pytest.MonkeyPatch,
):
    patch = _load_patch("post_lock_noise")
    monkeypatch.setenv("NIJA_PATCH_INSTALL_LOG_THROTTLE_S", "60")
    patch._PatchNoiseFilter._last_seen.clear()
    filter_ = patch._PatchNoiseFilter()
    first = logging.LogRecord(
        "one",
        logging.WARNING,
        __file__,
        1,
        "SPENDABLE_QUOTE_ROUTING_PATCHED marker=20260706a",
        (),
        None,
    )
    second = logging.LogRecord(
        "two",
        logging.WARNING,
        __file__,
        2,
        "SPENDABLE_QUOTE_ROUTING_PATCHED marker=20260706a",
        (),
        None,
    )

    assert filter_.filter(first) is True
    assert filter_.filter(second) is False


def test_verified_live_capital_requests_existing_safe_convergence(
    monkeypatch: pytest.MonkeyPatch,
):
    patch = _load_patch("post_lock_convergence")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    class CapitalAuthority:
        is_hydrated = True
        real_capital = 125.50

        def get_real_capital(self):
            return self.real_capital

        def is_fresh(self, ttl_s=180.0):
            return True

    gate = threading.Event()
    gate.set()
    capital_module = types.ModuleType("bot.capital_authority")
    capital_module.get_capital_authority = lambda: CapitalAuthority()
    capital_module.get_capital_system_gate = lambda: gate
    runtime_module = types.ModuleType("bot.runtime_authority_convergence_repair_patch")
    calls: list[str] = []
    runtime_module.converge_runtime_authority = lambda source: calls.append(source) or True
    bot_module = types.ModuleType("bot")
    bot_module.__path__ = []

    monkeypatch.setitem(sys.modules, "bot", bot_module)
    monkeypatch.setitem(sys.modules, "bot.capital_authority", capital_module)
    monkeypatch.setitem(
        sys.modules,
        "bot.runtime_authority_convergence_repair_patch",
        runtime_module,
    )
    original_import_module = patch.importlib.import_module

    def fake_import(name: str, package=None):
        if name == "bot.runtime_authority_convergence_repair_patch":
            return runtime_module
        return original_import_module(name, package)

    monkeypatch.setattr(patch.importlib, "import_module", fake_import)
    result = {
        "ready": 1.0,
        "total_capital": 125.50,
        "valid_brokers": 2,
        "snapshot_source": "live_exchange",
    }

    assert patch._request_safe_convergence("test", result) is True
    assert calls == ["post_lock_capital:test"]


def test_convergence_never_enables_operator_switch(monkeypatch: pytest.MonkeyPatch):
    patch = _load_patch("post_lock_switch_off")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "false")
    result = {
        "ready": 1.0,
        "total_capital": 125.50,
        "valid_brokers": 2,
        "snapshot_source": "live_exchange",
    }

    assert patch._request_safe_convergence("test", result) is False
    assert os.environ["LIVE_CAPITAL_VERIFIED"] == "false"


def test_placeholder_or_dedup_snapshot_cannot_trigger_convergence(
    monkeypatch: pytest.MonkeyPatch,
):
    patch = _load_patch("post_lock_placeholder")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setattr(patch, "_capital_authority_proof", lambda: (True, "proof"))

    assert patch._request_safe_convergence(
        "placeholder",
        {
            "ready": 1.0,
            "total_capital": 125.50,
            "valid_brokers": 2,
            "snapshot_source": "placeholder",
        },
    ) is False
    assert patch._request_safe_convergence(
        "dedup",
        {
            "ready": 1.0,
            "total_capital": 0.0,
            "valid_brokers": 2,
            "dedup": 1.0,
        },
    ) is False
