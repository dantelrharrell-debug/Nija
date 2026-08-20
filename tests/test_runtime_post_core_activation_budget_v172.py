from __future__ import annotations

import time

from bot import runtime_post_core_activation_budget_v172_patch as patch


def test_default_wait_covers_80s_pipeline_and_stays_below_90s_ttl(monkeypatch):
    for name in (
        "NIJA_POST_CORE_ACTIVATION_WAIT_S",
        "NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S",
        "NIJA_CAPITAL_PIPELINE_DEADLINE_S",
        "NIJA_CAPITAL_RUNTIME_DEADLINE_S",
        "NIJA_CAPITAL_REFRESH_PIPELINE_DEADLINE_S",
        "NIJA_CAPITAL_FRESHNESS_TTL_S",
        "NIJA_POST_CORE_ACTIVATION_FRESHNESS_MARGIN_S",
    ):
        monkeypatch.delenv(name, raising=False)

    wait_s = patch._activation_wait_seconds(60.0)
    assert wait_s == 85.0
    assert wait_s >= 80.0
    assert wait_s < 90.0


def test_lower_override_cannot_shorten_required_pipeline_budget(monkeypatch):
    monkeypatch.setenv("NIJA_POST_CORE_ACTIVATION_WAIT_S", "35")
    monkeypatch.setenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "80")
    monkeypatch.setenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "90")

    assert patch._activation_wait_seconds(40.0) == 85.0


def test_high_override_is_clamped_below_freshness_ttl(monkeypatch):
    monkeypatch.setenv("NIJA_POST_CORE_ACTIVATION_WAIT_S", "300")
    monkeypatch.setenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "90")
    monkeypatch.setenv("NIJA_POST_CORE_ACTIVATION_FRESHNESS_MARGIN_S", "5")

    assert patch._activation_wait_seconds(60.0) == 85.0


def test_custom_ttl_retains_safety_margin(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "120")
    monkeypatch.setenv("NIJA_POST_CORE_ACTIVATION_FRESHNESS_MARGIN_S", "10")
    monkeypatch.setenv("NIJA_POST_CORE_ACTIVATION_WAIT_S", "105")

    wait_s = patch._activation_wait_seconds(60.0)
    assert wait_s == 105.0
    assert wait_s <= 110.0


def test_source_repair_replaces_only_legacy_30s_cap():
    def _perform_post_core_activation_convergence(runtime, trading_thread, *, timeout_s=60.0):
        _act_deadline = time.time() + min(timeout_s, 30.0)
        return _act_deadline

    _perform_post_core_activation_convergence.__globals__["_nija_v172_activation_wait_s"] = (
        lambda requested: 85.0
    )
    repaired = patch._compile_repaired_function(_perform_post_core_activation_convergence)
    before = time.time()
    deadline = repaired(None, None, timeout_s=60.0)
    after = time.time()

    assert before + 84.5 <= deadline <= after + 85.5


def test_wait_budget_does_not_change_gate_result(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "90")
    # v172 computes only a wait duration; it has no API for granting readiness.
    wait_s = patch._activation_wait_seconds(60.0)
    assert isinstance(wait_s, float)
    assert not hasattr(patch, "force_activation")
    assert not hasattr(patch, "grant_execution_authority")
