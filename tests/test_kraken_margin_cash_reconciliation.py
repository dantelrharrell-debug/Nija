"""Offline cash comparison, including records that must never certify readiness."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

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

    def test_close_allocation_requires_independent_scoped_exact_rows(self):
        fill = "TAAAAA-BBBBB-CCCCCC"
        position = "TDDDDD-EEEEE-FFFFFF"
        order = "OAAAAA-BBBBB-CCCCCC"
        fills = {fill: dict(postxid=position, ordertxid=order, vol="0.250")}
        row = dict(exchange_trade_id=fill, exchange_position_id=position, exchange_order_id=order,
                   closed_volume="0.25", broker="kraken", **self.scope)
        compare = module.compare_close_fill_allocations
        self.assertEqual(compare(fills, [row], **self.scope), {
            "matched_fill_count": 1, "collector_certified": False, "authorizes_orders": False})
        for rows in ([], [row, row], [dict(row, closed_volume="0.24")],
                     [dict(row, account_sha256="c" * 64)], [dict(row, exchange_position_id=fill)]):
            with self.subTest(rows=len(rows)), self.assertRaises(module.MarginCashReconciliationDenied):
                compare(fills, rows, **self.scope)

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


class MarginPositionTests(unittest.TestCase):
    """Real decimal comparison with synthetic independent position records."""

    def setUp(self):
        self.scope = dict(account_scope="platform:kraken", account_sha256="a" * 64, api_key_sha256="b" * 64)
        self.position_id = "TAAAAA-AAAAA-AAAAAA"
        self.exchange = {self.position_id: dict(
            ordertxid="OAAAAA-AAAAA-AAAAAA", posstatus="open", pair="XXBTZUSD", time=1700000000.25,
            type="buy", ordertype="limit", cost="200", fee="0.25", vol="2", vol_closed="0.5", margin="40",
        )}
        self.local = [dict(self.exchange[self.position_id], exchange_position_id=self.position_id,
                           broker="kraken", **self.scope)]

    def compare(self):
        return module.compare_margin_position_records(self.exchange, self.local, **self.scope)

    def test_partial_close_keeps_remaining_base_quantity_without_certification(self):
        before = copy.deepcopy((self.exchange, self.local))
        result = self.compare()
        self.assertEqual(result["matched_position_count"], 1)
        self.assertEqual(result["remaining_base_quantities_by_pair"], {
            "XXBTZUSD": {"buy": "1.5", "sell": "0"}})
        self.assertEqual((self.exchange, self.local), before)
        for key, value in result.items():
            if key.endswith("verified") or key in {"balances_reconciled", "collector_certified", "authorizes_orders"}:
                self.assertIs(value, False)
        self.assertNotIn(self.position_id, repr(result))
        self.assertNotIn(self.local[0]["ordertxid"], repr(result))

    def test_each_static_term_must_match(self):
        changes = dict(ordertxid="OBBBBB-BBBBB-BBBBBB", pair="XBTUSD", posstatus="closed", type="sell",
                       ordertype="market", time=1700000001, cost="201", fee="0.26", vol="3",
                       vol_closed="0.75", margin="41")
        for field, value in changes.items():
            with self.subTest(field=field):
                self.setUp()
                self.local[0][field] = value
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()

    def test_malformed_matching_financial_inputs_cannot_pass(self):
        for field in ("cost", "fee", "vol", "vol_closed", "margin"):
            for value in (True, None, 0.1, "NaN", "Infinity", "1e99999", " 1", "1_000", "9" * 33, "-1"):
                with self.subTest(field=field, value=value):
                    self.setUp()
                    self.exchange[self.position_id][field] = value
                    self.local[0][field] = value
                    with self.assertRaises(module.MarginCashReconciliationDenied):
                        self.compare()

    def test_overclosed_fully_closed_or_unbacked_open_rows_deny(self):
        for field, value in (("vol_closed", "2"), ("vol_closed", "3"), ("vol", "0"),
                             ("margin", "0"), ("cost", "0")):
            with self.subTest(field=field, value=value):
                self.setUp()
                self.exchange[self.position_id][field] = value
                self.local[0][field] = value
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()

    def test_missing_extra_or_duplicate_local_positions_deny(self):
        for mode in ("missing", "extra", "duplicate"):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == "missing":
                    self.local.clear()
                else:
                    row = dict(self.local[0])
                    if mode == "extra":
                        row["exchange_position_id"] = "TBBBBB-BBBBB-BBBBBB"
                    self.local.append(row)
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()

    def test_wrong_provenance_is_never_inferred_from_matching_terms(self):
        for field in ("broker", "account_scope", "account_sha256", "api_key_sha256"):
            with self.subTest(field=field):
                self.setUp()
                self.local[0][field] = "other"
                with self.assertRaisesRegex(module.MarginCashReconciliationDenied,
                                            "margin_position_provenance_mismatch"):
                    self.compare()

    def test_buys_and_sells_are_not_netted_and_order_ids_are_not_position_ids(self):
        other = "TBBBBB-BBBBB-BBBBBB"
        self.exchange[other] = dict(self.exchange[self.position_id], type="sell")
        self.local.append(dict(self.exchange[other], exchange_position_id=other, broker="kraken", **self.scope))
        self.assertEqual(self.compare()["remaining_base_quantities_by_pair"], {
            "XXBTZUSD": {"buy": "1.5", "sell": "1.5"}})
        self.assertEqual(self.compare()["matched_position_count"], 2)

    def test_tiny_remaining_quantity_is_preserved_without_rounding(self):
        for row in (self.exchange[self.position_id], self.local[0]):
            row.update(vol="9" * 32, vol_closed="9" * 31 + "8." + "9" * 32)
        self.assertEqual(self.compare()["remaining_base_quantities_by_pair"]["XXBTZUSD"]["buy"],
                         "0." + "0" * 31 + "1")

    def test_filtered_empty_inputs_do_not_prove_flat_account(self):
        result = module.compare_margin_position_records({}, [], **self.scope)
        self.assertEqual(result["matched_position_count"], 0)
        self.assertFalse(result["complete_snapshot_verified"])
        self.assertFalse(result["balances_reconciled"])
        self.assertFalse(result["collector_certified"])

    def test_consolidated_keys_and_bad_position_identities_deny(self):
        for identity in ("XXBTZUSD", "OAAAAA-AAAAA-AAAAAA", None, "T-private-identifier"):
            with self.subTest(identity=identity):
                self.setUp()
                self.exchange = {identity: self.exchange[self.position_id]}
                self.local[0]["exchange_position_id"] = identity
                with self.assertRaisesRegex(module.MarginCashReconciliationDenied, "margin_position_row_invalid"):
                    self.compare()

    def test_missing_static_fields_deny(self):
        for field in self.exchange[self.position_id]:
            with self.subTest(field=field):
                self.setUp()
                del self.exchange[self.position_id][field]
                with self.assertRaises(module.MarginCashReconciliationDenied):
                    self.compare()

    def test_invalid_scope_and_row_budget_deny(self):
        with self.assertRaises(module.MarginCashReconciliationDenied):
            module.compare_margin_position_records({}, [], account_scope="other",
                                                   account_sha256="a" * 64, api_key_sha256="b" * 64)
        with patch.object(module, "MAX_ROWS", 0):
            with self.assertRaisesRegex(module.MarginCashReconciliationDenied, "margin_position_budget_exceeded"):
                self.compare()

    def test_live_valuation_fields_are_not_claimed_as_verified(self):
        self.exchange[self.position_id].update(value="250", net="50", terms="0.01% per 4 hours")
        self.local[0].update(value="240", net="40", terms="older snapshot")
        result = self.compare()
        self.assertTrue(result["input_positions_match"])
        self.assertFalse(result["complete_snapshot_verified"])

    def test_mismatch_errors_do_not_disclose_private_identifiers(self):
        self.local[0]["ordertxid"] = "OBBBBB-BBBBB-BBBBBB"
        with self.assertRaisesRegex(module.MarginCashReconciliationDenied, "margin_position_terms_mismatch") as error:
            self.compare()
        self.assertNotIn(self.position_id, str(error.exception))
        self.assertNotIn(self.local[0]["ordertxid"], str(error.exception))


if __name__ == "__main__":
    unittest.main()
