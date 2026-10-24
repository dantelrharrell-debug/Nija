"""Fail-closed tests for explicit entry admission dispatch boundary."""
import unittest
from unittest.mock import Mock, patch

from bot.account_admission_dispatch_boundary_v470 import consume_verified_entry
from bot.account_order_admission import AccountOrderAdmission, AdmissionDenied, Reservation
from bot.order_admission_policy import Candidate


class DispatchBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.candidate = Candidate("platform:kraken", "fingerprint", 1, "a" * 64)

    def test_missing_installed_store_denied(self):
        with self.assertRaises(AdmissionDenied):
            consume_verified_entry(None, self.candidate)

    def test_missing_candidate_denied(self):
        admission = object.__new__(AccountOrderAdmission)
        with self.assertRaises(AdmissionDenied):
            consume_verified_entry(admission, None)

    def test_reservation_consumed_exactly_once(self):
        admission = object.__new__(AccountOrderAdmission)
        reservation = Reservation("token", self.candidate)
        with patch.object(AccountOrderAdmission, "reserve", return_value=reservation) as reserve:
            with patch.object(AccountOrderAdmission, "consume") as consume:
                consume_verified_entry(admission, self.candidate)
        reserve.assert_called_once_with(self.candidate)
        consume.assert_called_once_with(reservation)

    def test_reservation_failure_blocks_consume(self):
        admission = object.__new__(AccountOrderAdmission)
        with patch.object(AccountOrderAdmission, "reserve", side_effect=AdmissionDenied("blocked")):
            with patch.object(AccountOrderAdmission, "consume") as consume:
                with self.assertRaises(AdmissionDenied):
                    consume_verified_entry(admission, self.candidate)
        consume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
