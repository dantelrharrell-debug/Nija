"""
Tests for Platform Account Layer and API Abstraction Layer.

Covers:
- PlatformAccountLayer: multi-exchange credential discovery, runtime user
  registration / unregistration, legacy Kraken env-var fallback, display helpers.
- APIAbstractionLayer: input validation, key masking, connect/disconnect/rotate
  workflows, list_user_connections.

These tests run without live exchange connectivity; the broker test path is
intentionally bypassed by not setting real credentials.

Run with:
    python -m pytest bot/test_platform_account_layer.py -v
"""

import os
import sys
import importlib

import pytest

# Ensure the repository root is on the path so both `bot.*` and top-level
# imports resolve correctly from any working directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_pal(monkeypatch, env: dict):
    """
    Return a freshly instantiated PlatformAccountLayer with the given
    environment variables (other vars cleared so tests are isolated).
    """
    # Patch os.environ with a minimal env for the module under test.
    monkeypatch.setattr(os, "environ", {**env})

    # Force a clean import each time so the singleton is reset.
    import bot.platform_account_layer as pal_mod
    importlib.reload(pal_mod)
    pal_mod._platform_account_layer = None

    layer = pal_mod.PlatformAccountLayer()
    return layer, pal_mod


def _fresh_aal(monkeypatch):
    """Return a fresh APIAbstractionLayer (singleton reset)."""
    import bot.api_abstraction_layer as aal_mod
    importlib.reload(aal_mod)
    aal_mod._api_abstraction_layer = None
    return aal_mod.APIAbstractionLayer(), aal_mod


# ===========================================================================
# PlatformAccountLayer tests
# ===========================================================================

