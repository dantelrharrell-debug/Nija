from __future__ import annotations

import render_liveness_server as server
import render_readiness_state_bridge as bridge


def test_render_cold_start_does_not_report_synthetic_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("NIJA_RENDER_READINESS_STATE_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("NIJA_REQUIRED_LIVE_VENUES", "coinbase,okx")

    ready, details = server._readiness()

    assert ready is False
    assert details["readiness_source"] == "safe_render_startup"
    assert details["coinbase_activation_state"] == "unobserved"
    assert details["coinbase_balance_observed"] == "0"
    assert details["coinbase_funding_status"] == "unobserved"
    assert details["coinbase_spendable_quote"] == "unobserved"
    assert details["degraded_live_venues"] == ""


def test_bridge_preserves_real_observed_coinbase_balance(monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_BALANCE_OBSERVED", "1")
    monkeypatch.setenv("NIJA_COINBASE_FUNDING_STATUS", "funded")
    monkeypatch.setenv("NIJA_COINBASE_SPENDABLE_QUOTE", "27.124880759")

    payload = bridge._payload()

    assert payload["coinbase_balance_observed"] == "1"
    assert payload["coinbase_funding_status"] == "funded"
    assert payload["coinbase_spendable_quote"] == "27.124880759"


def test_bridge_rejects_stale_zero_before_balance_probe(monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_BALANCE_OBSERVED", "0")
    monkeypatch.setenv("NIJA_COINBASE_FUNDING_STATUS", "observed_zero")
    monkeypatch.setenv("NIJA_COINBASE_SPENDABLE_QUOTE", "0")

    payload = bridge._payload()

    assert payload["coinbase_balance_observed"] == "0"
    assert payload["coinbase_funding_status"] == "unobserved"
    assert payload["coinbase_spendable_quote"] == "unobserved"


def test_observed_zero_remains_a_real_zero(monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_BALANCE_OBSERVED", "1")
    monkeypatch.setenv("NIJA_COINBASE_FUNDING_STATUS", "observed_zero")
    monkeypatch.setenv("NIJA_COINBASE_SPENDABLE_QUOTE", "0")

    payload = bridge._payload()

    assert payload["coinbase_balance_observed"] == "1"
    assert payload["coinbase_funding_status"] == "observed_zero"
    assert payload["coinbase_spendable_quote"] == "0"
