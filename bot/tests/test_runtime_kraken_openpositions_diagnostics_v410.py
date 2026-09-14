from __future__ import annotations

import logging

from bot import runtime_kraken_openpositions_diagnostics_v410_patch as v410
from bot import runtime_kraken_margin_canonical_coverage_v366_patch as v366


def test_exception_classification_is_bounded_and_does_not_return_message():
    samples = {
        "Kraken API circuit breaker OPEN — trading paused": "circuit_breaker_open",
        "Kraken nonce readiness gate blocked API call": "nonce_authority_unready",
        "writer authority is not valid": "writer_authority_unready",
        "EAPI:Permission denied": "api_permission_denied",
        "EAPI:Invalid key": "api_authentication_rejected",
        "EAPI:Invalid nonce": "kraken_invalid_nonce",
        "EAPI:Rate limit exceeded": "kraken_rate_limited",
        "read timed out": "transport_timeout",
        "connection reset": "transport_failure",
        "opaque failure SECRET-DO-NOT-LOG": "unclassified_exception",
    }
    for message, expected in samples.items():
        category = v410._classify_exception(Exception(message))
        assert category == expected
        assert "SECRET-DO-NOT-LOG" not in category


def test_private_call_wrapper_rethrows_and_redacts_exception_message(caplog, monkeypatch):
    secret = "super-secret-api-material"

    def original_private_call(_broker):
        def call(method, params=None):
            raise Exception(f"EAPI:Permission denied {secret}")
        return call

    monkeypatch.setattr(v366, "_private_call", original_private_call)
    assert v410._patch_private_call() is True

    wrapped = v366._private_call(object())
    with caplog.at_level(logging.ERROR):
        try:
            wrapped("OpenPositions", {"docalcs": "true", "secret": secret})
        except Exception as exc:
            assert secret in str(exc)  # original exception is preserved for its caller
        else:
            raise AssertionError("expected the original exception to be rethrown")

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "category=api_permission_denied" in rendered
    assert "message_redacted=true" in rendered
    assert secret not in rendered


def test_non_openpositions_failure_is_not_logged(caplog, monkeypatch):
    def original_private_call(_broker):
        def call(method, params=None):
            raise RuntimeError("network secret detail")
        return call

    monkeypatch.setattr(v366, "_private_call", original_private_call)
    assert v410._patch_private_call() is True
    wrapped = v366._private_call(object())

    with caplog.at_level(logging.ERROR):
        try:
            wrapped("Balance")
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected the original exception to be rethrown")

    assert not any("KRAKEN_OPENPOSITIONS_DIAGNOSTIC_V410" in record.getMessage() for record in caplog.records)