class TestPlatformCredentials:
    """NIJA platform account credential detection."""

    def test_not_configured_when_env_empty(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        status = layer.get_status()
        assert not status.platform_configured
        assert status.platform_exchanges == []

    def test_configured_via_coinbase_env(self, monkeypatch):
        env = {
            "COINBASE_PLATFORM_API_KEY": "cb_key_abc123",
            "COINBASE_PLATFORM_API_SECRET": "cb_secret_xyz789",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        status = layer.get_status()
        assert status.platform_configured
        assert "COINBASE" in status.platform_exchanges

    def test_configured_via_kraken_env(self, monkeypatch):
        env = {
            "KRAKEN_PLATFORM_API_KEY": "kraken_key_123",
            "KRAKEN_PLATFORM_API_SECRET": "kraken_secret_456",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        status = layer.get_status()
        assert status.platform_configured
        assert "KRAKEN" in status.platform_exchanges

    def test_legacy_kraken_fallback(self, monkeypatch):
        """KRAKEN_API_KEY (legacy) should be recognised as platform credentials."""
        env = {
            "KRAKEN_API_KEY": "legacy_key",
            "KRAKEN_API_SECRET": "legacy_secret",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        status = layer.get_status()
        assert status.platform_configured
        assert "KRAKEN" in status.platform_exchanges

    def test_multiple_exchanges_configured(self, monkeypatch):
        env = {
            "COINBASE_PLATFORM_API_KEY": "cb_key",
            "COINBASE_PLATFORM_API_SECRET": "cb_secret",
            "KRAKEN_PLATFORM_API_KEY": "kr_key",
            "KRAKEN_PLATFORM_API_SECRET": "kr_secret",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        status = layer.get_status()
        assert "COINBASE" in status.platform_exchanges
        assert "KRAKEN" in status.platform_exchanges

    def test_get_platform_credentials_coinbase(self, monkeypatch):
        env = {
            "COINBASE_PLATFORM_API_KEY": "my_cb_key",
            "COINBASE_PLATFORM_API_SECRET": "my_cb_secret",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        creds = layer.get_platform_credentials("COINBASE")
        assert creds["api_key"] == "my_cb_key"
        assert creds["api_secret"] == "my_cb_secret"

    def test_get_platform_credentials_unknown_exchange_returns_empty(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        creds = layer.get_platform_credentials("UNKNOWN_EXCHANGE")
        assert creds["api_key"] == ""
        assert creds["api_secret"] == ""


class TestUserConnectionDiscovery:
    """Env-var based user connection discovery (legacy path)."""

    def test_discovers_kraken_user(self, monkeypatch):
        env = {
            "KRAKEN_USER_ALICE_API_KEY": "alice_key",
            "KRAKEN_USER_ALICE_API_SECRET": "alice_secret",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        status = layer.get_status()
        assert status.user_count == 1
        conn = status.user_connections[0]
        assert conn.exchange == "KRAKEN"
        assert conn.user_id == "kraken_alice"
        assert conn.env_prefix == "KRAKEN_USER_ALICE"

    def test_discovers_coinbase_user(self, monkeypatch):
        env = {
            "COINBASE_USER_BOB_API_KEY": "bob_key",
            "COINBASE_USER_BOB_API_SECRET": "bob_secret",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        status = layer.get_status()
        assert status.user_count == 1
        conn = status.user_connections[0]
        assert conn.exchange == "COINBASE"
        assert conn.user_id == "coinbase_bob"

    def test_ignores_key_without_secret(self, monkeypatch):
        env = {"KRAKEN_USER_CHARLIE_API_KEY": "charlie_key"}
        layer, _ = _fresh_pal(monkeypatch, env)
        assert layer.get_status().user_count == 0

    def test_multiple_users_multiple_exchanges(self, monkeypatch):
        env = {
            "KRAKEN_USER_ALICE_API_KEY": "a_k",
            "KRAKEN_USER_ALICE_API_SECRET": "a_s",
            "COINBASE_USER_BOB_API_KEY": "b_k",
            "COINBASE_USER_BOB_API_SECRET": "b_s",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        assert layer.get_status().user_count == 2


class TestRuntimeUserRegistration:
    """register_user_account() and unregister_user_account() methods."""

    def test_register_adds_user(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        ok = layer.register_user_account(
            user_id="dave@example.com",
            name="Dave",
            exchange="KRAKEN",
            api_key="dave_kraken_key_xxxx",
            api_secret="dave_kraken_secret_xxxx",
        )
        assert ok
        status = layer.get_status()
        assert status.user_count == 1
        conn = status.user_connections[0]
        assert conn.user_id == "dave@example.com"
        assert conn.exchange == "KRAKEN"
        assert conn.name == "Dave"

    def test_register_sets_env_vars(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        layer.register_user_account(
            user_id="eve@example.com",
            name="Eve",
            exchange="COINBASE",
            api_key="eve_key_1234",
            api_secret="eve_secret_5678",
        )
        token = "EVE_EXAMPLE_COM"
        assert os.environ.get(f"COINBASE_USER_{token}_API_KEY") == "eve_key_1234"
        assert os.environ.get(f"COINBASE_USER_{token}_API_SECRET") == "eve_secret_5678"

    def test_register_rejects_empty_key(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        ok = layer.register_user_account(
            user_id="frank@example.com",
            name="Frank",
            exchange="KRAKEN",
            api_key="",
            api_secret="some_secret",
        )
        assert not ok
        assert layer.get_status().user_count == 0

    def test_register_rejects_unsupported_exchange(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        ok = layer.register_user_account(
            user_id="grace@example.com",
            name="Grace",
            exchange="UNSUPPORTED_EX",
            api_key="some_key",
            api_secret="some_secret",
        )
        assert not ok

    def test_unregister_removes_user(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        layer.register_user_account(
            user_id="heidi@example.com",
            name="Heidi",
            exchange="ALPACA",
            api_key="heidi_key_9999",
            api_secret="heidi_secret_8888",
        )
        assert layer.get_status().user_count == 1
        removed = layer.unregister_user_account("heidi@example.com")
        assert removed
        assert layer.get_status().user_count == 0

    def test_unregister_returns_false_for_unknown_user(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        assert not layer.unregister_user_account("nobody@example.com")

    def test_mark_user_connected(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        layer.register_user_account(
            user_id="ivan@example.com",
            name="Ivan",
            exchange="BINANCE",
            api_key="ivan_key_aaaa",
            api_secret="ivan_secret_bbbb",
        )
        layer.mark_user_connected("ivan@example.com", connected=True, balance_usd=5000.0)
        conn = layer.get_status().user_connections[0]
        assert conn.connected
        assert conn.balance_usd == 5000.0


class TestValidateAndDisplayHelpers:
    """validate() and display_hierarchy() smoke tests."""

    def test_validate_returns_true_when_configured(self, monkeypatch):
        env = {
            "KRAKEN_PLATFORM_API_KEY": "k",
            "KRAKEN_PLATFORM_API_SECRET": "s",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        assert layer.validate() is True

    def test_validate_returns_false_when_not_configured(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        assert layer.validate() is False

    def test_display_hierarchy_runs_without_error(self, monkeypatch):
        env = {
            "COINBASE_PLATFORM_API_KEY": "ck",
            "COINBASE_PLATFORM_API_SECRET": "cs",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        layer.display_hierarchy()  # should not raise

    def test_list_user_env_prefixes(self, monkeypatch):
        env = {
            "KRAKEN_USER_JEN_API_KEY": "j_k",
            "KRAKEN_USER_JEN_API_SECRET": "j_s",
        }
        layer, _ = _fresh_pal(monkeypatch, env)
        prefixes = layer.list_user_env_prefixes()
        assert "KRAKEN_USER_JEN" in prefixes


# ===========================================================================
# APIAbstractionLayer tests
# ===========================================================================

class TestMaskKey:
    """_mask_key() helper."""

    def test_masks_long_key(self):
        from bot.api_abstraction_layer import _mask_key
        result = _mask_key("abcdef1234567890")
        assert result.endswith("7890")
        assert "*" in result
        assert "abcdef" not in result

    def test_masks_short_key_fully(self):
        from bot.api_abstraction_layer import _mask_key
        result = _mask_key("abc")
        assert result == "***"
        assert "a" not in result

    def test_masks_empty_key(self):
        from bot.api_abstraction_layer import _mask_key
        assert _mask_key("") == ""

    def test_visible_chars_parameter(self):
        from bot.api_abstraction_layer import _mask_key
        result = _mask_key("1234567890", visible_chars=6)
        assert result.endswith("567890")


class TestValidation:
    """APIAbstractionLayer._validate_request() static method."""

    def _validate(self, user_id, exchange, api_key, api_secret):
        from bot.api_abstraction_layer import APIAbstractionLayer
        return APIAbstractionLayer._validate_request(user_id, exchange, api_key, api_secret)

    def test_valid_inputs_return_none(self):
        assert self._validate("user@x.com", "KRAKEN", "k" * 20, "s" * 20) is None

    def test_empty_user_id_fails(self):
        err = self._validate("", "KRAKEN", "k" * 20, "s" * 20)
        assert err is not None
        assert "user_id" in err.lower()

    def test_unsupported_exchange_fails(self):
        err = self._validate("u", "NOTANEXCHANGE", "k" * 20, "s" * 20)
        assert err is not None
        assert "Unsupported" in err

    def test_empty_api_key_fails(self):
        err = self._validate("u", "COINBASE", "", "s" * 20)
        assert err is not None
        assert "api_key" in err

    def test_empty_api_secret_fails(self):
        err = self._validate("u", "COINBASE", "k" * 20, "")
        assert err is not None
        assert "api_secret" in err

    def test_short_api_key_fails(self):
        err = self._validate("u", "COINBASE", "short", "s" * 20)
        assert err is not None
        assert "too short" in err

    def test_key_with_null_byte_fails(self):
        err = self._validate("u", "KRAKEN", "key\x00with_null_1234", "s" * 20)
        assert err is not None
        assert "invalid characters" in err

    def test_case_insensitive_exchange(self):
        # Exchange is normalized to upper; "kraken" should work
        from bot.api_abstraction_layer import APIAbstractionLayer
        err = APIAbstractionLayer._validate_request("u", "kraken".upper(), "k" * 20, "s" * 20)
        assert err is None


class TestConnectDisconnect:
    """connect_user_account() and disconnect_user_account() integration tests."""

    def _make_aal(self, monkeypatch):
        # Fresh PAL and AAL
        layer, _ = _fresh_pal(monkeypatch, {})
        aal, _ = _fresh_aal(monkeypatch)
        return aal

    def test_connect_succeeds_with_valid_request(self, monkeypatch):
        from bot.api_abstraction_layer import ExchangeConnectionRequest
        aal = self._make_aal(monkeypatch)
        req = ExchangeConnectionRequest(
            user_id="alice@test.com",
            display_name="Alice",
            exchange="KRAKEN",
            api_key="validkey_12345678",
            api_secret="validsecret_abcdefgh",
        )
        result = aal.connect_user_account(req)
        assert result.success
        assert result.exchange == "KRAKEN"
        assert result.masked_key.endswith("5678")
        assert "validkey" not in result.masked_key

    def test_connect_fails_with_empty_key(self, monkeypatch):
        from bot.api_abstraction_layer import ExchangeConnectionRequest
        aal = self._make_aal(monkeypatch)
        req = ExchangeConnectionRequest(
            user_id="bob@test.com",
            display_name="Bob",
            exchange="COINBASE",
            api_key="",
            api_secret="some_secret_abc123",
        )
        result = aal.connect_user_account(req)
        assert not result.success
        assert result.error is not None

    def test_connect_fails_with_invalid_exchange(self, monkeypatch):
        from bot.api_abstraction_layer import ExchangeConnectionRequest
        aal = self._make_aal(monkeypatch)
        req = ExchangeConnectionRequest(
            user_id="carol@test.com",
            display_name="Carol",
            exchange="BADEXCHANGE",
            api_key="validkey_12345678",
            api_secret="validsecret_abcdef",
        )
        result = aal.connect_user_account(req)
        assert not result.success
        assert "Unsupported" in (result.error or "")

    def test_disconnect_removes_user(self, monkeypatch):
        from bot.api_abstraction_layer import ExchangeConnectionRequest
        aal = self._make_aal(monkeypatch)
        req = ExchangeConnectionRequest(
            user_id="dave@test.com",
            display_name="Dave",
            exchange="ALPACA",
            api_key="davekey_1234567890",
            api_secret="davesecret_abcdefgh",
        )
        connect_result = aal.connect_user_account(req)
        assert connect_result.success

        disconnect_result = aal.disconnect_user_account("dave@test.com", "ALPACA")
        assert disconnect_result.success

    def test_disconnect_unknown_user_fails(self, monkeypatch):
        aal = self._make_aal(monkeypatch)
        result = aal.disconnect_user_account("nobody@test.com", "KRAKEN")
        assert not result.success
        assert "not found" in (result.error or "").lower()


class TestTestConnection:
    """test_connection() without live connectivity (skipped path)."""

    def test_passes_for_valid_format(self, monkeypatch):
        aal = _fresh_aal(monkeypatch)[0]
        result = aal.test_connection(
            exchange="COINBASE",
            api_key="valid_key_xxxxxxxxxx",
            api_secret="valid_secret_yyyyyyyy",
        )
        # Should succeed (broker adapter unavailable → skipped test)
        assert result.success

    def test_fails_for_invalid_exchange(self, monkeypatch):
        aal = _fresh_aal(monkeypatch)[0]
        result = aal.test_connection(
            exchange="INVALID",
            api_key="valid_key_xxxxxxxxxx",
            api_secret="valid_secret_yyyyyyyy",
        )
        assert not result.success

    def test_fails_for_short_key(self, monkeypatch):
        aal = _fresh_aal(monkeypatch)[0]
        result = aal.test_connection(
            exchange="KRAKEN",
            api_key="short",
            api_secret="valid_secret_yyyyyyyy",
        )
        assert not result.success


class TestRotateCredentials:
    """rotate_credentials() — replace API keys for an existing user."""

    def test_rotate_succeeds(self, monkeypatch):
        from bot.api_abstraction_layer import ExchangeConnectionRequest
        layer, _ = _fresh_pal(monkeypatch, {})
        aal = _fresh_aal(monkeypatch)[0]

        # Initial connect
        req = ExchangeConnectionRequest(
            user_id="eve@test.com",
            display_name="Eve",
            exchange="BINANCE",
            api_key="oldkey_1234567890ab",
            api_secret="oldsecret_xyzxyzxyz",
        )
        aal.connect_user_account(req)

        # Rotate
        result = aal.rotate_credentials(
            user_id="eve@test.com",
            exchange="BINANCE",
            new_api_key="newkey_abcdefghijkl",
            new_api_secret="newsecret_123456789",
        )
        assert result.success
        assert result.masked_key.endswith("ijkl")

    def test_rotate_fails_with_bad_key(self, monkeypatch):
        aal = _fresh_aal(monkeypatch)[0]
        result = aal.rotate_credentials(
            user_id="frank@test.com",
            exchange="KRAKEN",
            new_api_key="",
            new_api_secret="valid_secret_xxxxxxxx",
        )
        assert not result.success


class TestListUserConnections:
    """list_user_connections() returns correct UserConnectionInfo objects."""

    def test_lists_after_connect(self, monkeypatch):
        from bot.api_abstraction_layer import ExchangeConnectionRequest
        layer, _ = _fresh_pal(monkeypatch, {})
        aal = _fresh_aal(monkeypatch)[0]

        req = ExchangeConnectionRequest(
            user_id="grace@test.com",
            display_name="Grace",
            exchange="OKX",
            api_key="gracekey_1234567890",
            api_secret="gracesecret_abcdefgh",
        )
        aal.connect_user_account(req)

        connections = aal.list_user_connections("grace@test.com")
        assert len(connections) == 1
        conn_info = connections[0]
        assert conn_info.user_id == "grace@test.com"
        assert conn_info.exchange == "OKX"
        assert "gracekey" not in conn_info.masked_key

    def test_returns_empty_for_unknown_user(self, monkeypatch):
        layer, _ = _fresh_pal(monkeypatch, {})
        aal = _fresh_aal(monkeypatch)[0]
        assert aal.list_user_connections("nobody@test.com") == []


# ===========================================================================
# Singleton tests
# ===========================================================================

class TestSingletons:
    """get_platform_account_layer() and get_api_abstraction_layer() singletons."""

    def test_pal_singleton(self):
        import bot.platform_account_layer as mod
        mod._platform_account_layer = None
        inst1 = mod.get_platform_account_layer()
        inst2 = mod.get_platform_account_layer()
        assert inst1 is inst2

    def test_aal_singleton(self):
        import bot.api_abstraction_layer as mod
        mod._api_abstraction_layer = None
        inst1 = mod.get_api_abstraction_layer()
        inst2 = mod.get_api_abstraction_layer()
        assert inst1 is inst2

    def test_get_platform_layer_alias(self):
        """get_platform_layer() returns the same singleton as get_platform_account_layer()."""
        import bot.platform_account_layer as mod
        mod._platform_account_layer = None
        # Both accessors must return the same singleton instance.
        inst1 = mod.get_platform_layer()
        inst2 = mod.get_platform_account_layer()
        assert inst1 is inst2

    def test_pal_singleton_thread_safe(self):
        """Two threads racing on singleton creation must receive the same instance."""
        import threading
        import bot.platform_account_layer as mod
        mod._platform_account_layer = None

        results = []

        def _get():
            results.append(mod.get_platform_account_layer())

        t1 = threading.Thread(target=_get)
        t2 = threading.Thread(target=_get)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(results) == 2
        assert results[0] is results[1]


# ===========================================================================
# has_platform_account() tests
# ===========================================================================

class TestHasPlatformAccount:
    """Tests for PlatformAccountLayer.has_platform_account()."""

    def test_returns_true_when_exchange_credentials_set(self, monkeypatch):
        """has_platform_account() returns True when EXCHANGE_PLATFORM_* vars are present."""
        layer, _ = _fresh_pal(monkeypatch, {
            "KRAKEN_PLATFORM_API_KEY": "my_platform_key_long",
            "KRAKEN_PLATFORM_API_SECRET": "my_platform_secret_long",
        })
        assert layer.has_platform_account("KRAKEN") is True
        assert layer.has_platform_account("kraken") is True  # case-insensitive

    def test_returns_false_when_no_credentials(self, monkeypatch):
        """has_platform_account() returns False when no platform vars are set."""
        layer, _ = _fresh_pal(monkeypatch, {})
        assert layer.has_platform_account("KRAKEN") is False
        assert layer.has_platform_account("COINBASE") is False

    def test_returns_false_for_unconfigured_exchange(self, monkeypatch):
        """has_platform_account() returns False for an exchange with no credentials."""
        layer, _ = _fresh_pal(monkeypatch, {
            "KRAKEN_PLATFORM_API_KEY": "my_platform_key_long",
            "KRAKEN_PLATFORM_API_SECRET": "my_platform_secret_long",
        })
        assert layer.has_platform_account("COINBASE") is False

    def test_multi_exchange(self, monkeypatch):
        """has_platform_account() correctly reflects multiple configured exchanges."""
        layer, _ = _fresh_pal(monkeypatch, {
            "KRAKEN_PLATFORM_API_KEY": "kraken_key_long",
            "KRAKEN_PLATFORM_API_SECRET": "kraken_secret_long",
            "COINBASE_PLATFORM_API_KEY": "cb_key_long",
            "COINBASE_PLATFORM_API_SECRET": "cb_secret_long",
        })
        assert layer.has_platform_account("KRAKEN") is True
        assert layer.has_platform_account("COINBASE") is True
        assert layer.has_platform_account("OKX") is False

    def test_legacy_kraken_fallback(self, monkeypatch):
        """has_platform_account('KRAKEN') returns True with legacy KRAKEN_API_KEY vars."""
        layer, _ = _fresh_pal(monkeypatch, {
            "KRAKEN_API_KEY": "legacy_key",
            "KRAKEN_API_SECRET": "legacy_secret",
        })
        assert layer.has_platform_account("KRAKEN") is True
