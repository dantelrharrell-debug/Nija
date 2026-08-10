from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from bot.broker_manager import KrakenBroker


class KrakenWriterAuthorityGateV91Tests(unittest.TestCase):
    def _broker(self) -> KrakenBroker:
        broker = object.__new__(KrakenBroker)
        broker.account_identifier = "PLATFORM"
        broker.connected = True
        broker._connection_already_complete = True
        broker.last_connection_error = ""
        return broker

    def test_nonce_initialization_does_not_fabricate_heartbeat_without_writer(self) -> None:
        broker = self._broker()
        original = os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE")
        os.environ.pop("NIJA_WRITER_HEARTBEAT_ACTIVE", None)
        nonce_module = ModuleType("bot.distributed_nonce_manager")
        get_nonce_manager = MagicMock()
        nonce_module.get_distributed_nonce_manager = get_nonce_manager
        try:
            with (
                patch(
                    "bot.execution_authority_context.assert_distributed_writer_authority",
                    side_effect=RuntimeError("runtime_not_acquired"),
                ),
                patch.dict(
                    sys.modules,
                    {"bot.distributed_nonce_manager": nonce_module},
                ),
            ):
                ready = broker._initialize_nonce_manager()
                heartbeat_was_fabricated = "NIJA_WRITER_HEARTBEAT_ACTIVE" in os.environ
        finally:
            if original is None:
                os.environ.pop("NIJA_WRITER_HEARTBEAT_ACTIVE", None)
            else:
                os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = original

        self.assertFalse(ready)
        self.assertFalse(broker.connected)
        self.assertFalse(broker._connection_already_complete)
        self.assertIn("runtime_not_acquired", broker.last_connection_error)
        self.assertFalse(heartbeat_was_fabricated)
        get_nonce_manager.assert_not_called()

    def test_nonce_initialization_never_writes_heartbeat_telemetry(self) -> None:
        broker = self._broker()
        redis_client = MagicMock()
        nonce_manager = SimpleNamespace(
            _redis=SimpleNamespace(_client=redis_client)
        )
        nonce_module = ModuleType("bot.distributed_nonce_manager")
        get_nonce_manager = MagicMock(return_value=nonce_manager)
        nonce_module.get_distributed_nonce_manager = get_nonce_manager

        with (
            patch(
                "bot.execution_authority_context.assert_distributed_writer_authority"
            ) as assert_writer,
            patch.dict(
                sys.modules,
                {"bot.distributed_nonce_manager": nonce_module},
            ),
        ):
            ready = broker._initialize_nonce_manager()

        self.assertTrue(ready)
        assert_writer.assert_called_once_with()
        redis_client.set.assert_not_called()

    def test_connect_treats_nonce_authority_initialization_as_mandatory(self) -> None:
        source = __import__("inspect").getsource(KrakenBroker.connect)
        self.assertIn("if not self._initialize_nonce_manager():", source)
        self.assertIn("return False", source)


if __name__ == "__main__":
    unittest.main()
