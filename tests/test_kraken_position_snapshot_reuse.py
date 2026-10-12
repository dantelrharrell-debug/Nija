"""Regression tests for exact, current Kraken snapshot reuse without timestamp renewal."""
from __future__ import annotations

import time
from types import SimpleNamespace

import bot.position_sync_failure_truth_v98_patch as v98
import bot.runtime_authoritative_position_coverage_v285_patch as v285
import bot.runtime_kraken_position_refresh_liveness_v286_patch as v286
import bot.runtime_kraken_startup_phase_handoff_v306_patch as v306


def _broker(kind='kraken'):
    return SimpleNamespace(connected=True, broker_type=kind)


def _rows(quantity=0.25):
    return [{
        'symbol': 'BTC-USD', 'quantity': quantity, 'entry_price': 50000,
        'cost_basis': 50000 * quantity, 'tradable': True,
        'pricing_verified': True, 'raw_asset': 'XXBT',
        'authoritative_balance': True,
    }]


def test_second_publication_keeps_exact_raw_proof_current():
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    original_generation = broker._nija_authoritative_position_raw_generation_v286
    assert v306._current_authoritative_rows(broker)[0] is True

    observed = broker._nija_authoritative_position_snapshot_at_monotonic_v285
    assert v98._publish_v285_snapshot_if_loaded(broker, rows) is True
    assert broker._nija_authoritative_position_snapshot_generation_v285 == original_generation
    assert broker._nija_authoritative_position_raw_generation_v286 == original_generation
    assert broker._nija_authoritative_position_snapshot_at_monotonic_v285 == observed
    assert v306._current_authoritative_rows(broker)[0] is True
    assert tuple(broker._nija_authoritative_position_raw_rows_v286) == tuple(rows)


def test_different_response_never_retags_prior_raw_evidence():
    broker = _broker()
    v286._record_snapshot_success(broker, _rows(0.25))
    old_gen = broker._nija_authoritative_position_raw_generation_v286
    assert v98._publish_v285_snapshot_if_loaded(broker, _rows(0.50)) is False
    assert broker._nija_authoritative_position_raw_generation_v286 == old_gen
    ok, _rows_result, _age, _max_age, reason = v306._current_authoritative_rows(broker)
    assert ok is True
    assert reason == 'current_balance_snapshot'


def test_existing_raw_generation_mismatch_remains_blocked():
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    broker._nija_authoritative_position_raw_generation_v286 -= 1
    old_raw_gen = broker._nija_authoritative_position_raw_generation_v286
    assert v98._publish_v285_snapshot_if_loaded(broker, rows) is False
    assert broker._nija_authoritative_position_raw_generation_v286 == old_raw_gen


def test_missing_or_non_kraken_raw_proof_never_relinked():
    broker = _broker('coinbase')
    rows = _rows()
    assert v285._record_snapshot_success(broker, rows)
    assert v98._publish_v285_snapshot_if_loaded(broker, rows) is True
    assert not hasattr(broker, '_nija_authoritative_position_raw_generation_v286')

    missing = _broker('kraken')
    assert v285._record_snapshot_success(missing, rows)
    assert v98._publish_v285_snapshot_if_loaded(missing, rows) is True
    assert not hasattr(missing, '_nija_authoritative_position_raw_generation_v286')


def test_invalid_response_fails_closed_and_does_not_retag_raw_rows():
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    raw_generation = broker._nija_authoritative_position_raw_generation_v286
    assert v98._publish_v285_snapshot_if_loaded(
        broker, [{'symbol': '', 'quantity': 0}]
    ) is False
    assert broker._nija_authoritative_position_raw_generation_v286 == raw_generation


def test_empty_authenticated_balance_is_not_a_phantom_held_position():
    broker = _broker()
    v286._record_snapshot_success(broker, [])
    assert v98._publish_v285_snapshot_if_loaded(broker, []) is True
    ok, _rows_result, _age, _max_age, reason = v306._current_authoritative_rows(broker)
    assert ok is False
    assert reason == 'raw_rows_empty'


def test_stale_rows_cannot_renew_observation_time():
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    observed = time.monotonic() - v285._snapshot_max_age_s() - 1
    broker._nija_authoritative_position_snapshot_at_monotonic_v285 = observed
    generation = broker._nija_authoritative_position_snapshot_generation_v285
    assert v98._publish_v285_snapshot_if_loaded(broker, rows) is False
    assert broker._nija_authoritative_position_snapshot_at_monotonic_v285 == observed
    assert broker._nija_authoritative_position_snapshot_generation_v285 == generation
    assert v306._current_authoritative_rows(broker)[0] is False


def test_concurrently_advanced_generation_is_rejected(monkeypatch):
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    original = v285._snapshot_status

    def racing_status(target):
        result = original(target)
        target._nija_authoritative_position_snapshot_generation_v285 += 1
        return result

    monkeypatch.setattr(v285, '_snapshot_status', racing_status)
    raw_generation = broker._nija_authoritative_position_raw_generation_v286
    assert v98._publish_v285_snapshot_if_loaded(broker, rows) is False
    assert broker._nija_authoritative_position_raw_generation_v286 == raw_generation


def test_canonical_rows_must_match_raw_evidence():
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    broker._nija_authoritative_position_snapshot_rows_v285 = ()
    assert v98._publish_v285_snapshot_if_loaded(broker, rows) is False
