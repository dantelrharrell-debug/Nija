from __future__ import annotations

import types

from bot import runtime_kraken_margin_protection_authority_v368_patch as v368


def test_exact_scoped_authority_uses_v339_broker_context(monkeypatch):
    import bot.runtime_protective_exit_authority_bridge_v337_patch as v337
    import bot.runtime_protective_exit_broker_health_v339_patch as v339

    broker = object()
    seen = []

    def probe():
        seen.append(v339._BROKER.get())
        return True, "exact_broker_health_proven", object()

    monkeypatch.setattr(v337, "_hard_exit_authority_proof", probe)
    ok, reason = v368._exact_scoped_authority(broker)
    assert ok is True
    assert reason == "exact_broker_health_proven"
    assert seen == [broker]
    assert v339._BROKER.get() is None


def test_authenticated_read_fallback_does_not_promote_execution_health(monkeypatch):
    import bot.runtime_kraken_margin_protection_truth_v367_patch as v367
    import bot.runtime_all_account_position_exit_coverage_v281_patch as v281
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    broker = types.SimpleNamespace(connected=False)
    monkeypatch.setattr(v367, "_account_brokers", lambda: [])
    monkeypatch.setattr(v281, "_canonical_manager", lambda: object())
    monkeypatch.setattr(v281, "_expected_accounts", lambda _manager: {"platform:kraken": broker})
    monkeypatch.setattr(v366, "is_kraken_account", lambda account, obj: obj is broker)
    monkeypatch.setattr(v367, "_native_protection", lambda account, obj: (True, {}, "ok"))

    assert v368._patch_account_brokers_authenticated_read_fallback() is True
    assert v367._account_brokers() == [("platform:kraken", broker)]
    assert broker.connected is False


def test_software_status_remains_fail_closed_when_exact_authority_fails(monkeypatch):
    import bot.runtime_kraken_margin_protection_truth_v367_patch as v367

    monkeypatch.setattr(v367, "_monitor_alive", lambda: True)
    monkeypatch.setattr(v367, "_margin_scan_wiring_ready", lambda: True)
    monkeypatch.setattr(v368, "_exact_scoped_authority", lambda broker: (False, "nonce_not_ready"))

    original = v367._software_protection_status
    monkeypatch.setattr(v367, "_software_protection_status", original)
    assert v368._patch_software_protection_status() is True

    token = v368._BROKER_SCOPE.set(object())
    try:
        ok, reason = v367._software_protection_status()
    finally:
        v368._BROKER_SCOPE.reset(token)

    assert ok is False
    assert reason == "hard_exit_authority_unproven:nonce_not_ready"
