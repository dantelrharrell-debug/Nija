from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot import runtime_capital_publication_monotonicity_v170_patch as patch


def _snapshot(*, balances, real=100.0, computed_at=None):
    return SimpleNamespace(
        broker_balances=dict(balances),
        broker_count=len(balances),
        expected_brokers=3,
        real_capital=real,
        computed_at=computed_at or datetime.now(timezone.utc),
        is_stale=False,
    )


def _status(*, accepted=True, stale=False, timestamp=None, expiry=None, reason="accepted"):
    ts = timestamp or datetime.now(timezone.utc)
    return SimpleNamespace(
        accepted=accepted,
        stale=stale,
        reason=reason,
        timestamp=ts,
        expiry=expiry or (ts + timedelta(seconds=90)),
    )


def test_snapshot_complete_counts_legitimate_zero_balance_entry():
    authority = SimpleNamespace(_expected_brokers=3, _opportunistic=False)
    snap = _snapshot(balances={"kraken": 100.0, "coinbase": 0.0, "okx": 0.0})

    complete, contributed, required = patch._snapshot_complete(authority, snap)

    assert complete is True
    assert contributed == 3
    assert required == 3


def test_snapshot_complete_rejects_two_of_three_entries():
    authority = SimpleNamespace(_expected_brokers=3, _opportunistic=False)
    snap = _snapshot(balances={"coinbase": 95.0, "okx": 0.0})

    complete, contributed, required = patch._snapshot_complete(authority, snap)

    assert complete is False
    assert contributed == 2
    assert required == 3


def test_status_current_never_extends_original_expiry():
    now = datetime.now(timezone.utc)
    status = _status(timestamp=now - timedelta(seconds=100), expiry=now - timedelta(seconds=10))

    assert patch._status_current(status, now=now) is False


def test_same_publication_requires_exact_timestamp_identity():
    ts = datetime.now(timezone.utc)
    snap = _snapshot(balances={"kraken": 1, "coinbase": 1, "okx": 0}, computed_at=ts)

    assert patch._same_publication(snap, _status(timestamp=ts)) is True
    assert patch._same_publication(snap, _status(timestamp=ts + timedelta(microseconds=1))) is False


def test_canonical_snapshot_for_csm_prefers_current_complete_authority(monkeypatch):
    ts = datetime.now(timezone.utc)
    incoming = _snapshot(balances={"coinbase": 95.0, "okx": 0.0}, real=95.0, computed_at=ts)
    canonical = _snapshot(
        balances={"kraken": 242.0, "coinbase": 95.0, "okx": 0.0},
        real=337.0,
        computed_at=ts,
    )
    status = _status(timestamp=ts, expiry=ts + timedelta(seconds=90))
    authority = SimpleNamespace(
        _expected_brokers=3,
        _opportunistic=False,
        get_snapshot_publication_status=lambda: status,
        get_typed_snapshot=lambda: canonical,
    )

    fake_module = SimpleNamespace(get_capital_authority=lambda: authority)
    real_import = patch.importlib.import_module

    def fake_import(name):
        if name == "bot.capital_authority":
            return fake_module
        return real_import(name)

    monkeypatch.setattr(patch.importlib, "import_module", fake_import)

    selected, reason = patch._canonical_snapshot_for_csm(incoming)

    assert selected is canonical
    assert reason == "canonical_authority_publication"
