from __future__ import annotations

from contextlib import ExitStack, contextmanager
import sys
import types
import unittest
from unittest.mock import Mock, patch

from bot import broker_integration


class _FakeNonceManager:
    lease_version = 7

    def __init__(self) -> None:
        self.key_id = None

    def ensure_writer_lock(self, key_id: str) -> None:
        self.key_id = key_id

    def get_nonce(self, key_id: str) -> int:
        if key_id != self.key_id:
            raise AssertionError("nonce requested for a different API key")
        return 123456


@contextmanager
def _configured_adapter(response, *, authority_error=None):
    api_instances = []
    wrapped_clients = []
    nonce_manager = _FakeNonceManager()

    class FakeAPI:
        def __init__(self, *, key, secret) -> None:
            self.key = key
            self.secret = secret
            self._nonce = None
            api_instances.append(self)

    class FakeKrakenAPI:
        def __init__(self, api) -> None:
            wrapped_clients.append(api)

    krakenex = types.ModuleType("krakenex")
    krakenex.API = FakeAPI
    pykrakenapi = types.ModuleType("pykrakenapi")
    pykrakenapi.KrakenAPI = FakeKrakenAPI

    adapter = broker_integration.KrakenBrokerAdapter(
        api_key="fixture-key", api_secret="fixture-secret"
    )
    adapter._kraken_api_call = Mock(return_value=response)

    def assert_startup_authority() -> None:
        if authority_error is not None:
            raise authority_error

    with ExitStack() as stack:
        stack.enter_context(patch.dict(
            sys.modules, {"krakenex": krakenex, "pykrakenapi": pykrakenapi}
        ))
        stack.enter_context(patch.object(
            broker_integration, "assert_startup_write_authority",
            side_effect=assert_startup_authority,
        ))
        stack.enter_context(patch.object(
            broker_integration, "_get_distributed_nonce_manager",
            return_value=nonce_manager,
        ))
        stack.enter_context(patch.object(
            broker_integration, "_make_distributed_nonce_key_id",
            return_value="fixture-key-id",
        ))
        stack.enter_context(patch.object(
            broker_integration, "_EXEC_STATE_CONTROLLER_AVAILABLE", False,
        ))
        stack.enter_context(patch.object(
            broker_integration, "_ExecutionStateController", None,
        ))
        stack.enter_context(patch(
            "bot.kraken_order_validator.verify_per_api_key_execution",
            return_value=True,
        ))
        yield adapter, api_instances, wrapped_clients, nonce_manager


class TestKrakenAdapterConnection(unittest.TestCase):
    def test_connected_probe_uses_client_with_nonce_authority(self) -> None:
        with _configured_adapter({"error": [], "result": {"USD": "1.00"}}) as (
            adapter, api_instances, wrapped_clients, nonce_manager,
        ):
            self.assertTrue(adapter.connect())
            self.assertEqual(len(api_instances), 1)
            self.assertEqual(wrapped_clients, api_instances)
            self.assertIs(api_instances[0]._nonce, adapter._nonce_generator)
            self.assertEqual(api_instances[0]._nonce(), 123456)
            self.assertIs(adapter._distributed_nonce_manager, nonce_manager)
            adapter._kraken_api_call.assert_called_once_with("Balance")

    def test_invalid_kraken_authentication_stays_disconnected(self) -> None:
        with _configured_adapter({
            "error": ["EAPI:Invalid key"],
            "result": {},
        }) as (adapter, _api_instances, _wrapped_clients, _nonce_manager):
            self.assertFalse(adapter.connect())
            adapter._kraken_api_call.assert_called_once_with("Balance")

    def test_startup_writer_authority_denial_prevents_private_probe(self) -> None:
        with _configured_adapter(
            {"error": [], "result": {}},
            authority_error=RuntimeError("writer authority unavailable"),
        ) as (adapter, _api_instances, _wrapped_clients, _nonce_manager):
            self.assertFalse(adapter.connect())
            self.assertIsNone(adapter.api)
            adapter._kraken_api_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
