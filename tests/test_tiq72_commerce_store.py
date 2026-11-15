"""Offline TIQ72 persistence tests: python -m unittest tests.test_tiq72_commerce_store"""
import sqlite3
import unittest
from tiq72_commerce_store import Tiq72Store, CommerceDenied

class Tiq72CommerceStoreTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.store=Tiq72Store(self.db)
        self.run=self.store.save_run("adult-1","v515-72-decisions",
            {"challenges":[[{"action":"wait","stop":None} for _ in range(12)] for _ in range(6)]},
            {"score":50})
        self.rid=self.store.reserve(self.run,"adult-1",True)
        self.store.attach_session(self.rid,"cs_test_sample_12345678")

    def test_adult_and_owner_required(self):
        with self.assertRaises(CommerceDenied):
            self.store.reserve(self.run,"adult-1",False)
        with self.assertRaises(CommerceDenied):
            self.store.reserve(self.run,"other",True)

    def test_reservation_idempotent(self):
        self.assertEqual(self.rid,self.store.reserve(self.run,"adult-1",True))

    def test_payment_requires_reconciliation(self):
        with self.assertRaises(CommerceDenied):
            self.store.record_verified_event("evt1","checkout.session.completed",self.rid,
                                             "cs_test_sample_12345678")
        with self.assertRaises(CommerceDenied):
            self.store.get_report(self.rid,"adult-1")

    def test_grant_duplicate_and_ownership(self):
        args=("evt1","checkout.session.completed",self.rid,"cs_test_sample_12345678")
        self.assertTrue(self.store.record_verified_event(*args,verified_paid=True))
        self.assertFalse(self.store.record_verified_event(*args,verified_paid=True))
        self.store.save_report(self.rid,{"result":"educational"})
        self.assertEqual(self.store.get_report(self.rid,"adult-1")["result"],"educational")
        with self.assertRaises(CommerceDenied):
            self.store.get_report(self.rid,"other")

    def test_refund_revokes_and_replay_cannot_restore(self):
        session="cs_test_sample_12345678"
        self.store.record_verified_event("evt1","checkout.session.completed",self.rid,session,verified_paid=True)
        self.store.save_report(self.rid,{"result":"educational"})
        self.store.record_verified_event("evt2","charge.refunded",self.rid,session,verified_reversal=True)
        self.store.record_verified_event("evt3","checkout.session.completed",self.rid,session,verified_paid=True)
        with self.assertRaises(CommerceDenied):
            self.store.get_report(self.rid,"adult-1")

    def test_live_session_rejected(self):
        with self.assertRaises(CommerceDenied):
            self.store.attach_session(self.rid,"cs_live_123456789")

    def test_terminal_reservation_cannot_be_reattached(self):
        session="cs_test_sample_12345678"
        self.store.record_verified_event("evt1","checkout.session.completed",self.rid,session,verified_paid=True)
        with self.assertRaises(CommerceDenied):
            self.store.attach_session(self.rid,session)

    def test_event_id_cannot_be_reused_for_different_reservation(self):
        session="cs_test_sample_12345678"
        self.assertTrue(self.store.record_verified_event("evt_unique","checkout.session.completed",
            self.rid,session,verified_paid=True))
        second_run=self.store.save_run("adult-1","v515-72-decisions",
            {"challenges":[[{"action":"wait","stop":None} for _ in range(12)] for _ in range(6)]},
            {"score":51})
        second=self.store.reserve(second_run,"adult-1",True)
        self.store.attach_session(second,"cs_test_other_12345678")
        with self.assertRaisesRegex(CommerceDenied,"event_identity_conflict"):
            self.store.record_verified_event("evt_unique","checkout.session.completed",
                second,"cs_test_other_12345678",verified_paid=True)

    def test_invalid_run_shape(self):
        with self.assertRaises(CommerceDenied):
            self.store.save_run("adult-1","v515-72-decisions",{"challenges":[[]]},{})

if __name__=="__main__":
    unittest.main()
