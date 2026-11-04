"""Offline shared-binding regressions using the existing four-family fixtures."""
from __future__ import annotations

import copy
import unittest
from dataclasses import fields, replace
from typing import Any
from unittest.mock import Mock, patch

from bot import kraken_evidence_composition as composition
from bot.kraken_redis_evidence import ScopeObservation
from bot.tests import test_kraken_ledger_evidence as ledger_fixture
from bot.tests import test_kraken_operator_authorization as operator_fixture
from bot.tests import test_kraken_redis_evidence as redis_fixture
from bot.tests import test_kraken_risk_evidence as risk_fixture

NOW = ledger_fixture.NOW


def rebind(kind: type[Any], value: Any) -> Any:
    """Translate isolated fixture dataclasses to the production module's type."""
    return kind(**{field.name: getattr(value, field.name) for field in fields(value)})


class KrakenEvidenceCompositionTests(unittest.TestCase):
    """Exercise actual family readers without network, startup or shared state."""

    def setUp(self) -> None:
        self.ledger = ledger_fixture.KrakenLedgerEvidenceTests()
        self.ledger.setUp()
        self.addCleanup(self.ledger.tearDown)
        self.redis = redis_fixture.RedisEvidenceTests()
        self.redis.setUp()
        self.operator = operator_fixture.OperatorAuthorizationTests()
        self.operator.setUp()
        account, key_pin, account_pin = ledger_fixture.SCOPE, ledger_fixture.KEY_HASH, ledger_fixture.ACCOUNT_HASH
        self.redis.scope = replace(self.redis.scope, account=account, api_key_sha256=key_pin)
        self.redis.binding = replace(self.redis.binding, expected_scope=self.redis.scope)
        self.redis.proof.update(account=account, api_key_sha256=key_pin)
        self.redis.manifest_key, self.redis.members_key, self.redis.record_prefix = (
            redis_fixture.inventory_keys(account)
        )
        self.redis.rows[0].update(account=account, api_key_sha256=key_pin)
        self.redis._install_inventory()
        redis_binding = replace(
            rebind(composition.ReviewedBinding, self.redis.binding),
            expected_scope=rebind(ScopeObservation, self.redis.scope),
            observe_scope=lambda: rebind(ScopeObservation, self.redis.scope),
        )
        reader = composition.RedisEvidenceReader(self.redis.redis, redis_binding, clock=lambda: NOW)
        controls = [
            self.redis.scope.process_lock_value, "12", self.redis.scope.nonce_owner, "7", "7",
            self.redis.scope.nonce_fingerprint, "1700000000001",
        ]
        for (_, name), value in zip(reader._controls(), controls):
            self.redis.redis.values[name] = value.encode()
        for index in (0, 2, 3, 5):
            self.redis.redis.ttls[reader._controls()[index][1]] = 30000
        self.operator.binding = replace(
            self.operator.binding, account=account, api_key_sha256=key_pin, account_iiban_sha256=account_pin,
        )
        self.operator.approval.update(
            account=account, api_key_sha256=key_pin, account_iiban_sha256=account_pin,
            approved_at_epoch=NOW - 50, expires_at_epoch=NOW + 100,
        )
        self.operator.status.update(observed_at_epoch=NOW - 1, expires_at_epoch=NOW + 10)
        self.operator.resign()
        self.source = risk_fixture.SnapshotSource(risk_fixture.snapshot(account, key_pin))
        ledger_binding = rebind(composition.ReviewedLedgerBinding, self.ledger.binding)
        provider_ids = {
            "position_ledger_reconciliation": ledger_binding.provider_id,
            **dict(zip(composition.REDIS_FIELDS, redis_binding.provider_ids)),
            "risk_limits": "reviewed-risk-provider",
            "operator_authorization": self.operator.binding.provider_id,
        }
        self.binding = composition.KrakenEvidenceBinding(
            account=account, api_key_sha256=key_pin, account_iiban_sha256=account_pin,
            trusted_provider_ids=provider_ids, ledger=ledger_binding,
            redis_client=self.redis.redis, redis=redis_binding,
            risk=composition.RiskEvidenceDependencies(
                self.source, "reviewed-account-snapshot", risk_fixture.BINDINGS,
            ),
            operator=composition.OperatorEvidenceDependencies(
                self.operator.binding, {"test-operator": self.operator.public(self.operator.operator)},
                self.operator.public(self.operator.revoker), lambda: self.operator.records,
            ),
        )
        self.reviewed = True
        self.clock_value = NOW

    def compose(
        self, binding: composition.KrakenEvidenceBinding | None = None, **options: Any,
    ) -> composition.KrakenEvidenceComposition:
        """Use an object-identity review stand-in, never production approval."""
        selected = self.binding if binding is None else binding
        options = {
            "review_binding": lambda candidate: candidate is selected and self.reviewed,
            "clock": lambda: self.clock_value,
            **options,
        }
        return composition.compose_kraken_evidence(selected, **options)

    def test_composition_is_inert_and_collection_uses_one_shared_redis_read(self) -> None:
        reads = self.redis.redis.executions
        bound = self.compose()
        self.assertEqual(self.ledger.broker.calls, [])
        self.assertEqual(self.source.calls, [])
        self.assertEqual(self.redis.redis.executions, reads)
        with patch.object(bound._redis, "collect", wraps=bound._redis.collect) as collect:
            rows = bound.collect()
        collect.assert_called_once_with()
        self.assertEqual(set(rows), set(composition.FIELDS))
        self.assertEqual(len({row["evidence_id"] for row in rows.values()}), 6)
        self.assertEqual(self.source.calls, [(self.binding.account, self.binding.api_key_sha256)] * 2)
        self.assertTrue(all(row["authorizes_orders"] is False for row in rows.values()))
        redis_ids = [rows[field]["evidence_id"].partition(":")[0] for field in composition.REDIS_FIELDS]
        self.assertEqual(len(set(redis_ids)), 1)
        self.assertTrue(all(command in {"get", "smembers", "pttl"} for command, _ in self.redis.redis.commands))
        self.assertTrue(all(endpoint not in {"AddOrder", "CancelOrder"} for endpoint, _, _ in self.ledger.broker.calls))
        self.assertEqual(rows["position_ledger_reconciliation"]["observed_at_epoch"], NOW - 10)
        self.assertEqual(rows["risk_limits"]["expires_at_epoch"], NOW + 50)
        self.assertEqual(rows["operator_authorization"]["expires_at_epoch"], NOW + 10)
        self.assertEqual(rows["writer_lease"]["expires_at_epoch"], NOW + 30)

    def test_six_fields_do_not_certify_the_thirteen_source_contract(self) -> None:
        rows = self.compose().collect()
        pins = {field: "external:" + field for field in ledger_fixture.REQUIRED}
        pins.update(self.binding.trusted_provider_ids)
        verdict = ledger_fixture.evaluate_pretrade_certificate(
            rows, account=self.binding.account, trusted_provider_ids=pins, now_epoch=NOW,
        )
        self.assertFalse(verdict["certified"])
        self.assertFalse(verdict["authorizes_orders"])
        self.assertEqual(set(verdict["missing"]), set(ledger_fixture.REQUIRED) - set(composition.FIELDS))

    def test_trust_pin_mismatches_and_missing_dependencies_fail_without_reads(self) -> None:
        for change in (
            {"account": "platform:kraken"}, {"api_key_sha256": "c" * 64},
            {"account_iiban_sha256": "d" * 64}, {"ledger": None}, {"redis": None},
            {"redis_client": None}, {"risk": None}, {"operator": None},
            {"risk": replace(self.binding.risk, snapshot_source=None)},
            {"risk": replace(self.binding.risk, snapshot_source_id="")},
            {"risk": replace(self.binding.risk, record_source_ids={})},
            {"risk": replace(self.binding.risk, global_governor=object())},
            {"risk": replace(self.binding.risk, capital_authority=object(), capital_broker_id="reviewed")},
            {"risk": replace(self.binding.risk, capital_broker_id="unconfigured-veto")},
            {"operator": replace(self.binding.operator, read_records=None)},
            {"operator": replace(self.binding.operator, operator_public_keys={})},
            {"operator": replace(self.binding.operator, status_public_key=b"")},
            {"trusted_provider_ids": {}},
            {"trusted_provider_ids": dict.fromkeys(composition.FIELDS, "same-provider")},
            {"trusted_provider_ids": {**self.binding.trusted_provider_ids, "writer_lease": "other-writer"}},
        ):
            with self.subTest(change=change), self.assertRaises(composition.KrakenEvidenceCompositionDenied):
                self.compose(replace(self.binding, **change))
        self.assertEqual(self.ledger.broker.calls, [])
        self.assertEqual(self.source.calls, [])
        self.assertEqual(self.redis.redis.executions, 0)

    def test_independent_review_is_mandatory_and_rechecked(self) -> None:
        for reviewer in (None, lambda _: False, lambda _: 1, Mock(side_effect=RuntimeError("secret"))):
            with self.subTest(reviewer=reviewer), self.assertRaises(composition.KrakenEvidenceCompositionDenied):
                self.compose(review_binding=reviewer)
        bound = self.compose()
        self.reviewed = False
        with self.assertRaisesRegex(composition.KrakenEvidenceCompositionDenied, "family_collection_unavailable"):
            bound.collect()
        self.assertEqual(self.ledger.broker.calls, [])

    def test_review_revoked_during_collection_returns_no_partial_batch(self) -> None:
        original = self.binding.operator.read_records

        def revoke():
            self.reviewed = False
            return original()

        bound = self.compose(replace(
            self.binding, operator=replace(self.binding.operator, read_records=revoke),
        ))
        with self.assertRaisesRegex(composition.KrakenEvidenceCompositionDenied, "family_collection_unavailable"):
            bound.collect()

    def test_existing_unscoped_ledger_is_not_promoted_or_migrated(self) -> None:
        import sqlite3
        path = self.ledger.root / "canonical-unscoped.db"
        with sqlite3.connect(path) as database:
            database.execute("CREATE TABLE open_positions (position_id TEXT, quantity TEXT)")
            database.execute("INSERT INTO open_positions VALUES ('unscoped', '2')")
        original = path.read_bytes()
        bound = self.compose(replace(self.binding, ledger=replace(self.binding.ledger, ledger_path=path)))
        with self.assertRaisesRegex(composition.KrakenEvidenceCompositionDenied, "family_collection_unavailable"):
            bound.collect()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.ledger.broker.calls, [])

    def test_real_family_failures_deny_the_whole_batch(self) -> None:
        mutations = (
            lambda: self.operator.status.update(status="revoked"),
            lambda: self.source.value["policy"].update(halt_active=True),
            lambda: self.redis.redis.values.pop(self.redis.manifest_key),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                records = copy.deepcopy(self.operator.records)
                status = copy.deepcopy(self.operator.status)
                risk = copy.deepcopy(self.source.value)
                redis = copy.deepcopy(self.redis.redis.values)
                mutate()
                self.operator.resign()
                with self.assertRaises(composition.KrakenEvidenceCompositionDenied):
                    self.compose().collect()
                self.operator.records, self.operator.status = records, status
                self.source.value, self.redis.redis.values = risk, redis

    def test_canonical_governor_is_a_veto_not_a_snapshot_substitute(self) -> None:
        governor = Mock()
        governor.get_status.return_value = {"halt_active": True}
        bound = self.compose(replace(
            self.binding, risk=replace(self.binding.risk, global_governor=governor),
        ))
        with self.assertRaises(composition.KrakenEvidenceCompositionDenied):
            bound.collect()
        governor.get_status.assert_called_once_with()
        governor.approve_entry.assert_not_called()
        with self.assertRaises(composition.KrakenEvidenceCompositionDenied):
            self.compose(replace(self.binding, risk=replace(
                self.binding.risk, global_governor=governor, snapshot_source=None,
            )))

    def test_expiry_during_later_family_read_is_not_renewed(self) -> None:
        def advance_clock():
            self.clock_value = NOW + 11
            return self.operator.records

        bound = self.compose(replace(
            self.binding, operator=replace(self.binding.operator, read_records=advance_clock),
        ))
        with self.assertRaises(composition.KrakenEvidenceCompositionDenied):
            bound.collect()

    def test_short_redis_deadline_is_rechecked_after_later_families(self) -> None:
        self.operator.status["expires_at_epoch"] = NOW + 100
        self.operator.resign()
        bound = self.compose()
        original = bound._operator

        def finish_late():
            row = original()
            self.clock_value = NOW + 31
            return row

        bound._operator = finish_late
        with self.assertRaises(composition.KrakenEvidenceCompositionDenied):
            bound.collect()

    def test_collection_clock_must_not_regress_or_outlive_read_budget(self) -> None:
        for value in (NOW - 1, NOW + 61, True, float("nan")):
            with self.subTest(clock=value):
                bound = self.compose()
                original = bound._operator

                def finish_invalid():
                    row = original()
                    self.clock_value = value
                    return row

                bound._operator = finish_invalid
                with self.assertRaises(composition.KrakenEvidenceCompositionDenied):
                    bound.collect()
                self.clock_value = NOW

    def test_external_exception_of_public_denial_type_is_also_redacted(self) -> None:
        review = Mock(side_effect=composition.KrakenEvidenceCompositionDenied("sensitive-review-details"))
        with self.assertRaisesRegex(composition.KrakenEvidenceCompositionDenied, "^family_configuration_invalid$"):
            self.compose(review_binding=review)
        bound = self.compose()
        bound._reviewer = review
        with self.assertRaisesRegex(composition.KrakenEvidenceCompositionDenied, "^family_collection_unavailable$"):
            bound.collect()

    def test_pins_are_frozen_and_new_collections_do_not_reuse_evidence(self) -> None:
        bound = self.compose()
        with self.assertRaises(TypeError):
            bound.trusted_provider_ids["risk_limits"] = "replacement"
        first = bound.collect()
        first["writer_lease"]["verified"] = False
        second = bound.collect()
        self.assertTrue(second["writer_lease"]["verified"])
        self.assertTrue(all(first[field]["evidence_id"] != second[field]["evidence_id"]
                            for field in composition.FIELDS))
        self.assertEqual(second["writer_lease"]["observed_at_epoch"], NOW)

    def test_source_exceptions_are_redacted(self) -> None:
        source = Mock()
        source.read_snapshot.side_effect = RuntimeError("sensitive source details")
        bound = self.compose(replace(self.binding, risk=replace(self.binding.risk, snapshot_source=source)))
        with self.assertRaises(composition.KrakenEvidenceCompositionDenied) as failure:
            bound.collect()
        self.assertEqual(str(failure.exception), "family_collection_unavailable")
        self.assertIsNone(failure.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
