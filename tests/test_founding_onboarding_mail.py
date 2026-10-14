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
    def test_permanent_provider_error_fails_closed(self):
        key=self.outbox.enqueue("a1","user@example.com",approved=True,verified=True)
        err=OSError("invalid_sender")
        err.code=403
        opener=Mock(side_effect=err)
        self.assertEqual(self.outbox.send(key,sender="support@nijaaitrading.com",api_key="fake",now=1000,opener=opener),"failed")
        self.assertEqual(self.outbox.send(key,sender="support@nijaaitrading.com",api_key="fake",now=2000,opener=opener),"failed")
        opener.assert_called_once()
    def test_no_api_key_instructions(self):
        self.assertIn("Do not enter keys",invitation_body())

if __name__=="__main__": unittest.main()
