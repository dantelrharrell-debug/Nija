"""Offline cash comparison, including records that must never certify readiness."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "margin_cash", Path(__file__).resolve().parents[1] / "bot/kraken_margin_cash_reconciliation.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MarginCashTests(unittest.TestCase):
    def setUp(self):
        self.scope = dict(account_scope="platform:kraken", account_sha256="a" * 64, api_key_sha256="b" * 64)
        self.exchange = {
            "L-open": self.row("margin", "0", "0.25"),
            "L-close": self.row("margin", "-2.5", "0.125"),
            "L-funding": self.row("rollover", "0", "0.03125"),
        }
        self.local = [dict(row, exchange_ledger_id=key, broker="kraken", **self.scope)
                      for key, row in self.exchange.items()]

    @staticmethod
    def row(kind, amount, fee):
        return dict(refid="T-reference", type=kind, subtype="", asset="ZUSD", aclass="currency",
                    time=1700000000.25, amount=amount, fee=fee, balance="100")

    def compare(self):
        return module.compare_margin_cash_records(self.exchange, self.local, **self.scope)

    def test_margin_pnl_and_fees_not_spot_transfers(self):
        before = copy.deepcopy((self.exchange, self.local))
        result = self.compare()
        self.assertEqual(result["totals_by_asset"]["ZUSD"], {
            "realized_pnl": "-2.5", "opening_and_trading_fees": "0.375",
            "rollover_fees": "0.03125", "net_cash_change": "-2.90625"})
        self.assertEqual((self.exchange, self.local), before)
        self.assertEqual(result["matched_entry_count"], 3)
        for field in ("complete_history_verified", "account_identity_verified", "positions_reconciled",
                      "protective_exits_verified", "collector_certified", "authorizes_orders"):
            self.assertIs(result[field], False)

    def test_missing_extra_and_duplicate_local_rows(self):
        for mutation in (lambda rows: rows.pop(), lambda rows: rows.append(dict(rows[0])),
                         lambda rows: rows.append(dict(rows[0], exchange_ledger_id="L-extra"))):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.local)
                mutation(self.local)
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()
                self.local = original

    def test_all_cash_terms_compared(self):
        for field, value in dict(refid="T-wrong", asset="USD", aclass="other", subtype="changed",
                                 time=1700000001, amount="1", fee="1", balance="99", type="rollover").items():
            with self.subTest(field=field):
                original = copy.deepcopy(self.local)
                self.local[0][field] = value
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()
                self.local = original

    def test_other_account_and_rotated_key_denied(self):
        for field in ("account_scope", "account_sha256", "api_key_sha256", "broker"):
            with self.subTest(field=field):
                original = self.local[0][field]
                self.local[0][field] = "wrong"
                with self.assertRaisesRegex(module.MarginCashReconciliationDenied, "cash_provenance_mismatch"):
                    self.compare()
                self.local[0][field] = original

    def test_malformed_money_denied_even_when_both_sides_match(self):
        for value in (True, None, 0.1, "NaN", "Infinity", "1e99999", " 1", "1_000", "9" * 33):
            with self.subTest(value=value):
                self.exchange["L-open"]["fee"] = value
                self.local[0]["fee"] = value
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()

    def test_nonzero_rollover_and_negative_fees_denied(self):
        for field, value in (("amount", "1"), ("fee", "-1")):
            with self.subTest(field=field):
                self.setUp()
                self.exchange["L-funding"][field] = value
                self.local[2][field] = value
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()

    def test_empty_inputs_do_not_certify_history(self):
        result = module.compare_margin_cash_records({}, [], **self.scope)
        self.assertEqual(result["matched_entry_count"], 0)
        self.assertFalse(result["collector_certified"])
        self.assertFalse(result["complete_history_verified"])

    def test_separate_assets_are_never_added_together(self):
        self.exchange["L-funding"]["asset"] = "XXBT"
        self.local[2]["asset"] = "XXBT"
        totals = self.compare()["totals_by_asset"]
        self.assertEqual(totals["XXBT"]["net_cash_change"], "-0.03125")
        self.assertEqual(totals["ZUSD"]["net_cash_change"], "-2.875")

    def test_spot_and_settlement_rows_explicitly_excluded(self):
        for kind in ("trade", "settled", "deposit"):
            self.exchange["L-" + kind] = self.row(kind, "100", "0")
        result = self.compare()
        self.assertEqual(result["matched_entry_count"], 3)
        self.assertEqual(result["excluded_non_margin_entry_count"], 3)

    def test_unknown_or_malformed_type_denied(self):
        for kind in ("new_financing_type", None, [], True):
            with self.subTest(kind=kind):
                self.exchange["L-other"] = self.row(kind, "0", "0")
                with self.assertRaisesRegex(module.MarginCashReconciliationDenied, "cash_type_unsupported"):
                    self.compare()

    def test_tiny_fee_survives_large_realized_pnl(self):
        self.exchange = {"L-large": self.row("margin", "9" * 32, "0." + "0" * 31 + "1")}
        self.local = [dict(self.exchange["L-large"], exchange_ledger_id="L-large", broker="kraken", **self.scope)]
        net = self.compare()["totals_by_asset"]["ZUSD"]["net_cash_change"]
        self.assertEqual(net, "9" * 31 + "8." + "9" * 32)

    def test_bounded_fixed_errors_do_not_leak_identifiers(self):
        self.local[0]["refid"] = "T-private-changed"
        with self.assertRaises(module.MarginCashReconciliationDenied) as error:
            self.compare()
        self.assertEqual(str(error.exception), "cash_entry_terms_mismatch")

    def test_missing_fields_rejected(self):
        for field in ("refid", "asset", "aclass", "time", "amount", "fee", "balance"):
            with self.subTest(field=field):
                self.setUp()
                del self.exchange["L-open"][field]
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()


if __name__ == "__main__":
    unittest.main()
