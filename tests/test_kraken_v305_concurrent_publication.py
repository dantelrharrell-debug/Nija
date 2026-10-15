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



def test_concurrent_authenticated_balance_failure_remains_fail_closed():
    """A failed real Balance request cannot be erased by an ordinary read."""
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
        v286._record_snapshot_failure(broker, "authenticated_balance_request_failed")
    finally:
        release.set()
        worker.join(timeout=3)

    assert not worker.is_alive()
    assert result == [[]]
    assert broker._nija_authoritative_position_raw_generation_v286 == 1
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False
    assert broker._nija_authoritative_position_snapshot_error_v285 == (
        "v305_concurrent_authenticated_balance_failure"
    )
    assert broker._nija_authoritative_position_failure_serial_v286 == 1


def test_ordinary_failure_without_real_balance_failure_preserves_prior_proof():
    """Only non-authoritative get_positions() errors may restore v305 state."""
    from bot import runtime_authoritative_position_coverage_v285_patch as v285

    broker = Broker()
    v286._record_snapshot_success(
        broker, [{"symbol": "BTC-USD", "quantity": 1.0, "authoritative_balance": True}]
    )

    def ordinary(self):
        v285._record_snapshot_failure(self, "ordinary_get_positions_failed")
        raise RuntimeError("ordinary_get_positions_failed")

    wrapped = v305._wrap_get_positions(ordinary)
    try:
        wrapped(broker)
    except RuntimeError as exc:
        assert str(exc) == "ordinary_get_positions_failed"
    else:
        raise AssertionError("ordinary failure must propagate")

    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is True
    assert broker._nija_authoritative_position_snapshot_generation_v285 == 1
    assert broker._nija_authoritative_position_raw_generation_v286 == 1
    assert getattr(broker, "_nija_authoritative_position_failure_serial_v286", 0) == 0


def test_raw_publication_failure_is_counted_and_invalidates_canonical_proof():
    class RawWriteFailureBroker(Broker):
        def __setattr__(self, name, value):
            if name == "_nija_authoritative_position_raw_rows_v286":
                raise OSError("raw snapshot write failed")
            super().__setattr__(name, value)

    broker = RawWriteFailureBroker()
    try:
        v286._record_snapshot_success(
            broker, [{"symbol": "BTC-USD", "quantity": 1.0, "authoritative_balance": True}]
        )
    except RuntimeError as exc:
        assert "v286_raw_snapshot_publication_failed" in str(exc)
    else:
        raise AssertionError("raw publication failure must fail closed")

    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False
    assert broker._nija_authoritative_position_failure_serial_v286 == 1


def test_authoritative_failure_serial_is_account_local():
    first, second = Broker(), Broker()
    v286._record_snapshot_success(
        first, [{"symbol": "BTC-USD", "quantity": 1.0, "authoritative_balance": True}]
    )
    v286._record_snapshot_success(
        second, [{"symbol": "ETH-USD", "quantity": 2.0, "authoritative_balance": True}]
    )
    v286._record_snapshot_failure(second, "second_account_authenticated_read_failed")
    assert first._nija_authoritative_position_snapshot_fetch_ok_v285 is True
    assert getattr(first, "_nija_authoritative_position_failure_serial_v286", 0) == 0
    assert second._nija_authoritative_position_snapshot_fetch_ok_v285 is False
    assert second._nija_authoritative_position_failure_serial_v286 == 1


def test_disconnected_authenticated_kraken_read_revokes_old_proof():
    broker = Broker()
    v286._record_snapshot_success(
        broker, [{"symbol": "BTC-USD", "quantity": 1.0, "authoritative_balance": True}]
    )
    broker.connected = False
    try:
        v286._fetch_authoritative_rows_sync(broker)
    except RuntimeError as exc:
        assert str(exc) == "kraken_broker_not_connected"
    else:
        raise AssertionError("disconnected Balance must be rejected")
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False
    assert broker._nija_authoritative_position_failure_serial_v286 == 1


def test_missing_private_balance_client_revokes_old_proof():
    broker = Broker()
    v286._record_snapshot_success(
        broker, [{"symbol": "BTC-USD", "quantity": 1.0, "authoritative_balance": True}]
    )
    try:
        v286._fetch_authoritative_rows_sync(broker)
    except RuntimeError as exc:
        assert str(exc) == "kraken_private_call_unavailable"
    else:
        raise AssertionError("missing authenticated Balance client must be rejected")
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False
    assert broker._nija_authoritative_position_failure_serial_v286 == 1


def test_concurrent_canonical_publication_rejection_never_revives_old_proof():
    """Failed authenticated Balance publication is not an ordinary read failure."""
    from unittest.mock import patch
    from bot import runtime_authoritative_position_coverage_v285_patch as v285

    broker = Broker()
    v286._record_snapshot_success(
        broker, [{"symbol": "BTC-USD", "quantity": 1.0, "authoritative_balance": True}]
    )
    entered = threading.Event()
    release = threading.Event()
    worker_errors = []

    def ordinary(self):
        entered.set()
        assert release.wait(3)
        return []

    wrapped = v305._wrap_get_positions(ordinary)
    worker = threading.Thread(target=lambda: (
        wrapped(broker) if not worker_errors else None
    ))
    worker.start()
    try:
        assert entered.wait(3)
        with patch.object(v285, "_record_snapshot_success", return_value=False):
            try:
                v286._record_snapshot_success(
                    broker, [{"symbol": "BTC-USD", "quantity": 2.0, "authoritative_balance": True}]
                )
            except RuntimeError as exc:
                assert str(exc) == "v285_authoritative_snapshot_record_failed"
            else:
                raise AssertionError("canonical publication rejection must fail")
    finally:
        release.set()
        worker.join(timeout=3)

    assert not worker.is_alive()
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False
    assert broker._nija_authoritative_position_snapshot_error_v285 == (
        "v305_concurrent_authenticated_balance_failure"
    )
    assert broker._nija_authoritative_position_raw_generation_v286 == 1
    assert broker._nija_authoritative_position_failure_serial_v286 == 1


def test_canonical_publication_exception_revokes_old_proof():
    """Unexpected canonical writer errors must also revoke authenticated proof."""
    from unittest.mock import patch
    from bot import runtime_authoritative_position_coverage_v285_patch as v285

    broker = Broker()
    v286._record_snapshot_success(
        broker, [{"symbol": "BTC-USD", "quantity": 1.0, "authoritative_balance": True}]
    )
    with patch.object(v285, "_record_snapshot_success", side_effect=OSError("test_write_error")):
        try:
            v286._record_snapshot_success(
                broker, [{"symbol": "BTC-USD", "quantity": 2.0, "authoritative_balance": True}]
            )
        except RuntimeError as exc:
            assert str(exc) == "v285_authoritative_snapshot_record_failed"
        else:
            raise AssertionError("canonical writer error must fail")
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False
    assert broker._nija_authoritative_position_raw_generation_v286 == 1
    assert broker._nija_authoritative_position_failure_serial_v286 == 1
