from __future__ import annotations

from types import SimpleNamespace

from bot.kill_switch_coordinator_sync_patch import (
    _prepare_capital_publication_liveness,
    _structural_readiness_blockers,
)


def test_wrapper_proof_uses_code_identity_not_copied_display_name() -> None:
    def original():
        return None

    def owned_wrapper():
        return original()

    owned_wrapper.__name__ = original.__name__
    owned_wrapper.__wrapped__ = original
    owned_wrapper._owned = True

    fake = SimpleNamespace(
        _nija_startup_chain_prepared=False,
        _coordinator_in_flight_v142=lambda manager: False,
        _canonical_broker_connectivity=lambda: (False, {}),
        _canonical_manager=lambda: None,
    )
    assert _prepare_capital_publication_liveness(fake) is True

    assert fake._chain_contains(
        owned_wrapper,
        marker="_owned",
        expected_name="owned_wrapper",
    ) is True
    assert fake._chain_contains(
        owned_wrapper,
        marker="_owned",
        expected_name="different_wrapper",
    ) is False


def test_pre_v142_inflight_is_preserved_during_refresh_headroom() -> None:
    old = SimpleNamespace(_in_flight=True)
    manager = SimpleNamespace(_capital_coordinator=old)
    rollover_calls: list[str] = []

    fake = SimpleNamespace(
        _nija_startup_chain_prepared=False,
        _coordinator_in_flight_v142=lambda manager: True,
        _canonical_broker_connectivity=lambda: (False, {}),
        _canonical_manager=lambda: None,
    )

    def rollover(target_manager, *, expected_old=None, reason):
        rollover_calls.append(str(reason))
        return expected_old

    fake._rollover_coordinator = rollover

    assert _prepare_capital_publication_liveness(fake) is True
    assert fake._coordinator_in_flight_v142(manager) is True
    assert manager._capital_coordinator is old
    assert rollover_calls == []


def test_direct_broker_connectivity_false_cannot_be_overridden_by_stale_manager_state() -> None:
    broker_key = SimpleNamespace(value="kraken")
    broker = SimpleNamespace(connected=False)
    manager = SimpleNamespace(
        _platform_brokers={broker_key: broker},
        _platform_state={"kraken": "connected"},
        is_platform_connected=lambda raw_key: True,
    )
    fake = SimpleNamespace(
        _nija_startup_chain_prepared=False,
        _coordinator_in_flight_v142=lambda manager: False,
        _canonical_broker_connectivity=lambda: (True, {}),
        _canonical_manager=lambda: manager,
    )

    assert _prepare_capital_publication_liveness(fake) is True
    ready, meta = fake._canonical_broker_connectivity()

    assert ready is False
    assert meta["registered"] == ["kraken"]
    assert meta["connected"] == []
    assert meta["direct_connectivity_authoritative"] is True


def test_direct_broker_connectivity_true_remains_connected() -> None:
    broker_key = SimpleNamespace(value="coinbase")
    broker = SimpleNamespace(connected=True)
    manager = SimpleNamespace(
        _platform_brokers={broker_key: broker},
        _platform_state={"coinbase": "disconnected"},
        is_platform_connected=lambda raw_key: False,
    )
    fake = SimpleNamespace(
        _nija_startup_chain_prepared=False,
        _coordinator_in_flight_v142=lambda manager: False,
        _canonical_broker_connectivity=lambda: (False, {}),
        _canonical_manager=lambda: manager,
    )

    assert _prepare_capital_publication_liveness(fake) is True
    ready, meta = fake._canonical_broker_connectivity()

    assert ready is True
    assert meta["connected"] == ["coinbase"]


def test_structural_readiness_blockers_include_runtime_handoff_proofs(monkeypatch) -> None:
    from bot import readiness_table

    monkeypatch.setattr(
        readiness_table,
        "snapshot",
        lambda: {
            "broker_connected": True,
            "balance_hydrated": True,
            "authority_ready": False,
            "capital_ready": True,
            "risk_ready": True,
            "strategy_ready": False,
            "execution_ready": False,
            "nonce_ready": False,
            "bootstrap_ready": True,
            "position_sync_ready": False,
        },
    )

    assert _structural_readiness_blockers() == [
        "strategy_ready",
        "execution_ready",
        "position_sync_ready",
    ]
