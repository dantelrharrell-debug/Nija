from __future__ import annotations

import hashlib
import time
import types
from unittest import TestCase
from unittest.mock import patch

from bot import kraken_collector_composition_v487 as composition
from bot.kraken_writer_nonce_evidence_v488 import FIELDS as WRITER_NONCE_FIELDS
from bot.pretrade_attestation_validation_v452 import (
    PROOF_BY_SOURCE, REQUIRED, SOURCES,
)
from bot import pretrade_independent_attestation as attestation


def _certified_observation(field: str, *, observed_at: float) -> dict:
    source = SOURCES[field]
    return {
        "account": composition.ACCOUNT,
        "source": source,
        "provider_id": "reviewed-" + field,
        "evidence_id": "evidence-" + field,
        "verified": True,
        "read_only": True,
        "scope_verified": True,
        "observed_at_epoch": observed_at,
        "provenance": {
            "account_scope_verified": True,
            "collector_identity_verified": True,
            "snapshot_complete": True,
            "complete_pagination_verified": True,
            PROOF_BY_SOURCE[source]: True,
        },
    }


class TestKrakenCollectorCompositionV487(TestCase):
    def test_composes_existing_kraken_broker_nonce_bindings(self) -> None:
        key = "synthetic-composition-key"
        key_id = hashlib.sha256(key.encode()).hexdigest()[:16]

        class NonceManager:
            _redis = object()
            _strict_redis_lease = True
            _owner_id = "owner"
            _owner_fingerprint = "fingerprint"
            lease_version = 17

            def get_writer_lease_status(self, requested_key_id):
                self.assert_key_id(requested_key_id, key_id)
                return {
                    "enabled": True, "key_id": requested_key_id, "error": "",
                    "owner_id": self._owner_id,
                    "owner_fingerprint": self._owner_fingerprint,
                    "token": 17, "ttl_remaining_ms": 25000, "stable_for_s": 12.0,
                }

            def get_last_nonce(self, requested_key_id):
                self.assert_key_id(requested_key_id, key_id)
                return 100000

            @staticmethod
            def assert_key_id(actual, expected):
                if actual != expected:
                    raise AssertionError("unexpected key identity")

        class ExistingKrakenBroker:
            connected = True
            account_type = "platform"
            broker_type = "kraken"
            user_id = None

            def __init__(self):
                self.api = types.SimpleNamespace(key=key)
                self.api_key = key
                self._nonce_key_id = key_id
                self._distributed_nonce_manager = NonceManager()
                self._nonce_lease_version = self._distributed_nonce_manager.lease_version
                self._nonce_generator = lambda: "1"
                self.api._nonce = self._nonce_generator

            @staticmethod
            def _kraken_private_call(*args, **kwargs):
                return None

        broker = ExistingKrakenBroker()
        reviewed_ids = {field: "reviewed-" + field for field in REQUIRED}
        broker_fields = {
            field: (lambda: {"provider": field})
            for field in composition.BROKER_FIELDS
        }
        independent = {
            field: (lambda: {"provider": field}) for field in composition.OTHER_FIELDS
        }

        with (
            patch.object(
                composition, "make_reviewed_kraken_producer_bundle",
                return_value=broker_fields,
            ),
            patch.object(
                composition, "make_kraken_protective_exit_provider",
                return_value=lambda: {},
            ),
            patch(
                "bot.execution_authority_context.assert_distributed_writer_authority"
            ),
        ):
            providers = composition.compose_reviewed_kraken_providers(
                broker=broker,
                approved_api_key_sha256=hashlib.sha256(key.encode()).hexdigest(),
                approved_iban_sha256="b" * 64,
                reviewed_provider_ids=reviewed_ids,
                independent_open_intents=lambda: {},
                independent_positions=lambda: {},
                independent_remaining=independent,
                monitoring_category=object(),
                independently_reviewed=True,
                clock=lambda: 1000.0,
            )
            writer_observation = providers["writer_lease"]()
            nonce_observation = providers["nonce_sequence"]()

        self.assertTrue(writer_observation["verified"])
        self.assertTrue(nonce_observation["verified"])
        self.assertTrue(writer_observation["read_only"])
        self.assertTrue(nonce_observation["read_only"])
        self.assertFalse(writer_observation["authorizes_orders"])
        self.assertFalse(nonce_observation["authorizes_orders"])

    def test_composes_all_fields_with_existing_writer_nonce_providers(self) -> None:
        broker = type("Broker", (), {"_kraken_private_call": lambda *args, **kwargs: None})()
        reviewed_ids = {field: "reviewed-" + field for field in REQUIRED}
        broker_fields = {
            field: (lambda: {"provider": field})
            for field in composition.BROKER_FIELDS
        }
        exit_provider = lambda: {"provider": "protective_exit_readback"}
        writer_providers = {
            field: (lambda: {"provider": field}) for field in WRITER_NONCE_FIELDS
        }
        independent = {
            field: (lambda: {"provider": field}) for field in composition.OTHER_FIELDS
        }
        positions = lambda: {"positions": {}}
        open_intents = lambda: {"orders": {}}

        with (
            patch.object(
                composition, "make_reviewed_kraken_producer_bundle",
                return_value=broker_fields,
            ) as make_broker,
            patch.object(
                composition, "make_kraken_protective_exit_provider",
                return_value=exit_provider,
            ) as make_exits,
            patch.object(
                composition, "make_kraken_writer_nonce_providers",
                return_value=writer_providers,
            ) as make_writer_nonce,
        ):
            providers = composition.compose_reviewed_kraken_providers(
                broker=broker,
                approved_api_key_sha256="a" * 64,
                approved_iban_sha256="b" * 64,
                reviewed_provider_ids=reviewed_ids,
                independent_open_intents=open_intents,
                independent_positions=positions,
                independent_remaining=independent,
                monitoring_category=object(),
                independently_reviewed=True,
                clock=lambda: 1000.0,
            )

        self.assertEqual(set(providers), set(REQUIRED))
        self.assertIs(providers["writer_lease"], writer_providers["writer_lease"])
        self.assertIs(providers["nonce_sequence"], writer_providers["nonce_sequence"])
        self.assertEqual(set(independent).intersection(providers), set(composition.OTHER_FIELDS))
        self.assertIs(make_broker.call_args.args[0], broker)
        self.assertIs(make_exits.call_args.args[0], broker)
        self.assertIs(make_writer_nonce.call_args.args[0], broker)
        self.assertEqual(
            set(make_writer_nonce.call_args.kwargs["reviewed_provider_ids"]),
            set(WRITER_NONCE_FIELDS),
        )

    def test_incomplete_independent_registry_is_rejected_before_provider_creation(self) -> None:
        broker = type("Broker", (), {"_kraken_private_call": lambda *args, **kwargs: None})()
        reviewed_ids = {field: "reviewed-" + field for field in REQUIRED}
        independent = {
            field: (lambda: {}) for field in composition.OTHER_FIELDS
        }
        independent.pop(next(iter(composition.OTHER_FIELDS)))

        with (
            patch.object(composition, "make_reviewed_kraken_producer_bundle") as make_broker,
            patch.object(composition, "make_kraken_protective_exit_provider") as make_exits,
            patch.object(composition, "make_kraken_writer_nonce_providers") as make_writer_nonce,
        ):
            with self.assertRaisesRegex(
                composition.KrakenCollectorBindingDenied,
                "independent_sources_incomplete",
            ):
                composition.compose_reviewed_kraken_providers(
                    broker=broker,
                    approved_api_key_sha256="a" * 64,
                    approved_iban_sha256="b" * 64,
                    reviewed_provider_ids=reviewed_ids,
                    independent_open_intents=lambda: {},
                    independent_positions=lambda: {},
                    independent_remaining=independent,
                    monitoring_category=object(),
                    independently_reviewed=True,
                )

        make_broker.assert_not_called()
        make_exits.assert_not_called()
        make_writer_nonce.assert_not_called()

    def test_unreviewed_registry_cannot_be_composed(self) -> None:
        with self.assertRaisesRegex(
            composition.KrakenCollectorBindingDenied,
            "independent_review_required",
        ):
            composition.compose_reviewed_kraken_providers(
                broker=object(),
                approved_api_key_sha256="a" * 64,
                approved_iban_sha256="b" * 64,
                reviewed_provider_ids={},
                independent_open_intents=lambda: {},
                independent_positions=lambda: {},
                independent_remaining={},
                monitoring_category=object(),
            )

    def test_collector_registers_only_after_complete_fresh_evidence(self) -> None:
        now = time.time()
        providers = {
            field: (lambda field=field: _certified_observation(
                field, observed_at=now,
            ))
            for field in REQUIRED
        }
        reviewed_ids = {field: "reviewed-" + field for field in REQUIRED}

        with patch.object(composition, "register_reviewed_account_registry") as register:
            composition.install_reviewed_kraken_collector(
                providers=providers,
                reviewed_provider_ids=reviewed_ids,
                independently_reviewed=True,
                backup_restore_certified=True,
                broker_ledger_exits_certified=True,
            )

        register.assert_called_once()

    def test_stale_evidence_never_registers_collector(self) -> None:
        now = time.time()
        previous = lambda _account: {"previous": True}
        providers = {
            field: (lambda field=field: _certified_observation(
                field,
                observed_at=now - (61 if field == "nonce_sequence" else 0),
            ))
            for field in REQUIRED
        }
        reviewed_ids = {field: "reviewed-" + field for field in REQUIRED}

        with patch.object(attestation, "_COLLECTOR", previous):
            with self.assertRaisesRegex(
                ValueError,
                "independent_pretrade_provenance_unverified",
            ):
                composition.install_reviewed_kraken_collector(
                    providers=providers,
                    reviewed_provider_ids=reviewed_ids,
                    independently_reviewed=True,
                    backup_restore_certified=True,
                    broker_ledger_exits_certified=True,
                )
            self.assertIs(attestation._COLLECTOR, previous)
