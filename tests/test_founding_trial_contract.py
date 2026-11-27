"""Source-only deterministic tests; no Stripe, broker, or production mutations."""
from datetime import datetime, timedelta, timezone
import pytest

from founding_trial_contract import TRIAL_DURATION_DAYS, trial_window_from_authoritative_fill


def test_first_fill_window_is_exactly_14_days():
    first_fill = datetime(2026, 11, 23, 16, 12, 5, tzinfo=timezone.utc)
    window = trial_window_from_authoritative_fill(first_fill)
    assert TRIAL_DURATION_DAYS == 14
    assert window.starts_at == first_fill
    assert window.ends_at == datetime(2026, 12, 7, 16, 12, 5, tzinfo=timezone.utc)


def test_offset_fill_normalizes_to_utc_without_changing_instant():
    utc_minus_eight = timezone(timedelta(hours=-8))
    first_fill = datetime(2026, 11, 23, 8, 12, 5, tzinfo=utc_minus_eight)
    window = trial_window_from_authoritative_fill(first_fill)
    assert window.starts_at == datetime(2026, 11, 23, 16, 12, 5, tzinfo=timezone.utc)
    assert window.ends_at - window.starts_at == timedelta(days=14)


@pytest.mark.parametrize("value", [None, "2026-11-23", 0, datetime(2026, 11, 23, 8)])
def test_missing_or_untrusted_timestamp_format_rejected(value):
    with pytest.raises(ValueError, match="timezone-aware"):
        trial_window_from_authoritative_fill(value)


def test_daylight_saving_transition_does_not_shorten_14_day_window():
    first_fill = datetime(2027, 3, 8, 9, 30, tzinfo=timezone(timedelta(hours=-8)))
    window = trial_window_from_authoritative_fill(first_fill)
    assert window.ends_at - window.starts_at == timedelta(days=14)
