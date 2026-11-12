"""Synthetic-only tests. Run: python3 -m unittest tests/test_synthetic_instructor_debrief.py"""
import unittest
from dataclasses import replace
from decimal import Decimal
from tools.synthetic_instructor_debrief import (
    SYNTHETIC_TRADE, build_debrief, render_text
)


class SyntheticInstructorDebriefTests(unittest.TestCase):
    def test_expected_arithmetic(self):
        report = build_debrief(SYNTHETIC_TRADE)
        self.assertEqual(report["duration_minutes"], Decimal("18"))
        self.assertEqual(report["gross_result"], Decimal("-0.100"))
        self.assertEqual(report["modeled_fees"], Decimal("0.10"))
        self.assertEqual(report["illustrative_net_result"], Decimal("-0.200"))
        self.assertIn("Fictional", render_text(report))
        self.assertIn("Not a broker statement", report["limitations"])

    def test_sell_direction(self):
        report = build_debrief(replace(SYNTHETIC_TRADE, side="SELL"))
        self.assertEqual(report["gross_result"], Decimal("0.100"))

    def test_rejects_naive_time(self):
        with self.assertRaises(ValueError):
            build_debrief(replace(SYNTHETIC_TRADE, entry_time="2026-01-01T12:00:00"))

    def test_rejects_negative_fee(self):
        with self.assertRaises(ValueError):
            build_debrief(replace(SYNTHETIC_TRADE, entry_fee=Decimal("-1")))

    def test_rejects_reverse_timestamps(self):
        with self.assertRaises(ValueError):
            build_debrief(replace(SYNTHETIC_TRADE, exit_time="2026-01-01T11:00:00+00:00"))

    def test_rejects_invalid_quantity(self):
        with self.assertRaises(ValueError):
            build_debrief(replace(SYNTHETIC_TRADE, quantity=Decimal("0")))


if __name__ == "__main__":
    unittest.main()
