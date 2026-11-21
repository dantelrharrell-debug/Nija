"""Offline tests using synthetic records only."""
import hashlib
import json
import subprocess
import sys
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.rehearse_kraken_opening_period import read_pinned, rehearse


class OpeningPeriodTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ledger = Path(temp.name) / "current.db"
        self.backup = Path(temp.name) / "reference.db"
        db = sqlite3.connect(self.ledger)
        db.executescript("""
            CREATE TABLE pending_kraken_closes(order_id,symbol,side,fill_price,filled_usd,exit_fee,
                user_id,verification_level,account_scope,broker,state,reason,matched_position_id);
            CREATE TABLE open_positions(user_id,status);
        """)
        for i in range(13):
            db.execute("INSERT INTO pending_kraken_closes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (f"O{i:05}-ABCDE-123456", "BTC-USD", "sell", 5, 2, 1, "platform", "observed",
                        "platform:kraken", "kraken", "pending", "missing_position", None))
        db.commit()
        db.close()
        shutil.copyfile(self.ledger, self.backup)
        self.digest = hashlib.sha256(self.backup.read_bytes()).hexdigest()
        self.boundary = dict(account_scope="platform:kraken", wallet="default", cutoff=20, coverage_start=8,
                             coverage_end=40, opening_balances={"USD": "1", "BTC": "0.00000001", "BABY": "0.00000002"},
                             history_cursor_exhausted=True, writer_fenced_through_interval=True,
                             intent_inventory_complete=True, movements=[], outstanding_intents=[])
        self.left, self.right = (self.inventory(i) for i in (10, 30))

    def inventory(self, start):
        results = (
            ("BalanceEx", {k: {"balance": v, "hold_trade": "0"} for k, v in self.boundary["opening_balances"].items()}),
            ("OpenOrders", {"open": {}, "cursor": {}}), ("OpenPositions", {}))
        return dict(diagnostic_only=True, inventory_read_succeeded=True, trading_authorized=False,
                    account_scope_asserted_by_caller="platform:kraken", request_id=f"{start:032x}",
                    observations={k: dict(started_at=start+i, finished_at=start+i+1, result=v)
                                  for i, (k,v) in enumerate(results)})

    def compare(self):
        return rehearse(self.boundary, self.left, self.right, self.ledger, self.backup, self.digest)

    def test_replay_keeps_unknown_attribution_and_preserves_both_databases(self):
        result = self.compare()
        self.assertEqual(result, self.compare())
        self.assertEqual(result["opening_inventory"]["BTC"],
                         {"quantity": "1E-8", "cost_basis": None, "strategy_id": None})
        self.assertEqual(result["historical_exceptions_preserved"], 13)
        self.assertFalse(result["period_created"] or result["authorizes_orders"])
        for path in (self.ledger, self.backup):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.digest)

    def test_changed_exception_denies(self):
        with sqlite3.connect(self.ledger) as db:
            db.execute("UPDATE pending_kraken_closes SET fill_price=3 WHERE rowid=1")
        with self.assertRaisesRegex(ValueError, "historical_exceptions_changed"):
            self.compare()

    def test_movements_and_incomplete_sources_deny(self):
        for field, value in (("movements", ["deposit", "withdrawal"]), ("outstanding_intents", ["intent"]),
                             ("coverage_end", 31), ("cutoff", 8), ("history_cursor_exhausted", False),
                             ("writer_fenced_through_interval", False), ("intent_inventory_complete", False)):
            with self.subTest(field=field):
                original = self.boundary[field]
                self.boundary[field] = value
                with self.assertRaises(ValueError):
                    self.compare()
                self.boundary[field] = original

    def test_inventory_disagreement_denies(self):
        for endpoint, result in (("OpenOrders", {"open": {"order": {}}, "cursor": {}}),
                                 ("OpenOrders", {"open": {}, "cursor": {"next": "more"}}),
                                 ("OpenPositions", {"position": {}}),
                                 ("BalanceEx", {"USD": {"balance": "1", "hold_trade": "0"}})):
            with self.subTest(endpoint=endpoint):
                self.right = self.inventory(30)
                self.right["observations"][endpoint]["result"] = result
                with self.assertRaises(ValueError):
                    self.compare()

    def test_duplicate_json_key_and_unpinned_input_deny(self):
        path = self.ledger.parent / "source.json"
        raw = b'{"a":1,"a":2}'
        path.write_bytes(raw)
        for digest in ("0"*64, hashlib.sha256(raw).hexdigest()):
            with self.assertRaises(ValueError):
                read_pinned(path, digest)


    def test_cli_checks_pins_and_prints_only_counts(self):
        args = [sys.executable, "-BS", "-m", "scripts.rehearse_kraken_opening_period",
                "--ledger", str(self.ledger), "--backup", str(self.backup), "--backup-sha256", self.digest]
        pins = []
        for name, content in (("before", self.left), ("after", self.right), ("boundary", self.boundary)):
            if name == "boundary":
                content.update(inventory_sha256=pins.copy(), historical_sha256=self.digest)
            path = self.ledger.parent / (name + ".json")
            path.write_text(json.dumps(content))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            args.extend(["--" + name, str(path), "--" + name + "-sha256", digest])
            pins.append(digest)
        passed = subprocess.run(args, capture_output=True, check=True)
        self.assertEqual(passed.stderr, b"")
        report = json.loads(passed.stdout)
        self.assertNotIn("opening_inventory", report)
        self.assertEqual(report["historical_exceptions_preserved"], 13)
        args[-1] = "0" * 64
        denied = subprocess.run(args, capture_output=True, check=False)
        self.assertEqual(denied.returncode, 2)
        self.assertEqual(json.loads(denied.stdout)["comparison"], "denied")


    def test_unpaginated_order_inventory_needs_matching_request_mode(self):
        observation = self.right["observations"]["OpenOrders"]
        observation["result"] = {"open": {}}
        with self.assertRaises(ValueError):
            self.compare()
        observation["request_mode"] = "all_unfiltered_no_limit"
        self.assertEqual(self.compare()["comparison"], "supplied_inputs_match")
        observation["result"]["cursor"] = {"next": "more"}
        with self.assertRaises(ValueError):
            self.compare()
