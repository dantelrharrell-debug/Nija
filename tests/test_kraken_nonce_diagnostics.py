"""Regression tests: nonce error diagnostics must not read the platform manager."""
from types import SimpleNamespace

from bot.kraken_nonce_diagnostics import nonce_error_diagnostic


class Manager:
    def __init__(self, expected_key="user-key", nonce=123456):
        self.expected_key = expected_key
        self.nonce = nonce
        self.reads = []

    def get_last_nonce(self, key_id):
        self.reads.append(key_id)
        assert key_id == self.expected_key
        return self.nonce


def test_user_nonce_uses_only_its_own_key():
    manager = Manager()
    broker = SimpleNamespace(nonce_manager=manager, api_key_id="user-key")
    result = nonce_error_diagnostic(broker)
    assert "last_issued_nonce=123456 nonce_scope=account" in result
    assert manager.reads == ["user-key"]


def test_missing_scope_does_not_claim_platform_nonce():
    manager = Manager()
    broker = SimpleNamespace(nonce_manager=manager, api_key_id=None)
    assert "last_issued_nonce=unavailable nonce_scope=unverified" in nonce_error_diagnostic(broker)
    assert manager.reads == []


def test_unavailable_backend_fails_closed_in_diagnostics():
    manager = Manager(nonce=0)
    broker = SimpleNamespace(nonce_manager=manager, api_key_id="user-key")
    result = nonce_error_diagnostic(broker, parenthesized=True)
    assert result == " (last_issued_nonce=unavailable nonce_scope=unverified)"


def test_diagnostic_never_issues_or_resets_nonce():
    class ReadOnlyManager:
        def get_last_nonce(self, key_id):
            raise RuntimeError("Redis unavailable")

        def get_nonce(self, key_id):
            raise AssertionError("must never issue nonce")

        def reset_key(self, key_id):
            raise AssertionError("must never reset nonce")

    broker = SimpleNamespace(nonce_manager=ReadOnlyManager(), api_key_id="user-key")
    assert "nonce_scope=unverified" in nonce_error_diagnostic(broker)
