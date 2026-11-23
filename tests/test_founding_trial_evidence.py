"""Synthetic verification adapter tests. No real broker or Stripe account."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from founding_trial_ledger import FoundingTrialLedger
from founding_trial_evidence import BrokerExecution, UnverifiedFill, verify_and_record_first_fill

FILL_TIME = datetime(2026, 11, 23, 16, 0, tzinfo=timezone.utc)
NOW = FILL_TIME + timedelta(minutes=1)


class Executions:
    def __init__(self, record):
        self.record = record

    def retrieve_execution(self, execution_id):
        return self.record


class Accounts:
    def __init__(self, owner):
        self.owner = owner

    def owner_of(self, brokerage_account_id):
        return self.owner


@pytest.fixture
def ledger(tmp_path):
    return FoundingTrialLedger(tmp_path / 'evidence.db')


@pytest.fixture
def evidence():
    return BrokerExecution('fill-1', 'account-1', 'live', 'filled', '0.05', FILL_TIME)


def invoke(ledger, evidence, **kwargs):
    args = dict(
        ledger=ledger, member_id='member-1', execution_id='fill-1',
        brokerage_account_id='account-1', executions=Executions(evidence),
        accounts=Accounts('member-1'), now=NOW,
    )
    args.update(kwargs)
    return verify_and_record_first_fill(**args)


def test_verified_live_fill_creates_exact_window(ledger, evidence):
    result = invoke(ledger, evidence)
    assert result.starts_at == FILL_TIME.isoformat()
    assert result.ends_at == (FILL_TIME + timedelta(days=14)).isoformat()


def test_evidence_is_retrieved_not_client_trusted(ledger, evidence):
    with pytest.raises(UnverifiedFill):
        invoke(ledger, evidence, executions=Executions(None))
    assert ledger.get('member-1') is None


@pytest.mark.parametrize('patch', [
    {'environment': 'paper'}, {'environment': 'sandbox'}, {'status': 'submitted'},
    {'status': 'partially_filled'}, {'status': 'canceled'}, {'filled_quantity': '0'},
    {'filled_quantity': '-1'}, {'filled_quantity': 'NaN'}, {'filled_quantity': 'Infinity'},
    {'filled_quantity': 'banana'}, {'execution_id': 'fill-other'},
    {'brokerage_account_id': 'account-other'},
    {'executed_at': FILL_TIME + timedelta(days=1)},
    {'executed_at': datetime(2026, 11, 23, 16)},
])
def test_unverified_evidence_never_starts_trial(ledger, evidence, patch):
    with pytest.raises(UnverifiedFill):
        invoke(ledger, replace(evidence, **patch))
    assert ledger.get('member-1') is None


def test_owner_mismatch_rejected(ledger, evidence):
    with pytest.raises(UnverifiedFill):
        invoke(ledger, evidence, accounts=Accounts('member-2'))
    assert ledger.get('member-1') is None


def test_missing_readers_fail_closed(ledger, evidence):
    with pytest.raises(UnverifiedFill):
        invoke(ledger, evidence, executions=object())
    assert ledger.get('member-1') is None


def test_reader_outage_fails_closed(ledger, evidence):
    class Outage:
        def retrieve_execution(self, _):
            raise ConnectionError('down')
    with pytest.raises(UnverifiedFill, match='unavailable'):
        invoke(ledger, evidence, executions=Outage())
    assert ledger.get('member-1') is None


def test_replay_does_not_restart_clock(ledger, evidence):
    first = invoke(ledger, evidence)
    assert invoke(ledger, evidence, now=NOW + timedelta(hours=3)) == first


def test_canceled_member_cannot_restart_clock(ledger, evidence):
    ledger.cancel('member-1')
    assert invoke(ledger, evidence).state == 'canceled'


def test_naive_now_fails_closed(ledger, evidence):
    with pytest.raises(UnverifiedFill):
        invoke(ledger, evidence, now=datetime(2026, 11, 23, 16, 1))
