from __future__ import annotations

from bot import runtime_kraken_read_contention_recovery_v290_patch as v290


class KrakenReadLockBusy(RuntimeError):
    pass


def test_local_contention_classifier_is_exact():
    assert v290._local_contention(KrakenReadLockBusy("Kraken read lock busy after 3.00s for Balance"))
    assert not v290._local_contention(RuntimeError("EAPI:Invalid key"))
    assert not v290._local_contention(RuntimeError("invalid nonce"))


def test_retry_read_recovers_local_contention(monkeypatch):
    monkeypatch.setattr(v290, "_retry_sleep_s", lambda attempt, identity: 0.0)
    monkeypatch.setattr(v290, "_retry_budget_s", lambda: 10.0)
    calls = {"count": 0}

    def operation():
        calls["count"] += 1
        if calls["count"] < 3:
            raise KrakenReadLockBusy("Kraken read lock busy after 3.00s for Balance")
        return {"ok": True}

    assert v290._retry_read(operation, "USER:test", "Balance") == {"ok": True}
    assert calls["count"] == 3


def test_retry_read_does_not_retry_real_exchange_error(monkeypatch):
    monkeypatch.setattr(v290, "_retry_sleep_s", lambda attempt, identity: 0.0)
    calls = {"count": 0}

    def operation():
        calls["count"] += 1
        raise RuntimeError("EAPI:Invalid key")

    try:
        v290._retry_read(operation, "PLATFORM", "Balance")
    except RuntimeError as exc:
        assert "Invalid key" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    assert calls["count"] == 1
