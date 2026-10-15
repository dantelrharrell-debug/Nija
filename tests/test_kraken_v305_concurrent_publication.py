"""v305 must not roll back an authenticated Balance publication made during a slow ordinary read."""
import threading
from bot import runtime_kraken_authoritative_snapshot_ownership_v305_patch as v305
from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286

class Broker:
    account_identifier = "USER:test"
    broker_type = "kraken"
    connected = True

def test_concurrent_authenticated_publication_is_preserved():
    broker = Broker()
    old = [{"symbol":"BTC-USD","quantity":1.0,"authoritative_balance":True}]
    new = [{"symbol":"BTC-USD","quantity":2.0,"authoritative_balance":True}]
    v286._record_snapshot_success(broker,old)
    entered = threading.Event()
    release = threading.Event()
    result = []
    def ordinary(self):
        entered.set()
        assert release.wait(3)
        return []
    wrapped = v305._wrap_get_positions(ordinary)
    worker = threading.Thread(target=lambda: result.append(wrapped(broker)))
    worker.start()
    try:
        assert entered.wait(3)
        v286._record_snapshot_success(broker,new)
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert result == [[]]
    assert broker._nija_authoritative_position_snapshot_generation_v285 == 2
    assert broker._nija_authoritative_position_raw_generation_v286 == 2
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is True

def test_concurrent_ordinary_corruption_remains_fail_closed():
    broker = Broker()
    v286._record_snapshot_success(broker,[{"symbol":"BTC-USD","quantity":1.0,"authoritative_balance":True}])
    entered = threading.Event()
    release = threading.Event()
    def ordinary(self):
        entered.set()
        assert release.wait(3)
        self._nija_authoritative_position_snapshot_generation_v285 = -1
        return []
    wrapped = v305._wrap_get_positions(ordinary)
    worker = threading.Thread(target=lambda: wrapped(broker))
    worker.start()
    try:
        assert entered.wait(3)
        v286._record_snapshot_success(broker,[{"symbol":"BTC-USD","quantity":2.0,"authoritative_balance":True}])
    finally:
        release.set()
        worker.join(timeout=3)
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False


def test_concurrent_authenticated_empty_balance_publication_is_preserved():
    """An authenticated zero-holding Balance generation is not an ordinary empty read."""
    broker = Broker()
    v286._record_snapshot_success(
        broker, [{"symbol": "BTC-USD", "quantity": 1.0, "authoritative_balance": True}]
    )
    entered = threading.Event()
    release = threading.Event()
    result = []

    def ordinary(self):
        entered.set()
        assert release.wait(3)
        return []

    wrapped = v305._wrap_get_positions(ordinary)
    worker = threading.Thread(target=lambda: result.append(wrapped(broker)))
    worker.start()
    try:
        assert entered.wait(3)
        v286._record_snapshot_success(broker, [])
    finally:
        release.set()
        worker.join(timeout=3)

    assert not worker.is_alive()
    assert result == [[]]
    assert broker._nija_authoritative_position_snapshot_generation_v285 == 2
    assert broker._nija_authoritative_position_raw_generation_v286 == 2
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is True
    assert broker._nija_authoritative_position_snapshot_rows_v285 == ()
    assert broker._nija_authoritative_position_raw_rows_v286 == ()
