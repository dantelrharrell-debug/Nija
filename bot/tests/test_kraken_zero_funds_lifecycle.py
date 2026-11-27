"""Joined recovery rehearsal with synthetic exchange events and real local AOF.

This is component integration, not a live-dispatch or exchange certification.
It reuses the authoritative ledger-reader fixtures and calls real duplicate,
fill-classification and reconciliation code. No order method or credential
reader exists in the broker fixture. Python network transport is denied; the
only external process is a private Redis server with TCP disabled.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import socket
import sqlite3
# Only fixed local Redis binaries are spawned; no shell or broker process.
import subprocess  # nosec B404
import time
from types import ModuleType
from typing import Any, Mapping
import unittest
import uuid
from unittest.mock import patch


def _load_fixture_module() -> ModuleType:
    """Reuse the existing accounting fixture without executing bot startup."""
    path = Path(__file__).with_name("test_kraken_ledger_evidence.py")
    spec = importlib.util.spec_from_file_location("_zero_funds_ledger_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = _load_fixture_module()
decisions = fixture.load_pure_module("_zero_funds_decisions", "control/decision_context.py")
fills = fixture.load_pure_module("_zero_funds_fill_truth", "runtime_confirmed_fill_profitability_v328_patch.py")


class PrivateRedis:
    """Real isolated Redis with AOF, reached only through its private Unix socket."""

    def __init__(self) -> None:
        self.server = shutil.which("redis-server")
        self.cli = shutil.which("redis-cli")
        if not self.server or not self.cli:
            raise RuntimeError("Redis tooling required; lifecycle certification must not silently skip")
        self.directory = Path.cwd() / (".lifecycle-redis-" + uuid.uuid4().hex[:8])
        self.socket = self.directory / "r.sock"
        if len(str(self.socket).encode()) >= 104:
            raise RuntimeError("Private Unix socket path too long")
        self.process = None

    def __enter__(self) -> PrivateRedis:
        """Create the isolated state directory and start its server."""
        self.directory.mkdir(mode=0o700)
        try:
            self.start()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_args: object) -> None:
        """Stop the owned server before removing its disposable files."""
        try:
            self.stop()
        finally:
            shutil.rmtree(self.directory)

    def start(self) -> None:
        """Start only the owned server, without a TCP listener or background daemon."""
        # Fixed Redis binary and arguments; the only variable path is owned scratch.
        self.process = subprocess.Popen(  # nosec B603
            [self.server, "--port", "0", "--unixsocket", str(self.socket),
             "--unixsocketperm", "700", "--save", "", "--appendonly", "yes",
             "--appendfsync", "always", "--daemonize", "no", "--dir", str(self.directory)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                output = self.process.communicate(timeout=1)[0]
                raise AssertionError("Private Redis exited before readiness: " + output[-2000:])
            if self.socket.exists():
                try:
                    if self.command("PING") == "PONG":
                        if self.command("CONFIG", "GET", "port") != "port\n0":
                            raise AssertionError("TCP must remain disabled")
                        return
                except subprocess.CalledProcessError:
                    pass
            time.sleep(0.02)
        raise AssertionError("Private Redis did not become responsive")

    def stop(self) -> None:
        """Shut down the owned process; never address a production Redis endpoint."""
        if self.process is not None and self.process.poll() is None:
            try:
                self.command("SHUTDOWN", "NOSAVE")
                self.process.wait(timeout=5)
            finally:
                if self.process.poll() is None:
                    self.process.kill()
                    self.process.wait(timeout=5)
        if self.process is not None and self.process.stdout is not None:
            self.process.stdout.close()

    def restart(self) -> None:
        """Discard server memory and reload the same private append-only files."""
        self.stop()
        if not any(self.directory.rglob("*.aof")):
            raise AssertionError("AOF evidence is missing")
        self.start()

    def command(self, *parts: str | int) -> str:
        """Run a Redis command against the exact private socket, without a shell."""
        # Redis CLI receives a list of arguments and the owned socket; no shell.
        result = subprocess.run(  # nosec B603
            [self.cli, "--raw", "-s", str(self.socket), *(str(part) for part in parts)],
            check=True, capture_output=True, text=True, timeout=3,
        ).stdout.rstrip("\n")
        if result.startswith("ERR "):
            raise AssertionError("Private Redis command failed")
        return result

    def set(self, key: str, value: str, *, nx: bool = False, px: int | None = None) -> bool:
        """Use the real Redis SET NX/PX behavior required by the registry."""
        parts = ["SET", key, value]
        if nx:
            parts.append("NX")
        if px is not None:
            parts.extend(("PX", px))
        return self.command(*parts) == "OK"

    def get(self, key: str) -> str | None:
        """Read a reservation from the isolated shared store."""
        return self.command("GET", key) or None

    def eval(self, script: str, key_count: int, *parts: str | int) -> int:
        """Run the production registry's unchanged atomic Lua operation."""
        return int(self.command("EVAL", script, key_count, *parts))


