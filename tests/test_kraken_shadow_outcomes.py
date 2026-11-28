from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import unittest
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory

from bot.regime_performance_calibrator import RegimePerformanceCalibrator

from bot.kraken_shadow_outcomes import KrakenShadowOutcomes, ReconciledClose


def close(scope="test:a", lot="lot-1", **kwargs):
    base = ReconciledClose(
        scope, lot, "opening-intent", "opening-order", ("fill-1", "fill-2"),
        Decimal("2"), Decimal("2"), Decimal("0.02"),
        "TEST", "trending", "fixture", "a" * 64,
    )
    return replace(base, **kwargs)


class ShadowOutcomesTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / "shadow.sqlite")
        self.proofs = {}
        self.inbox = self.reopen()

    def reopen(self):
        return KrakenShadowOutcomes(
            self.path, read_reconciled_close=lambda scope, lot: self.proofs.get((scope, lot))
        )

    def put(self, proof):
        self.proofs[proof.scope, proof.lot_id] = proof
        return self.inbox.observe(proof.scope, proof.lot_id)

    def test_duplicate_reordered_fills_and_refreshed_evidence_after_restart(self):
        self.assertEqual(self.put(close()), "accepted")
        self.inbox = self.reopen()
        self.assertEqual(self.put(close(
            closing_fill_ids=("fill-2", "fill-1"), net_return=Decimal(".020"),
            evidence_sha256="b" * 64,
        )), "duplicate")
        self.assertEqual(len(self.inbox.snapshot("test:a")), 1)

    def test_separate_account_same_lot_and_fills(self):
        self.assertEqual(self.put(close()), "accepted")
        self.assertEqual(self.put(close("test:b", net_return=Decimal("-0.02"))), "accepted")
        self.assertEqual(self.inbox.snapshot("test:a")[0]["net_return"], "0.02")
        self.assertEqual(self.inbox.snapshot("test:b")[0]["net_return"], "-0.02")

    def test_unresolved_13_fixture_lots(self):
        for i in range(13):
            self.assertEqual(self.inbox.observe("test:a", f"unresolved-{i}"), "unverified")
        self.assertEqual(self.inbox.snapshot("test:a"), [])

    def test_partial_then_complete(self):
        self.assertEqual(self.put(close(closed_quantity=Decimal(1))), "unverified")
        self.assertEqual(self.put(close()), "accepted")

    def test_conflicting_replay_removes_previously_accepted_lot(self):
        self.assertEqual(self.put(close()), "accepted")
        self.assertEqual(self.put(close(net_return=Decimal("-0.02"))), "quarantined")
        self.inbox = self.reopen()
        self.assertEqual(self.put(close()), "quarantined")
        self.assertEqual(self.inbox.snapshot("test:a"), [])

    def test_reused_fill_quarantines_both_claims(self):
        self.assertEqual(self.put(close()), "accepted")
        self.assertEqual(self.put(close(lot="lot-2", closing_fill_ids=("fill-2", "fill-3"))),
                         "quarantined")
        self.assertEqual(self.put(close(lot="lot-3", closing_fill_ids=("fill-3",))),
                         "quarantined")
        self.assertEqual(self.inbox.snapshot("test:a"), [])

    def test_malformed_evidence(self):
        for change in (
            {"opening_intent_id": ""}, {"opening_order_id": ""}, {"evidence_sha256": ""},
            {"closing_fill_ids": ("fill-1", "fill-1")}, {"net_return": Decimal("NaN")},
        ):
            self.assertEqual(self.put(close(**change)), "unverified")
        self.proofs["test:a", "lot-1"] = close("test:b")
        self.assertEqual(self.inbox.observe("test:a", "lot-1"), "unverified")

    def test_concurrent_retry_has_single_admission(self):
        self.proofs["test:a", "lot-1"] = close()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.inbox.observe("test:a", "lot-1"), range(12)))
        self.assertEqual(results.count("accepted"), 1)
        self.assertEqual(results.count("duplicate"), 11)
        self.assertEqual(len(self.reopen().snapshot("test:a")), 1)


    @patch.dict("os.environ", {
        "NIJA_ADAPTIVE_STRATEGY_MODE": "shadow",
        "NIJA_ADAPTIVE_STRATEGY_APPROVED": "false",
    })
    def test_rebuild_disposable_calibrator_stays_neutral_before_and_after_conflict(self):
        def rebuild(expected_samples):
            with TemporaryDirectory() as folder:
                calibrator = RegimePerformanceCalibrator(str(Path(folder) / "report.json"))
                for row in self.reopen().snapshot("test:a"):
                    calibrator.record_closed_trade(
                        symbol=row["symbol"], regime=row["regime"],
                        strategy=row["strategy"], net_return=float(row["net_return"]),
                    )
                report = calibrator.get_recommendation("trending", "fixture")
                self.assertEqual(report["sample_size"], expected_samples)
                score = calibrator.score_strategy_candidate(
                    strategy="fixture", regime="trending", direction="long", base_score=.51,
                )
                self.assertEqual(score["selection_score"], .51)

        self.assertEqual(self.put(close()), "accepted")
        self.assertEqual(self.put(close()), "duplicate")
        self.assertEqual(self.put(close("test:b")), "accepted")
        rebuild(1)
        self.assertEqual(self.put(close(net_return=Decimal("-0.02"))), "quarantined")
        rebuild(0)

    def test_cost_reconciliation_and_owner_decisions_survive_restart(self):
        from bot.kraken_offline_strategy_review import evaluate
        from bot.kraken_shadow_outcomes import CloseEconomics, OwnerDecision

        first = close(economics=CloseEconomics(Decimal("100"), Decimal("3"), Decimal("1"), 100))
        self.assertEqual(self.put(replace(first, economics=None)), "accepted")
        self.assertIsNone(evaluate(self.inbox, "test:a")["metrics"]["net_realized_pnl_usd"])
        self.assertEqual(self.put(first), "enriched")
        self.assertEqual(self.put(first), "duplicate")
        self.assertEqual(self.put(close(
            lot="loss", closing_fill_ids=("fill-3",),
            net_return=Decimal("-.01"),
            economics=CloseEconomics(Decimal("100"), Decimal("0"), Decimal("1"), 200),
        )), "accepted")

        report = evaluate(self.reopen(), "test:a")
        self.assertEqual(report["learning_sample_count"], 2)
        self.assertFalse(report["authorizes_orders"])
        self.assertEqual(report["metrics"], {
            "status": "reconciled_sample", "net_realized_pnl_usd": "1", "execution_cost_usd": "2",
            "realized_drawdown_usd": "1", "profit_factor": "2",
        })
        decision = OwnerDecision("test:a", "evaluation-1", "owner-fixture", report["snapshot_sha256"], "retain_for_review", 250)
        self.assertEqual(self.inbox.record_owner_decision(decision, authenticate=lambda _: False), "unverified")
        self.assertEqual(self.inbox.record_owner_decision(decision, authenticate=lambda _: True), "recorded")
        self.assertEqual(self.reopen().record_owner_decision(decision, authenticate=lambda _: True), "duplicate")
        self.assertEqual(self.inbox.record_owner_decision(
            replace(decision, decision="reject"), authenticate=lambda _: True,
        ), "conflict")
        self.assertEqual(len(evaluate(self.reopen(), "test:a")["owner_decisions"]), 1)

        disputed = replace(first, economics=CloseEconomics(Decimal("100"), Decimal("4"), Decimal("2"), 100))
        self.assertEqual(self.put(disputed), "quarantined")
        report = evaluate(self.reopen(), "test:a")
        self.assertEqual(report["owner_decisions"], [])
        self.assertEqual(report["metrics"]["net_realized_pnl_usd"], "-1")

    def test_offline_cutoff_keeps_future_and_same_second_lots_out_of_the_wrong_sample(self):
        from bot.kraken_offline_strategy_review import evaluate
        from bot.kraken_shadow_outcomes import CloseEconomics, OwnerDecision

        for lot, epoch, gross in (("early", 99, "3"), ("boundary-a", 100, "3"),
                                  ("boundary-b", 100, "3"), ("holdout", 101, "21")):
            income = Decimal(gross)
            self.proofs[("test:a", lot)] = close(
                lot=lot, closing_fill_ids=(lot + "-fill",), net_return=(income - 1) / 100,
                economics=CloseEconomics(Decimal("100"), income, Decimal("1"), epoch),
            )
            self.assertEqual(self.inbox.observe("test:a", lot), "accepted")
        cut = 100
        with patch.object(RegimePerformanceCalibrator, "record_closed_trade", autospec=True) as record:
            report = evaluate(self.inbox, "test:a", training_through_epoch=cut)
        self.assertEqual(record.call_count, 3)
        self.assertTrue(all(call.kwargs["net_return"] == 0.02 for call in record.call_args_list))
        self.assertEqual(report["recommendation_basis"], "training_samples_only")
        chronology = report["chronological_review"]
        self.assertEqual(chronology["status"], "separate_samples")
        self.assertEqual(chronology["holdout_sample_count"], 1)
        self.assertEqual(chronology["observed_holdout_metrics"]["net_realized_pnl_usd"], "20")
        self.assertEqual(chronology["candidate_comparison_status"], "not_evaluated")
        self.assertIsNone(chronology["candidate_comparison"])
        self.assertFalse(report["authorizes_orders"])

        decision = OwnerDecision("test:a", "decision-for-cutoff", "fixture-owner",
                                 report["snapshot_sha256"], "retain_for_review", 110)
        self.assertEqual(self.inbox.record_owner_decision(decision, authenticate=lambda _: True), "recorded")
        changed = evaluate(self.inbox, "test:a", training_through_epoch=cut - 1)
        self.assertNotEqual(report["snapshot_sha256"], changed["snapshot_sha256"])
        self.assertEqual(changed["owner_decisions"], [])
        same = evaluate(self.inbox, "test:a", training_through_epoch=cut)
        self.assertEqual(len(same["owner_decisions"]), 1)

    def test_offline_cutoff_is_explicit_and_empty_samples_remain_uncertified(self):
        from bot.kraken_offline_strategy_review import evaluate

        default = evaluate(self.inbox, "test:a")
        self.assertEqual(default["recommendation_basis"], "in_sample_shadow_only")
        self.assertEqual(default["chronological_review"]["status"], "cutoff_not_set")
        report = evaluate(self.inbox, "test:a", training_through_epoch=100)
        self.assertEqual(report["chronological_review"]["status"], "insufficient_dated_samples")
        self.assertIsNone(report["chronological_review"]["observed_holdout_metrics"])
        self.assertIsNone(report["chronological_review"]["observed_holdout_cost_by_regime"])
        self.assertIsNone(report["chronological_review"]["candidate_comparison"])
        self.assertFalse(report["authorizes_orders"])
        for invalid in (True, 0, -1, "100", 100.5, 253402300800):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "training cutoff"):
                evaluate(self.inbox, "test:a", training_through_epoch=invalid)

    def test_cost_attribution_uses_only_admitted_dated_holdout_economics(self):
        from bot.kraken_offline_strategy_review import evaluate
        from bot.kraken_shadow_outcomes import CloseEconomics

        cases = (
            ("training", "trending", 100, "40", "0"),
            ("turns-negative", "trending", 101, "1.2", "2.5"),
            ("break-even", "trending", 102, "1", "1"),
            ("gross-loss", "ranging", 103, "-2", "0.5"),
            ("still-positive", "ranging", 104, "5", "1"),
        )
        for lot, regime, stamp, gross, cost in cases:
            gross, cost = Decimal(gross), Decimal(cost)
            self.assertEqual(self.put(close(
                lot=lot, regime=regime, closing_fill_ids=(lot + "-fill",),
                net_return=(gross - cost) / 100,
                economics=CloseEconomics(Decimal("100"), gross, cost, stamp),
            )), "accepted")
        self.assertEqual(self.put(close(lot="undated", regime="trending")), "accepted")
        # A different account must have no influence on this report.
        self.assertEqual(self.put(close(
            "test:b", economics=CloseEconomics(Decimal("100"), Decimal("3"), Decimal("1"), 105),
        )), "accepted")
        report = evaluate(self.reopen(), "test:a", training_through_epoch=100)
        chronology = report["chronological_review"]
        self.assertEqual(chronology["holdout_sample_count"], 4)
        self.assertEqual(chronology["lots_without_economics"], 1)
        self.assertIsNone(report["metrics"]["net_realized_pnl_usd"])
        self.assertEqual(chronology["observed_holdout_cost_by_regime"], [
            {"admitted_regime_label": "ranging", "gross_realized_pnl_usd": "3",
             "recorded_execution_cost_usd": "1.5", "net_realized_pnl_usd": "1.5",
             "sample_count": 2, "gross_winner_lots_erased_by_cost": 0},
            {"admitted_regime_label": "trending", "gross_realized_pnl_usd": "2.2",
             "recorded_execution_cost_usd": "3.5", "net_realized_pnl_usd": "-1.3",
             "sample_count": 2, "gross_winner_lots_erased_by_cost": 2},
        ])
        self.assertEqual(chronology["slippage_status"], "unavailable_no_benchmark_evidence")
        self.assertIsNone(chronology["candidate_comparison"])
        self.assertFalse(report["authorizes_orders"])

    def test_reject_wrong_or_missing_cost_reconciliation(self):
        from bot.kraken_shadow_outcomes import CloseEconomics

        for cost, stamp in ((Decimal("2"), 100), (Decimal("-1"), 100), (Decimal("1"), True)):
            self.assertEqual(self.put(close(
                economics=CloseEconomics(Decimal("100"), Decimal("3"), cost, stamp),
            )), "unverified")
        self.assertEqual(self.inbox.snapshot("test:a"), [])
