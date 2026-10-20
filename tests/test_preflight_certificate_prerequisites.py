"""Offline certificate regressions; importing this test never starts the bot."""
import importlib.util
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "bot" / "preflight_observability.py"
SPEC = importlib.util.spec_from_file_location("offline_preflight_certificate", SOURCE)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_complete_preflight_is_diagnostic_only():
    facts = dict.fromkeys(preflight.REQUIRED_PREFLIGHT, True)
    assert all(preflight.certificate_from_independent_evidence(facts).values())
    report = preflight.observe_preflight(facts)
    assert report["preflight_operational_ready"] is True
    assert report["activation_allowed"] is False
    assert report["last_execution_evidence_status"] == "unknown"


@pytest.mark.parametrize("field", preflight.REQUIRED_PREFLIGHT)
@pytest.mark.parametrize("value", [False, None, 1, "true", "missing"])
def test_every_safety_prerequisite_requires_literal_true(field, value):
    facts = dict.fromkeys(preflight.REQUIRED_PREFLIGHT, True)
    if value == "missing":
        facts.pop(field)
    else:
        facts[field] = value
    certificate = preflight.certificate_from_independent_evidence(facts)
    assert not all(certificate.values())
    report = preflight.observe_preflight(facts, {"verified": True})
    assert report["preflight_operational_ready"] is False
    assert report["activation_allowed"] is False
    assert field in report["preflight_missing_attestations"]


def test_empty_evidence_does_not_certify_account():
    assert not any(preflight.certificate_from_independent_evidence({}).values())
