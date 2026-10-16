import json
import tempfile
import unittest
from unittest.mock import Mock
from founding_onboarding_mail import InvitationOutbox, invitation_body

class InvitationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.outbox = InvitationOutbox(self.temp.name + "/outbox.db")
    def tearDown(self):
        self.temp.cleanup()
    def test_requires_verified_approval(self):
        with self.assertRaises(ValueError):
            self.outbox.enqueue("a1","user@example.com",approved=True)
    def test_repeat_event_not_duplicate(self):
        a = self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        self.assertEqual(a,self.outbox.enqueue("a1","user@example.com",approved=True,verified=True))
        with self.outbox.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM onboarding_mail").fetchone()[0],1)
    def test_changed_recipient_denied(self):
        self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        with self.assertRaises(ValueError):
            self.outbox.enqueue("a1","other@example.com",approved=True,verified=True)
    def test_provider_accepted_only_not_delivered(self):
        key=self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        response=Mock()
        response.read.return_value=json.dumps({"id":"email_123"}).encode()
        opener=Mock(return_value=response)
        self.assertEqual(self.outbox.send(key,sender="support@nijaaitrading.com",api_key="fake",now=1000,opener=opener),"accepted")
        self.assertEqual(self.outbox.send(key,sender="support@nijaaitrading.com",api_key="fake",now=1000,opener=opener),"accepted")
        opener.assert_called_once()
    def test_failure_retry(self):
        key=self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        self.assertEqual(self.outbox.send(key,sender="support@nijaaitrading.com",api_key="fake",now=1000,opener=Mock(side_effect=OSError())),"retry")
    def test_inflight_lease_prevents_second_send(self):
        key=self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        with self.outbox.connect() as db:
            db.execute("UPDATE onboarding_mail SET status='sending',retry_at=1120 WHERE key=?", (key,))
        opener=Mock()
        self.assertEqual(self.outbox.send(key,sender="support@nijaaitrading.com",api_key="fake",now=1100,opener=opener),"sending")
        opener.assert_not_called()
    def test_expired_sending_lease_requeued_after_worker_crash(self):
        key=self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        with self.outbox.connect() as db:
            db.execute("UPDATE onboarding_mail SET status='sending',retry_at=1120 WHERE key=?", (key,))
        self.assertEqual(self.outbox.due_keys(now=1100),[])
        self.assertEqual(self.outbox.due_keys(now=1120),[key])
    def test_permanent_provider_error_fails_closed(self):
        key=self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        err=OSError("invalid_sender")
        err.code=403
        opener=Mock(side_effect=err)
        self.assertEqual(self.outbox.send(key,sender="support@nijaaitrading.com",api_key="fake",now=1000,opener=opener),"failed")
        self.assertEqual(self.outbox.send(key,sender="support@nijaaitrading.com",api_key="fake",now=2000,opener=opener),"failed")
        opener.assert_called_once()
    def test_http_408_timeout_is_retryable_using_identical_idempotency_key(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)
        timeout = OSError("request timed out")
        timeout.code = 408
        response = Mock()
        response.read.return_value = json.dumps({"id": "email_timeout_recovered"}).encode()
        opener = Mock(side_effect=[timeout, response])
        args = {"sender": "support@nijaaitrading.com", "api_key": "fake", "opener": opener}
        self.assertEqual(self.outbox.send(key, now=1000, **args), "retry")
        self.assertEqual(self.outbox.due_keys(now=1059), [])
        self.assertEqual(self.outbox.send(key, now=1059, **args), "retry")
        self.assertEqual(self.outbox.send(key, now=1060, **args), "accepted")
        self.assertEqual(opener.call_count, 2)
        first = opener.call_args_list[0].args[0]
        second = opener.call_args_list[1].args[0]
        self.assertEqual(first.get_header("Idempotency-key"), key)
        self.assertEqual(second.get_header("Idempotency-key"), key)
        self.assertEqual(self.outbox.send(key, now=2000, **args), "accepted")
        self.assertEqual(opener.call_count, 2)

    def test_http_429_is_retryable_without_premature_resend(self):
        key = self.outbox.enqueue("a2", "user2@example.com", approved=True, verified=True)
        limited = OSError("rate limit")
        limited.code = 429
        opener = Mock(side_effect=limited)
        args = {"sender": "support@nijaaitrading.com", "api_key": "fake", "opener": opener}
        self.assertEqual(self.outbox.send(key, now=1000, **args), "retry")
        self.assertEqual(self.outbox.send(key, now=1059, **args), "retry")
        opener.assert_called_once()

    def test_delivery_status_and_due_work(self):
        key=self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        self.assertEqual(self.outbox.due_keys(now=1000),[key])
        with self.outbox.connect() as db:
            db.execute("UPDATE onboarding_mail SET status='accepted',provider_id='email_123' WHERE key=?", (key,))
        self.assertTrue(self.outbox.record_provider_event("email_123","email.delivered"))
        with self.outbox.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM onboarding_mail WHERE key=?", (key,)).fetchone()[0],"delivered")
        self.assertEqual(self.outbox.due_keys(now=1000),[])
    def test_bounce_suppression(self):
        key=self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        with self.outbox.connect() as db:
            db.execute("UPDATE onboarding_mail SET status='accepted',provider_id='email_123' WHERE key=?", (key,))
        self.assertTrue(self.outbox.record_provider_event("email_123","email.bounced"))
        with self.outbox.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM onboarding_mail WHERE key=?", (key,)).fetchone()[0],"suppressed")
    def test_no_api_key_instructions(self):
        self.assertIn("Do not enter keys",invitation_body())

    def test_bounce_suppresses_future_events_and_cannot_be_delivered(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)
        with self.outbox.connect() as db:
            db.execute("UPDATE onboarding_mail SET status='accepted',provider_id='mail1' WHERE key=?", (key,))
        self.outbox.record_provider_event("mail1", "email.bounced")
        self.outbox.record_provider_event("mail1", "email.delivered")
        second = self.outbox.enqueue("a2", "user@example.com", approved=True, verified=True)
        opener = Mock()
        self.assertEqual(self.outbox.send(second, sender="support@nijaaitrading.com",
                                         api_key="fake", opener=opener), "suppressed")
        opener.assert_not_called()
        with self.outbox.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM onboarding_mail WHERE key=?", (key,)).fetchone()[0],
                             "suppressed")
        self.assertEqual(self.outbox.alerts()[0]["reason"], "email.bounced")

    def test_early_webhook_survives_response_race(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)
        self.outbox.record_provider_event("early", "email.delivered")
        response = Mock()
        response.read.return_value = b'{"id":"early"}'
        self.assertEqual(self.outbox.send(key, sender="support@nijaaitrading.com", api_key="fake",
                                         opener=Mock(return_value=response)), "delivered")

    def test_late_acceptance_does_not_overwrite_bounce(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)

        def respond(*args, **kwargs):
            self.outbox.record_provider_event("early", "email.bounced")
            response = Mock()
            response.read.return_value = b'{"id":"early"}'
            return response

        self.assertEqual(self.outbox.send(key, sender="support@nijaaitrading.com", api_key="fake",
                                         opener=respond), "suppressed")

    def test_redrive_preserves_key_and_refuses_expired_provider_window(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)
        err = OSError()
        err.code = 403
        self.outbox.send(key, sender="support@nijaaitrading.com", api_key="fake",
                         opener=Mock(side_effect=err), now=1000)
        self.outbox.redrive(key, now=1100)
        self.assertEqual(self.outbox.due_keys(now=1100), [key])
        self.outbox.send(key, sender="support@nijaaitrading.com", api_key="fake",
                         opener=Mock(side_effect=err), now=1100)
        with self.assertRaises(ValueError):
            self.outbox.redrive(key, now=1000 + 24 * 3600)

    def test_retry_after_provider_idempotency_expiry_never_resubmits(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)
        opener = Mock(side_effect=OSError())
        args = dict(sender="support@nijaaitrading.com", api_key="fake", opener=opener)
        self.outbox.send(key, now=1000, **args)
        self.assertEqual(self.outbox.send(key, now=1000 + 24 * 3600, **args), "failed")
        opener.assert_called_once()
        self.assertEqual(self.outbox.alerts()[0]["reason"], "reconcile_before_redrive")

    def test_sustained_outage_and_missing_delivery_alert(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)
        with self.outbox.connect() as db:
            db.execute("UPDATE onboarding_mail SET created_at=1000 WHERE key=?", (key,))
        self.assertEqual(self.outbox.alerts(now=4599), [])
        self.assertEqual(self.outbox.alerts(now=4600)[0]["key"], key)
        response = Mock()
        response.read.return_value = b'{"id":"accepted"}'
        self.outbox.send(key, sender="support@nijaaitrading.com", api_key="fake",
                         opener=Mock(return_value=response), now=4600)
        self.outbox.record_provider_event("accepted", "email.delivered")
        self.assertEqual(self.outbox.alerts(now=9000), [])

    def test_retry_exhaustion_dead_letters_with_actionable_alert(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)
        with self.outbox.connect() as db:
            db.execute("UPDATE onboarding_mail SET attempts=7,first_attempt_at=1000 WHERE key=?", (key,))
        self.assertEqual(self.outbox.send(key, sender="support@nijaaitrading.com", api_key="fake",
                                         opener=Mock(side_effect=OSError()), now=2000), "failed")
        self.assertEqual(self.outbox.alerts()[0]["key"], key)

    def test_legacy_ambiguous_retry_fails_closed(self):
        key = self.outbox.enqueue("a1", "user@example.com", approved=True, verified=True)
        with self.outbox.connect() as db:
            db.execute("UPDATE onboarding_mail SET attempts=1,status='retry' WHERE key=?", (key,))
        opener = Mock()
        self.assertEqual(self.outbox.send(key, sender="support@nijaaitrading.com",
                                         api_key="fake", opener=opener), "failed")
        opener.assert_not_called()

if __name__=="__main__": unittest.main()
