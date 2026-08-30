from __future__ import annotations

from pathlib import Path

import pytest

from bot import runtime_kraken_authoritative_snapshot_ownership_v305_patch as v305


class _FakeKraken:
    account_identifier = "PLATFORM"

    def __init__(self) -> None:
        self._nija_authoritative_position_snapshot_rows_v285 = ({"symbol": "ETH-USD", "quantity": 1.0},)
        self._nija_authoritative_position_snapshot_at_monotonic_v285 = 123.5
        self._nija_authoritative_position_snapshot_at_wall_v285 = 456.5
        self._nija_authoritative_position_snapshot_generation_v285 = 7
        self._nija_authoritative_position_snapshot_fetch_ok_v285 = True
        self._nija_authoritative_position_snapshot_error_v285 = None


def _original_state(broker: _FakeKraken) -> dict[str, object]:
    return {name: getattr(broker, name) for name in v305._SNAPSHOT_FIELDS}


def _mutate_authority_state(broker: _FakeKraken) -> None:
    broker._nija_authoritative_position_snapshot_rows_v285 = ({"symbol": "BTC-USD", "quantity": 2.0},)
    broker._nija_authoritative_position_snapshot_at_monotonic_v285 = 999.0
    broker._nija_authoritative_position_snapshot_at_wall_v285 = 999.0
    broker._nija_authoritative_position_snapshot_generation_v285 = 99
    broker._nija_authoritative_position_snapshot_fetch_ok_v285 = False
    broker._nija_authoritative_position_snapshot_error_v285 = "ordinary_openpositions_failed"


def test_ordinary_get_positions_result_passes_through_and_authority_state_is_restored() -> None:
    broker = _FakeKraken()
    before = _original_state(broker)
    result = [{"symbol": "ETH-USD", "quantity": 1.0}]

    def ordinary_get_positions(self):
        _mutate_authority_state(self)
        return result

    wrapped = v305._wrap_get_positions(ordinary_get_positions)

    assert wrapped(broker) is result
    assert _original_state(broker) == before


def test_ordinary_get_positions_exception_passes_through_and_authority_state_is_restored() -> None:
    broker = _FakeKraken()
    before = _original_state(broker)
    failure = RuntimeError("openpositions_lock_busy")

    def ordinary_get_positions(self):
        _mutate_authority_state(self)
        raise failure

    wrapped = v305._wrap_get_positions(ordinary_get_positions)

    with pytest.raises(RuntimeError) as caught:
        wrapped(broker)

    assert caught.value is failure
    assert _original_state(broker) == before


def test_fields_created_only_by_ordinary_read_are_removed_after_call() -> None:
    class EmptyKraken:
        account_identifier = "PLATFORM"

    broker = EmptyKraken()

    def ordinary_get_positions(self):
        self._nija_authoritative_position_snapshot_rows_v285 = ()
        self._nija_authoritative_position_snapshot_at_monotonic_v285 = 1.0
        self._nija_authoritative_position_snapshot_at_wall_v285 = 2.0
        self._nija_authoritative_position_snapshot_generation_v285 = 1
        self._nija_authoritative_position_snapshot_fetch_ok_v285 = False
        self._nija_authoritative_position_snapshot_error_v285 = "temporary"
        return []

    wrapped = v305._wrap_get_positions(ordinary_get_positions)
    assert wrapped(broker) == []
    for name in v305._SNAPSHOT_FIELDS:
        assert not hasattr(broker, name)


def test_v303_production_surface_chains_v305() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "bot" / "runtime_heartbeat_position_cap_result_bridge_v303_patch.py").read_text(encoding="utf-8")

    assert "runtime_kraken_authoritative_snapshot_ownership_v305_patch" in source
    assert "v305_ready = _install_v305_snapshot_ownership()" in source
    assert "and v305_ready" in source