class KrakenZeroFundsLifecycleTests(unittest.TestCase):
    """Join durable intent ownership, fill truth, protection and ledger recovery."""

    def setUp(self) -> None:
        self.ledger = fixture.KrakenLedgerEvidenceTests()
        self.ledger.setUp()
        self.addCleanup(self.ledger.tearDown)
        self.context = decisions.UserDecisionContext(
            user_id="alice", account_id="synthetic-account", broker="kraken",
            portfolio_id="offline-portfolio", strategy_signal_id="offline-signal",
            trade_id="offline-trade", execution_mode="live", environment="production",
        )
        # The LIVE context above tests mandatory shared authority. It is only
        # data supplied to the registry; no runtime, dispatch or broker is loaded.
        self.connect_guard = self.enterContext(patch.object(
            socket.socket, "connect", side_effect=AssertionError("broker transport forbidden"),
        ))
        self.dns_guard = self.enterContext(patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("broker DNS forbidden"),
        ))

    def assert_entries_remain_blocked(self, registry: Any, handle: Any) -> None:
        """A duplicate may not acquire ownership even after the registry restarts."""
        allowed, duplicate = registry.reserve(self.context, symbol="BTC-USD", direction="long")
        self.assertFalse(allowed)
        self.assertEqual(duplicate.token, "")
        self.assertEqual(registry.get_state(handle), "submitted_pending")

    def assert_diagnostic_only(self, row: Mapping[str, Any]) -> None:
        """One successful accounting observation never becomes general admission."""
        field = "position_ledger_reconciliation"
        trusted = {key: "fixture-provider:" + key for key in fixture.REQUIRED}
        trusted[field] = self.ledger.binding.provider_id
        certificate = fixture.evaluate_pretrade_certificate(
            {field: row}, account=fixture.SCOPE, trusted_provider_ids=trusted,
            now_epoch=fixture.NOW,
        )
        self.assertFalse(row["authorizes_orders"])
        self.assertTrue(row["read_only"])
        self.assertFalse(certificate["certified"])
        self.assertFalse(certificate["authorizes_orders"])
        self.assertIn("operator_authorization", certificate["missing"])

    def test_ambiguous_ack_partial_fill_rejected_protection_restart_and_reconciliation(self) -> None:
        """Unknown execution survives restart; only matching history clears the evidence gap."""
        case = self.ledger
        final_order = case.broker.data["ClosedOrders"][fixture.BUY]
        protections = case.broker.data["OpenOrders"]
        deposit = case.broker.data["Ledgers"]["deposit"]
        with sqlite3.connect(case.path) as db:
            db.executescript("""
                DELETE FROM trade_ledger;
                DELETE FROM open_positions;
                DELETE FROM ledger_open_orders;
                DELETE FROM pending_kraken_closes;
            """)
        case.broker.data = {
            "TradesHistory": {}, "ClosedOrders": {}, "Ledgers": {"deposit": deposit}, "OpenOrders": {},
        }
        case.broker.balance = {"ZUSD": "1000"}
        with PrivateRedis() as backend:
            registry = decisions.UserScopedIdempotencyRegistry(redis_client=backend)
            allowed, handle = registry.reserve(self.context, symbol="BTC-USD", direction="long")
            self.assertTrue(allowed)
            self.assertTrue(handle.shared_required)
            self.assertTrue(registry.mark_state(handle, "submitted_pending"))
            case.update("ledger_evidence_state", "unresolved_submission_count", 1)

            # A plausible price on an ACK cannot create a fill or a position.
            with self.assertRaisesRegex(RuntimeError, "ACK timeout pending reconciliation"):
                fills._normalize_dict_fill({
                    "status": "pending", "order_id": fixture.BUY, "price": 100, "size_usd": 200,
                }, symbol="BTC-USD", side="buy")
            with sqlite3.connect(case.path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM trade_ledger").fetchone(), (0,))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM open_positions").fetchone(), (0,))
            case.denied("ledger_snapshot_state_unverified")
            self.assert_entries_remain_blocked(registry, handle)

            # One independently persisted synthetic fill arrives, with its
            # matching cash-ledger debits. The still-open order is not complete.
            case.insert("trade_ledger", {
                "user_id": "alice", "symbol": "BTC-USD", "side": "BUY", "action": "OPEN",
                "quantity": "1", "size_usd": "100", "fee": "1", "position_id": "internal-lot-1",
                "exchange_trade_id": fixture.TID, "exchange_order_id": fixture.BUY,
                "order_id": "internal-order-1",
            })
            case.insert("open_positions", {
                "user_id": "alice", "position_id": "internal-lot-1", "symbol": "BTC-USD",
                "side": "long", "quantity": "1", "status": "open",
                "stop_order_id": fixture.STOP, "take_profit_order_id": fixture.PROFIT,
            })
            case.insert("ledger_open_orders", {
                "exchange_order_id": fixture.BUY, "pair": "BTCUSD", "side": "buy",
                "ordertype": "limit", "price": "100", "volume": "2", "executed": "1",
            })
            case.broker.data["TradesHistory"][fixture.TID] = {
                "ordertxid": fixture.BUY, "pair": "XXBTZUSD", "type": "buy",
                "vol": "1", "cost": "100", "fee": "1", "time": 100,
            }
            partial = fixture.order(side="buy", volume="2", executed="1", trades=[fixture.TID])
            partial.update(cost="100", fee="1")
            case.broker.data["OpenOrders"][fixture.BUY] = partial
            case.broker.data["Ledgers"].update({
                "buy-base": {"asset": "XXBT", "amount": "1", "fee": "0", "type": "trade", "refid": fixture.TID},
                "buy-quote": {"asset": "ZUSD", "amount": "-100", "fee": "1", "type": "trade", "refid": fixture.TID},
            })
            case.broker.balance = {"XXBT": "1", "ZUSD": "899"}
            with self.assertRaisesRegex(RuntimeError, "ACK timeout pending reconciliation"):
                fills._normalize_dict_fill({
                    "status": "partially_filled", "order_id": fixture.BUY,
                    "filled_price": 100, "filled_volume": 1,
                }, symbol="BTC-USD", side="buy")
            case.denied("ledger_snapshot_state_unverified")
            self.assert_entries_remain_blocked(registry, handle)

            # Actual Redis shutdown/start discards process memory. A new
            # registry must recover the pending hold from its persisted AOF.
            old_pid = backend.process.pid
            backend.restart()
            self.assertNotEqual(backend.process.pid, old_pid)
            registry = decisions.UserScopedIdempotencyRegistry(redis_client=backend)
            self.assert_entries_remain_blocked(registry, handle)
            stale = decisions.IdempotencyReservationHandle(handle.key, "stale-owner", True)
            self.assertFalse(registry.mark_state(stale, "reconciled_filled"))
            self.assert_entries_remain_blocked(registry, handle)

            # Complete synthetic history arrives as two exact fills. The
            # independently persisted SQLite contract contains the same fills,
            # fee debits and balances; ACK fields do not populate these rows.
            second_trade = "TEEEEE-EEEEE-EEEEEE"
            case.insert("trade_ledger", {
                "user_id": "alice", "symbol": "BTC-USD", "side": "BUY", "action": "OPEN",
                "quantity": "1", "size_usd": "100", "fee": "1", "position_id": "internal-lot-1",
                "exchange_trade_id": second_trade, "exchange_order_id": fixture.BUY,
                "order_id": "internal-order-1",
            })
            trade = case.broker.data["TradesHistory"][fixture.TID]
            case.broker.data["TradesHistory"][second_trade] = dict(trade)
            final_order["trades"].append(second_trade)
            case.broker.data["ClosedOrders"][fixture.BUY] = final_order
            case.broker.data["OpenOrders"] = {fixture.PROFIT: protections[fixture.PROFIT]}
            cash = case.broker.data["Ledgers"]
            cash["buy-base-2"] = dict(cash["buy-base"], refid=second_trade)
            cash["buy-quote-2"] = dict(cash["buy-quote"], refid=second_trade)
            case.broker.balance = {"XXBT": "2", "ZUSD": "798"}
            case.update("open_positions", "quantity", "2")
            with sqlite3.connect(case.path) as db:
                db.execute("DELETE FROM ledger_open_orders WHERE exchange_order_id=?", (fixture.BUY,))
            case.insert("ledger_open_orders", {
                "exchange_order_id": fixture.PROFIT, "pair": "BTCUSD", "side": "sell",
                "ordertype": "take-profit", "price": "100", "volume": "2", "executed": "0",
            })
            case.update("ledger_evidence_state", "unresolved_submission_count", 0)
            self.assertEqual(fills._normalize_dict_fill({
                "status": "closed", "order_id": fixture.BUY,
                "filled_price": 100, "filled_volume": 2,
            }, symbol="BTC-USD", side="buy"), (100, 200))

            # A rejected/missing stop remains a hard reconciliation failure;
            # the still-pending duplicate fence is not released on that failure.
            case.denied("protective_order_not_open")
            self.assert_entries_remain_blocked(registry, handle)

            case.broker.data["OpenOrders"][fixture.STOP] = protections[fixture.STOP]
            case.insert("ledger_open_orders", {
                "exchange_order_id": fixture.STOP, "pair": "BTCUSD", "side": "sell",
                "ordertype": "stop-loss", "price": "100", "volume": "2", "executed": "0",
            })
            before = case.path.read_bytes()
            observed = case.provider()()
            self.assertEqual(case.path.read_bytes(), before)
            self.assertTrue(observed["fills_reconciled"])
            self.assertEqual(observed["positions"]["internal-lot-1"]["quantity"], "2")
            self.assert_diagnostic_only(observed)

            # Provider reconstruction reads the durable SQLite state afresh.
            # Repeated observations do not add fills, positions or orders.
            self.assert_diagnostic_only(case.provider()())
            self.assertEqual(case.path.read_bytes(), before)
            self.assertTrue(registry.mark_state(handle, "reconciled_filled"))
            backend.restart()
            recovered = decisions.UserScopedIdempotencyRegistry(redis_client=backend)
            self.assertEqual(recovered.get_state(handle), "reconciled_filled")
            self.assertFalse(recovered.reserve(self.context, symbol="BTC-USD", direction="long")[0])
            self.assertEqual({endpoint for endpoint, _, _ in case.broker.calls}, {
                "GetApiKeyInfo", "Balance", "TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders",
            })
        self.connect_guard.assert_not_called()
        self.dns_guard.assert_not_called()

    def test_restart_rejects_stale_quantity_or_orphan_protection_without_releasing_intent(self) -> None:
        """Durable ownership remains held when recovered accounting cannot be certified."""
        case = self.ledger
        with PrivateRedis() as backend:
            registry = decisions.UserScopedIdempotencyRegistry(redis_client=backend)
            allowed, handle = registry.reserve(self.context, symbol="BTC-USD", direction="long")
            self.assertTrue(allowed)
            self.assertTrue(registry.mark_state(handle, "submitted_pending"))
            backend.restart()
            registry = decisions.UserScopedIdempotencyRegistry(redis_client=backend)
            case.update("ledger_evidence_state", "observed_at_epoch", fixture.NOW - 61)
            case.denied("source_timestamp_invalid_or_stale")
            self.assert_entries_remain_blocked(registry, handle)
            case.update("ledger_evidence_state", "observed_at_epoch", fixture.NOW - 10)
            case.update("open_positions", "quantity", "1")
            case.denied("ledger_position_fill_quantity_mismatch")
            self.assert_entries_remain_blocked(registry, handle)
            case.update("open_positions", "quantity", "2")
            case.broker.data["OpenOrders"]["OFFFFF-FFFFF-FFFFFF"] = fixture.order("stop-loss")
            case.denied("ledger_broker_open_orders_mismatch")
            self.assert_entries_remain_blocked(registry, handle)
        self.connect_guard.assert_not_called()
        self.dns_guard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
