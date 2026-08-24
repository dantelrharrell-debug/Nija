from __future__ import annotations

import importlib


def test_authority_errors_are_not_authentication_failures():
    v218 = importlib.import_module("bot.failure_mode_auth_classification_v218_patch")

    assert v218._is_authentication_failure("execution authority not granted") is False
    assert v218._is_authentication_failure("authority heartbeat expired") is False
    assert v218._is_authentication_failure("runtime authority lifecycle pending") is False


def test_explicit_authentication_failures_remain_protected():
    v218 = importlib.import_module("bot.failure_mode_auth_classification_v218_patch")

    assert v218._is_authentication_failure("401 Unauthorized") is True
    assert v218._is_authentication_failure("authentication failed") is True
    assert v218._is_authentication_failure("invalid api key") is True
    assert v218._is_authentication_failure("EAPI:Invalid key") is True
    assert v218._is_authentication_failure("invalid signature") is True


def test_classifier_preserves_non_auth_failure_taxonomy():
    manager = importlib.import_module("bot.failure_mode_manager")
    v218 = importlib.import_module("bot.failure_mode_auth_classification_v218_patch")

    assert v218._classify("execution authority not granted", manager.FailureType.UNKNOWN_ERROR) == manager.FailureType.UNKNOWN_ERROR
    assert v218._classify("request timed out", manager.FailureType.UNKNOWN_ERROR) == manager.FailureType.TIMEOUT
    assert v218._classify("429 rate limit exceeded", manager.FailureType.UNKNOWN_ERROR) == manager.FailureType.RATE_LIMIT
    assert v218._classify("401 Unauthorized", manager.FailureType.UNKNOWN_ERROR) == manager.FailureType.INVALID_CREDENTIALS
