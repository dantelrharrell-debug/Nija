from __future__ import annotations

from bot import runtime_authority_convergence_repair_patch as patch


class FakeCapitalAuthority:
    is_hydrated = True
    first_snap_accepted = True
    total_capital = 579.90
    usable_capital = 568.30
    risk_capital = 568.30
    valid_broker_count = 3
    registered_broker_count = 3

    def get_real_capital(self):
        return 579.90

    def get_usable_capital(self):
        return 568.30

    def is_fresh(self, ttl_s=240.0):
        return True


class HandoffOnlyCapitalAuthority:
    is_hydrated = True
    total_capital = 466.62
    real_capital = 466.62
    usable_capital = 0.0
    risk_capital = 0.0
    valid_brokers = 3
    broker_count = 3

    def get_real_capital(self):
        return 466.62

    def get_usable_capital(self):
        return 0.0

    def is_stale(self):
        return True


class ConflictingFreshnessCapitalAuthority(FakeCapitalAuthority):
    def __init__(self):
        self.freshness_ttls = []

    def is_fresh(self, ttl_s=240.0):
        self.freshness_ttls.append(ttl_s)
        return True

    def is_stale(self, ttl_s=60.0):
        raise AssertionError("is_stale must not overwrite canonical is_fresh")


class FakeKillSwitch:
    def __init__(self, active=False):
        self._active = active

    def is_active(self):
        return self._active


def _live_env(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "EMERGENCY_STOP")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "1")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "2257")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "9999999999")


def test_capital_authority_ready_for_logged_579_case(monkeypatch):
    _live_env(monkeypatch)
    import bot.capital_authority as ca_mod
    monkeypatch.setattr(ca_mod, "get_capital_authority", lambda: FakeCapitalAuthority())

    ready, reason, detail = patch._capital_authority_ready()

    assert ready is True
    assert "capital_ready" in reason
    assert detail["real"] == 579.90
    assert detail["valid_brokers"] == 3


def test_capital_authority_accepts_handoff_ready_snapshot_without_usable_field(monkeypatch):
    _live_env(monkeypatch)
    monkeypatch.delenv("LIVE_CAPITAL_VERIFIED", raising=False)
    monkeypatch.setenv("NIJA_CAPITAL_READINESS_HANDOFF_V34_READY", "1")
    import bot.capital_authority as ca_mod
    monkeypatch.setattr(ca_mod, "get_capital_authority", lambda: HandoffOnlyCapitalAuthority())

    ready, reason, detail = patch._capital_authority_ready()

    assert ready is True
    assert "handoff=True" in reason
    assert detail["real"] == 466.62
    assert detail["usable"] == 466.62
    assert detail["valid_brokers"] == 3
    assert detail["fresh"] is True


def test_capital_freshness_uses_one_consistent_ttl(monkeypatch):
    _live_env(monkeypatch)
    monkeypatch.setenv(
        "NIJA_RUNTIME_AUTHORITY_CONVERGENCE_CAPITAL_TTL_S", "240"
    )
    authority = ConflictingFreshnessCapitalAuthority()
    import bot.capital_authority as ca_mod
    monkeypatch.setattr(ca_mod, "get_capital_authority", lambda: authority)

    ready, _reason, detail = patch._capital_authority_ready()

    assert ready is True
    assert detail["fresh"] is True
    assert authority.freshness_ttls == [240.0]


def test_heartbeat_ready_requires_token_generation_and_fresh_alive(monkeypatch):
    _live_env(monkeypatch)

    ready, reason = patch._heartbeat_ready()

    assert ready is True
    assert "heartbeat_ready" in reason


def test_heartbeat_fails_closed_without_generation(monkeypatch):
    _live_env(monkeypatch)
    monkeypatch.delenv("NIJA_WRITER_LEASE_GENERATION", raising=False)

    ready, reason = patch._heartbeat_ready()

    assert ready is False
    assert "writer_token_or_generation_missing" in reason


def test_unsafe_emergency_reason_blocks_recovery(monkeypatch):
    _live_env(monkeypatch)
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_REASON", "manual operator stop")

    unsafe, token = patch._unsafe_emergency_reason_present()

    assert unsafe is True
    assert token in {"manual", "operator"}


def test_safe_to_recover_when_kill_switch_clear_capital_ready_and_writer_ok(monkeypatch):
    _live_env(monkeypatch)
    import bot.capital_authority as ca_mod
    import bot.kill_switch as kill_mod
    monkeypatch.setattr(ca_mod, "get_capital_authority", lambda: FakeCapitalAuthority())
    monkeypatch.setattr(kill_mod, "get_kill_switch", lambda: FakeKillSwitch(active=False))
    monkeypatch.setattr(patch, "_distributed_writer_ready", lambda: (True, "distributed_writer_ready"))

    ready, reason, detail = patch._safe_to_recover()

    assert ready is True
    assert "kill_switch_clear" in reason
    assert "capital_ready" in reason
    assert detail["usable"] == 568.30

def test_convergence_blocks_same_thread_reentry(monkeypatch):
    calls = []
    monkeypatch.setattr(
        patch,
        "_converge_runtime_authority_once",
        lambda source: calls.append(source) or True,
    )
    monkeypatch.setattr(patch._CONVERGENCE_LOCAL, "active", True, raising=False)

    assert patch.converge_runtime_authority("nested") is False
    assert calls == []


def test_rejected_activation_commit_does_not_force_live_transition(monkeypatch):
    import bot.trading_state_machine as tsm

    class FakeStateMachine:
        def __init__(self):
            self.state = tsm.TradingState.OFF
            self.commit_calls = 0
            self.transitions = []

        def get_current_state(self):
            return self.state

        def commit_activation(self, cycle_capital=None):
            self.commit_calls += 1
            return False

        def transition_to(self, state, reason):
            self.transitions.append((state, reason))
            self.state = state
            return True

    sm = FakeStateMachine()
    monkeypatch.setenv("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_REPAIR_ENABLED", "true")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setattr(
        patch,
        "_safe_to_recover",
        lambda: (
            True,
            "all safety proofs passed",
            {"valid_brokers": 3, "hydrated": True, "fresh": True, "real": 466.21},
        ),
    )
    monkeypatch.setattr(tsm, "get_state_machine", lambda: sm)
    monkeypatch.setattr(patch._CONVERGENCE_LOCAL, "active", False, raising=False)

    assert patch.converge_runtime_authority("test") is False
    assert sm.commit_calls == 1
    assert sm.transitions == []
    assert sm.state == tsm.TradingState.OFF

