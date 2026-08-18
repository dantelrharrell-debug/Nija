from __future__ import annotations

from types import SimpleNamespace

from bot.kill_switch_coordinator_sync_patch import _prepare_capital_publication_liveness


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


def test_pre_v142_inflight_rolls_over_when_refresh_enters_headroom(monkeypatch) -> None:
    from bot import capital_publication_deadline_v137_patch as v137

    old = SimpleNamespace(_in_flight=True)
    replacement = SimpleNamespace(_in_flight=False)
    manager = SimpleNamespace(_capital_coordinator=old)
    authority = SimpleNamespace()
    reasons: list[str] = []

    fake = SimpleNamespace(
        _nija_startup_chain_prepared=False,
        _coordinator_in_flight_v142=lambda manager: True,
        _authority=lambda: authority,
    )

    def rollover(target_manager, *, expected_old=None, reason):
        assert expected_old is old
        reasons.append(str(reason))
        target_manager._capital_coordinator = replacement
        return replacement

    fake._rollover_coordinator = rollover
    monkeypatch.setattr(
        v137,
        "_publication_refresh_due",
        lambda authority, manager: (
            True,
            {
                "due_reason": "pre_expiry_headroom",
                "remaining_s": 42.0,
            },
        ),
    )

    assert _prepare_capital_publication_liveness(fake) is True
    assert fake._coordinator_in_flight_v142(manager) is False
    assert manager._capital_coordinator is replacement
    assert reasons == ["untracked_inflight_refresh_due:pre_expiry_headroom"]
