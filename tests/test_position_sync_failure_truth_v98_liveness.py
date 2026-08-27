from __future__ import annotations

from types import ModuleType, SimpleNamespace

import bot.position_sync_failure_truth_v98_patch as v98


class _Broker:
    def __init__(self, result=None, error: BaseException | None = None):
        self.connected = True
        self.position_tracker = SimpleNamespace(get_all_positions=lambda: [])
        self._startup_position_sync_adopted = True
        self._startup_position_sync_fetch_ok = True
        self._startup_position_sync_symbols = tuple()
        self._startup_position_sync_error = None
        self._result = [] if result is None else result
        self._error = error

    def get_positions(self):
        if self._error is not None:
            raise self._error
        return self._result


def _module_with_adopter(observed: list[tuple[bool, bool | None]] | None = None) -> ModuleType:
    module = ModuleType("bot.startup_position_sync")

    def adopter(broker, broker_name, eps):
        if observed is not None:
            observed.append(
                (
                    bool(getattr(broker, "_startup_position_sync_adopted", False)),
                    getattr(broker, "_startup_position_sync_fetch_ok", None),
                )
            )
        try:
            positions = broker.get_positions()
        except Exception:
            # Mirrors startup_position_sync: transport failures are logged and
            # converted to a non-success return at this legacy boundary.
            return 0
        if not positions:
            broker._startup_position_sync_adopted = True
            broker._startup_position_sync_symbols = tuple()
            return 0
        broker._startup_position_sync_adopted = True
        broker._startup_position_sync_symbols = tuple(
            sorted(str(item.get("symbol", "")) for item in positions if isinstance(item, dict))
        )
        return len(positions)

    module._adopt_broker_positions = adopter
    return module


def test_valid_prior_proof_is_not_revoked_before_refresh_fetch_starts(monkeypatch):
    observed: list[tuple[bool, bool | None]] = []
    module = _module_with_adopter(observed)
    monkeypatch.delenv("NIJA_POSITION_SYNC_ACTIVATION_READY", raising=False)
    monkeypatch.delenv("NIJA_POSITION_SYNC_DISPATCH_READY", raising=False)

    assert v98._patch_startup_sync(module) is True
    broker = _Broker(result=[])

    module._adopt_broker_positions(broker, "platform:coinbase", None)

    assert observed == [(True, True)]
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_fetch_ok is True
    assert broker._startup_position_sync_error is None


def test_completed_fetch_failure_revokes_previous_success(monkeypatch):
    module = _module_with_adopter()
    monkeypatch.delenv("NIJA_POSITION_SYNC_ACTIVATION_READY", raising=False)
    monkeypatch.delenv("NIJA_POSITION_SYNC_DISPATCH_READY", raising=False)

    assert v98._patch_startup_sync(module) is True
    broker = _Broker(error=TimeoutError("coinbase positions timed out"))

    module._adopt_broker_positions(broker, "platform:coinbase", None)

    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert "TimeoutError" in str(broker._startup_position_sync_error)
    assert v98.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert v98.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_authoritative_empty_snapshot_refreshes_fetch_proof():
    module = _module_with_adopter()
    assert v98._patch_startup_sync(module) is True
    broker = _Broker(result=[])
    broker._startup_position_sync_adopted = False
    broker._startup_position_sync_fetch_ok = None

    module._adopt_broker_positions(broker, "platform:coinbase", None)

    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_fetch_ok is True
    assert broker._startup_position_sync_error is None
