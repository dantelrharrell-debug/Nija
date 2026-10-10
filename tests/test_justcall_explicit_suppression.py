"""Regression coverage for explicit JustCall opt-out flags.

A status update containing 'do_not_call': false must never cause suppression.
Only positively asserted suppression flags or statuses are actionable.
"""
from __future__ import annotations

import unittest
from unittest import mock

import render_outreach_extension as extension


class ContactStatusSuppressionTests(unittest.TestCase):
    NUMBER = "+12065550144"

    def _process(self, data):
        payload = {
            "type": "contact.status_updated",
            "data": {"contact_number": self.NUMBER, **data},
        }
        with mock.patch.object(extension, "set_suppression") as update:
            extension._contact_status_suppression(payload)
            return update.call_args_list

    def test_false_do_not_call_does_not_suppress(self):
        self.assertEqual(self._process({"do_not_call": False}), [])

    def test_false_dnd_and_irrelevant_notes_do_not_suppress(self):
        self.assertEqual(
            self._process({"dnd": False, "notes": "Asked about do_not_call policy"}),
            [],
        )

    def test_negative_string_flags_do_not_suppress(self):
        self.assertEqual(
            self._process({"do_not_call": "false", "blacklist": "no"}),
            [],
        )

    def test_explicit_true_suppresses(self):
        calls = self._process({"do_not_call": True})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs["contact_number"], self.NUMBER)
        self.assertTrue(calls[0].kwargs["active"])

    def test_explicit_blocked_status_suppresses(self):
        self.assertEqual(len(self._process({"status": "blocked"})), 1)

    def test_unrelated_event_ignored(self):
        payload = {
            "type": "call.completed",
            "data": {"contact_number": self.NUMBER, "do_not_call": True},
        }
        with mock.patch.object(extension, "set_suppression") as update:
            extension._contact_status_suppression(payload)
            update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
