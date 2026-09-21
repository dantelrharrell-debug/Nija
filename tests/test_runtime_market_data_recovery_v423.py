from bot.runtime_market_data_entry_failclosed_v403_patch import _recovery_scan_allowed


def test_recovery_scan_allowed_only_for_core_quality_failure():
    detail = {
        "workers_ok": True,
        "threads_ok": True,
        "timeout_rate_ok": True,
        "data_fresh_ok": True,
        "core_data_quality_ok": False,
        "core_data_failure_rate": 0.7143,
    }
    assert _recovery_scan_allowed(detail) is True


def test_recovery_scan_denied_for_transport_failure():
    detail = {
        "workers_ok": True,
        "threads_ok": True,
        "timeout_rate_ok": False,
        "data_fresh_ok": True,
        "core_data_quality_ok": False,
    }
    assert _recovery_scan_allowed(detail) is False


def test_recovery_scan_not_needed_when_core_quality_healthy():
    detail = {
        "workers_ok": True,
        "threads_ok": True,
        "timeout_rate_ok": True,
        "data_fresh_ok": True,
        "core_data_quality_ok": True,
    }
    assert _recovery_scan_allowed(detail) is False
