"""Offline regression tests: no Kraken requests, secrets or production writes."""
import unittest
from datetime import datetime, timedelta, timezone
from bot.kraken_activation_status_v1 import State, REQUIRED_OBSERVATIONS
from bot.kraken_activation_evidence_v1 import Evidence, TrustContext, verify_evidence
from bot.kraken_activation_transitions_v1 import transition

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
TRUST = TrustContext("account-A", "commit-A", "sha256:image-A", "epoch-A",
                     {p: "reviewer" for p in REQUIRED_OBSERVATIONS})

def record(provider, **changes):
    fields = dict(provider=provider, account_scope="account-A",
                  release_sha="commit-A", image_digest="sha256:image-A",
                  deployment_epoch="epoch-A", observed_at=NOW-timedelta(seconds=10),
                  expires_at=NOW+timedelta(seconds=10),
                  payload=b"redacted-payload", signature=b"test-signature",
                  signer_role="reviewer")
    fields.update(changes)
    return Evidence(**fields)

class EvidenceTests(unittest.TestCase):
    def test_all_valid_with_injected_verifier(self):
        valid, errors = verify_evidence({p:record(p) for p in REQUIRED_OBSERVATIONS},
                                        TRUST, NOW, lambda _: True)
        self.assertEqual(len(valid), 13)
        self.assertFalse(errors)

    def test_missing_each_provider(self):
        for omitted in REQUIRED_OBSERVATIONS:
            with self.subTest(omitted=omitted):
                valid, errors = verify_evidence(
                    {p:record(p) for p in REQUIRED_OBSERVATIONS if p != omitted},
                    TRUST, NOW, lambda _: True)
                self.assertEqual(len(valid), 12)
                self.assertIn("missing:"+omitted, errors)

    def test_reject_stale_scope_epoch_signature_and_future(self):
        cases = [
            {"observed_at": NOW-timedelta(hours=1)},
            {"account_scope":"other"}, {"release_sha":"other"},
            {"image_digest":"other"}, {"deployment_epoch":"old"},
            {"signer_role":"other"}, {"observed_at":NOW+timedelta(seconds=1)},
            {"signature":b""},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                valid, _ = verify_evidence({"account_identity":record("account_identity",**changes)},
                                            TRUST, NOW, lambda _: True)
                self.assertFalse(valid)

    def test_verifier_rejection_and_exception_fail_closed(self):
        for verifier in (lambda _: False, lambda _: 1/0):
            valid, _ = verify_evidence({"account_identity":record("account_identity")},
                                        TRUST, NOW, verifier)
            self.assertFalse(valid)

    def test_missing_verifier_rejected(self):
        with self.assertRaises(ValueError):
            verify_evidence({}, TRUST, NOW, None)

class TransitionTests(unittest.TestCase):
    def test_revoked_approval_and_critical_loss_stop(self):
        self.assertEqual(transition(State.CONTROLLED, State.READY_FOR_APPROVAL,
                                    approval_revoked=True).state, State.PROTECTIVE_STOP)
        for name in ("writer_lease", "nonce_sequence", "protective_exit_readback",
                     "kill_switch_clear", "position_ledger_reconciliation"):
            self.assertEqual(transition(State.CONTROLLED, State.VERIFYING,
                            missing_observations=frozenset({name})).state, State.PROTECTIVE_STOP)

    def test_restart_invalidates_evidence(self):
        self.assertEqual(transition(State.CONTROLLED, State.CONTROLLED,
                                    restarted=True).state, State.RECOVERY)

    def test_no_synthetic_controlled_or_direct_stop_clear(self):
        self.assertEqual(transition(State.VERIFYING, State.CONTROLLED).state,
                         State.READY_FOR_APPROVAL)
        self.assertEqual(transition(State.PROTECTIVE_STOP, State.CONTROLLED,
                                    authenticated_gate=True).state, State.VERIFYING)

    def test_no_transition_authorizes_orders(self):
        for previous in State:
            for proposed in State:
                self.assertFalse(transition(previous, proposed).authorizes_orders)

if __name__ == "__main__":
    unittest.main()
