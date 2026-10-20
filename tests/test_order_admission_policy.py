"""Cold-start, idle and unsafe-state acceptance cases for the proposed contract."""
from dataclasses import replace
import unittest
import importlib.util
from pathlib import Path
import sys

# Load only the pure policy: importing bot also installs runtime hooks.
spec = importlib.util.spec_from_file_location(
    "nija_admission_policy_test", Path(__file__).resolve().parents[1] / "bot/order_admission_policy.py"
)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)
Candidate = policy.Candidate
CurrentFact = policy.CurrentFact
OrderOutcome = policy.OrderOutcome
REQUIRED_CONTROLS = policy.REQUIRED_CONTROLS
evaluate_candidate = policy.evaluate_candidate
NOW = 5000000.0
CANDIDATE = Candidate('platform:kraken', 'synthetic-key-identity', 42, 'a' * 64)
EMPTY = OrderOutcome(CANDIDATE.account, 'none')

def facts():
    return {name: CurrentFact(CANDIDATE, True, NOW, 'test-only') for name in REQUIRED_CONTROLS}

def evaluate(current=None, outcome=EMPTY, candidate=CANDIDATE, now=NOW):
    return evaluate_candidate(candidate, facts() if current is None else current, outcome, now=now)

class AdmissionPolicyTests(unittest.TestCase):

    def test_cold_start_has_no_circular_fill_dependency(self):
        decision = evaluate()
        assert decision.eligible_for_canonical_dispatch is True
        assert decision.execution_evidence_fresh is False
        assert decision.reasons == ()

    def test_42_day_reconciled_history_does_not_expire_current_operational_checks(self):
        event = NOW - 42 * 86400
        outcome = OrderOutcome(CANDIDATE.account, 'verified', event, event + 1, 'old-order', True, True)
        decision = evaluate(outcome=outcome)
        assert decision.eligible_for_canonical_dispatch is True
        assert decision.execution_evidence_fresh is False

    def test_every_control_is_mandatory(self):
        for control in REQUIRED_CONTROLS:
            with self.subTest(control=control):
                current = facts()
                del current[control]
                assert evaluate(current).eligible_for_canonical_dispatch is False

    def test_every_control_requires_verified_boolean(self):
        for control in REQUIRED_CONTROLS:
            for value in [False, None, 1, 'true']:
                with self.subTest(control=control, value=value):
                    current = facts()
                    current[control] = replace(current[control], verified=value)
                    assert evaluate(current).eligible_for_canonical_dispatch is False

    def test_stale_future_and_malformed_facts_block(self):
        for observed in [NOW - 30.001, NOW + 0.001, 0, float('nan'), float('inf'), True]:
            with self.subTest(observed=observed):
                current = facts()
                current['authenticated_account'] = replace(current['authenticated_account'], observed_at=observed)
                assert not evaluate(current).eligible_for_canonical_dispatch

    def test_fact_cannot_cross_account_key_writer_epoch_or_order_terms(self):
        for field, value in [('account', 'user:other:kraken'), ('credential_fingerprint', 'rotated-key'), ('writer_generation', 43), ('intent_digest', 'b' * 64)]:
            with self.subTest(field=field, value=value):
                candidate = replace(CANDIDATE, **{field: value})
                decision = evaluate(candidate=candidate, outcome=replace(EMPTY, account=candidate.account))
                assert not decision.eligible_for_canonical_dispatch
                assert all((reason.endswith('identity_mismatch') for reason in decision.reasons))

    def test_unresolved_or_unrecognized_outcome_blocks(self):
        for state in ['pending', 'unknown', 'failed', 'cancelled', 'acknowledged']:
            with self.subTest(state=state):
                assert not evaluate(outcome=replace(EMPTY, state=state)).eligible_for_canonical_dispatch

    def test_empty_history_cannot_hide_a_real_order(self):
        assert not evaluate(outcome=replace(EMPTY, broker_order_id='actual-order')).eligible_for_canonical_dispatch

    def test_a_fresh_fill_never_substitutes_for_ledger_reconciliation(self):
        outcome = OrderOutcome(CANDIDATE.account, 'verified', NOW - 1, NOW, 'order', True, False)
        assert not evaluate(outcome=outcome).eligible_for_canonical_dispatch

    def test_fill_freshness_retains_exact_1800_second_limit(self):
        for age, expected in [(1800, True), (1800.001, False)]:
            with self.subTest(age=age, expected=expected):
                outcome = OrderOutcome(CANDIDATE.account, 'verified', NOW - age, NOW, 'order', True, True)
                decision = evaluate(outcome=outcome)
                assert decision.eligible_for_canonical_dispatch
                assert decision.execution_evidence_fresh is expected

    def test_fresh_fill_cannot_override_active_stop(self):
        current = facts()
        current['kill_switch_clear'] = replace(current['kill_switch_clear'], verified=False)
        outcome = OrderOutcome(CANDIDATE.account, 'verified', NOW - 1, NOW, 'order', True, True)
        decision = evaluate(current, outcome)
        assert decision.execution_evidence_fresh
        assert not decision.eligible_for_canonical_dispatch

    def test_invalid_clock_is_denied(self):
        for now in [float('nan'), float('inf'), True, 0]:
            with self.subTest(now=now):
                assert not evaluate(now=now).eligible_for_canonical_dispatch

    def test_evaluation_does_not_mutate_supplied_facts(self):
        current = facts()
        before = dict(current)
        evaluate(current)
        assert current == before
