from __future__ import annotations

import importlib


def _v219():
    return importlib.import_module("bot.kill_switch_false_auth_recovery_v219_patch")


def test_exact_legacy_authority_misclassification_is_eligible():
    ok, detail = _v219()._false_auth_signature(
        {
            "source": "FAILURE_MODE_MANAGER",
            "reason": "INVALID_CREDENTIALS: execution authority not granted",
        }
    )
    assert ok is True
    assert "authority" in detail.lower()


def test_real_authentication_stop_is_never_eligible():
    ok, detail = _v219()._false_auth_signature(
        {
            "source": "FAILURE_MODE_MANAGER",
            "reason": "INVALID_CREDENTIALS: 401 Unauthorized invalid api key",
        }
    )
    assert ok is False
    assert detail == "embedded_error_not_authority" or detail == "real_authentication_evidence_present"


def test_manual_risk_and_unknown_sources_are_never_eligible():
    for source in ("MANUAL", "UI", "CLI", "GLOBAL_RISK_CONTROLLER", "AUTO_TRIGGER", "FILE_SYSTEM", ""):
        ok, _ = _v219()._false_auth_signature(
            {
                "source": source,
                "reason": "INVALID_CREDENTIALS: execution authority not granted",
            }
        )
        assert ok is False


def test_invalid_credentials_without_authority_evidence_is_not_eligible():
    ok, detail = _v219()._false_auth_signature(
        {
            "source": "FAILURE_MODE_MANAGER",
            "reason": "INVALID_CREDENTIALS: malformed account configuration",
        }
    )
    assert ok is False
    assert detail == "embedded_error_not_authority"
