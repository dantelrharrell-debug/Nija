"""Offline regression: duplicate-call lookup errors must block outbound submissions.

No provider connection, test call, or production state is used.
"""
from datetime import datetime, timezone
from unittest import mock
import sqlite3

import render_outreach_autodial as dial


def _now():
    return datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)


def test_missing_phone_key_blocks():
    with mock.patch.object(dial, "phone_key", return_value=""):
        assert dial._active_call_exists("+12065550123", _now()) is True


def test_database_query_failure_blocks():
    con = mock.MagicMock()
    con.__enter__.return_value = con
    con.execute.side_effect = sqlite3.OperationalError("history unavailable")
    with (
        mock.patch.object(dial, "_connect", return_value=con),
        mock.patch.object(dial, "_ensure_schema"),
        mock.patch.object(dial, "phone_key", return_value="opaque-phone-key"),
    ):
        assert dial._active_call_exists("+12065550123", _now()) is True


def test_history_without_prior_call_does_not_falsely_block():
    con = mock.MagicMock()
    con.__enter__.return_value = con
    con.execute.return_value.fetchone.return_value = None
    with (
        mock.patch.object(dial, "_connect", return_value=con),
        mock.patch.object(dial, "_ensure_schema"),
        mock.patch.object(dial, "phone_key", return_value="opaque-phone-key"),
    ):
        assert dial._active_call_exists("+12065550123", _now()) is False


def test_active_call_blocks():
    con = mock.MagicMock()
    con.__enter__.return_value = con
    con.execute.return_value.fetchone.return_value = {
        "latest_event_type": "call.answered",
        "updated_at": _now().isoformat(),
    }
    with (
        mock.patch.object(dial, "_connect", return_value=con),
        mock.patch.object(dial, "_ensure_schema"),
        mock.patch.object(dial, "phone_key", return_value="opaque-phone-key"),
    ):
        assert dial._active_call_exists("+12065550123", _now()) is True
