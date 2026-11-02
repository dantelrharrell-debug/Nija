"""Offline unittest coverage for account-pinned Kraken risk observations."""
from __future__ import annotations

import copy
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock


def load_module(filename: str):
    """Load pure review modules without executing bot package startup hooks."""
    spec = importlib.util.spec_from_file_location(
        filename.removesuffix(".py"), Path(__file__).resolve().parents[1] / filename,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


risk_evidence = load_module("kraken_risk_evidence.py")
v452 = load_module("pretrade_attestation_validation_v452.py")
PROVENANCE = risk_evidence.PROVENANCE
KrakenRiskEvidenceDenied = risk_evidence.KrakenRiskEvidenceDenied
make_kraken_risk_limits_provider = risk_evidence.make_kraken_risk_limits_provider
REQUIRED, SOURCES, PROOF_BY_SOURCE = v452.REQUIRED, v452.SOURCES, v452.PROOF_BY_SOURCE
evaluate_pretrade_certificate = v452.evaluate_pretrade_certificate

NOW = 1_800_000_000.0
PIN = "a" * 64
ACCOUNT = "platform:kraken"
BINDINGS = {
    "capital": "reviewed-capital-registry",
    "exposure": "reviewed-account-exposure",
    "policy": "reviewed-account-policy",
}


def snapshot(account: str = ACCOUNT, pin: str = PIN) -> dict:
    """Build complete synthetic evidence, never runtime credentials or state."""
    def envelope(source: str) -> dict:
        return {
            "account": account, "broker": "kraken", "api_key_sha256": pin,
            "source_id": source, "revision": 7, "observed_at_epoch": NOW - 10,
            "verified": True, "read_only": True, "scope_verified": True,
            "provenance": dict.fromkeys(PROVENANCE, True),
        }

    result = envelope("reviewed-account-snapshot")
    result["capital"] = envelope(BINDINGS["capital"]) | {
        "hydrated": True, "registered": True, "is_real": True,
        "real_capital": 1000.0, "usable_capital": 900.0,
    }
    result["exposure"] = envelope(BINDINGS["exposure"]) | {
        "hydrated": True, "total_gross_exposure_usd": 40.0, "total_risk_usd": 1.0,
        "positions": [{
            "position_id": "position-1", "symbol": "BTC-USD", "asset_class": "Crypto",
            "direction": "long", "state": "open", "notional_usd": 40.0,
            "risk_usd": 1.0, "quantity": 0.001, "protected_quantity": 0.001,
            "protective_exit_verified": True, "broker_acknowledged": True,
            "reduce_only": True, "stop_distance_pct": 2.0, "leverage": 1.0,
        }],
    }
    result["policy"] = envelope(BINDINGS["policy"]) | {
        "trading_allowed": True, "halt_active": False, "protective_exits_required": True,
        "leverage_allowed": False, "short_allowed": False, "reduce_only_required": True,
        "max_open_positions": 12, "max_consecutive_losses": 5, "consecutive_losses": 0,
        "position_size_multiplier": 1.0, "max_position_pct": 5.0,
        "max_single_asset_pct": 15.0, "max_total_risk_pct": 25.0,
        "max_drawdown_pct": 20.0, "max_daily_loss_pct": 5.0,
        "max_stop_distance_pct": 5.0, "max_total_exposure_pct": 40.0,
        "max_leverage": 2.0, "absolute_max_leverage": 5.0,
        "max_asset_class_pct": {"Crypto": 40.0}, "peak_equity_usd": 1000.0,
        "drawdown_pct": 0.0, "daily_pnl_usd": 0.0,
    }
    return result


class SnapshotSource:
    """Fake independently reviewed source with deterministic detached reads."""

    def __init__(self, value: dict) -> None:
        self.value = value
        self.calls = []
        self.after_first = None

    def read_snapshot(self, account: str, api_key_sha256: str) -> dict:
        """Return synthetic state and optionally simulate concurrent publication."""
        self.calls.append((account, api_key_sha256))
        value = copy.deepcopy(self.value)
        if len(self.calls) == 1 and self.after_first is not None:
            self.after_first(self.value)
        return value


class KrakenRiskEvidenceTests(unittest.TestCase):
    """Verify provenance, risk restrictions, non-mutation and race rejection."""

    def provider(self, value: dict | None = None, **overrides):
        """Construct only offline fake sources; no collectors are installed."""
        source = SnapshotSource(snapshot() if value is None else value)
        options = {
            "account_scope": ACCOUNT, "approved_api_key_sha256": PIN,
            "reviewed_provider_id": "reviewed-risk-limits-provider",
            "reviewed_snapshot_source_id": "reviewed-account-snapshot",
            "reviewed_record_source_ids": BINDINGS, "independently_reviewed": True,
            "clock": lambda: NOW,
        }
        options.update(overrides)
        return make_kraken_risk_limits_provider(source, **options), source

    def assert_denied(self, value: dict) -> None:
        """Assert the stable denial type rather than leaking source details."""
        read, _ = self.provider(value)
        with self.assertRaises(KrakenRiskEvidenceDenied):
            read()

    def test_v452_compatible_unique_non_authorizing_observation(self):
        read, source = self.provider()
        original = copy.deepcopy(source.value)
        first, second = read(), read()
        self.assertEqual(source.value, original)
        self.assertNotEqual(first["evidence_id"], second["evidence_id"])
        self.assertFalse(first["authorizes_orders"])
        self.assertEqual(first["source"], "risk_governor")
        self.assertEqual(first["api_key_sha256"], PIN)
        self.assertEqual(first["observed_at_epoch"], NOW - 10)
        self.assertEqual(source.calls, [(ACCOUNT, PIN)] * 4)
        provider_ids = {field: f"reviewed-{field}" for field in REQUIRED}
        provider_ids["risk_limits"] = first["provider_id"]
        rows = {}
        for field in REQUIRED:
            rows[field] = {
                "account": ACCOUNT, "source": SOURCES[field],
                "provider_id": provider_ids[field], "evidence_id": f"test-{field}",
                "verified": True, "read_only": True, "scope_verified": True,
                "observed_at_epoch": NOW - 5,
                "provenance": dict.fromkeys((
                    "account_scope_verified", "collector_identity_verified", "snapshot_complete",
                    "complete_pagination_verified", PROOF_BY_SOURCE[SOURCES[field]],
                ), True),
            }
        rows["risk_limits"] = first
        verdict = evaluate_pretrade_certificate(
            rows, account=ACCOUNT, trusted_provider_ids=provider_ids, now_epoch=NOW,
        )
        self.assertTrue(verdict["certified"], verdict)
        self.assertFalse(verdict["authorizes_orders"])

    def test_independent_review_and_bindings_are_mandatory(self):
        for options in (
            {"independently_reviewed": False}, {"reviewed_provider_id": ""},
            {"reviewed_snapshot_source_id": ""},
            {"reviewed_record_source_ids": {}},
            {"reviewed_record_source_ids": dict.fromkeys(BINDINGS, "same-producer")},
            {"account_scope": "platform:coinbase"},
            {"approved_api_key_sha256": "not-a-pin"},  # pragma: allowlist secret -- invalid synthetic fingerprint
        ):
            with self.subTest(options=options), self.assertRaises(KrakenRiskEvidenceDenied):
                self.provider(**options)

    def test_source_age_is_not_reset_when_certification_is_observed(self):
        for component in ("capital", "exposure"):
            value = snapshot()
            value[component]["observed_at_epoch"] = NOW - 59
            read, _ = self.provider(value)
            row = read()
            self.assertEqual(row["observed_at_epoch"], NOW - 59)
            self.assertEqual(row["expires_at_epoch"], NOW + 1)
            providers = {field: f"reviewed-{field}" for field in REQUIRED}
            providers["risk_limits"] = row["provider_id"]
            for now, expected_reason in ((NOW, None), (NOW + 2, "observation_stale")):
                verdict = evaluate_pretrade_certificate(
                    {"risk_limits": row}, account=ACCOUNT,
                    trusted_provider_ids=providers, now_epoch=now,
                )
                with self.subTest(component=component, now=now):
                    self.assertEqual(verdict["failure_reasons"].get("risk_limits"), expected_reason)

    def test_stricter_source_expiry_is_preserved_and_enforced_by_v452(self):
        for component in (None, "capital", "exposure", "policy"):
            value = snapshot()
            record = value if component is None else value[component]
            record["expires_at_epoch"] = NOW + 1
            read, _ = self.provider(value)
            row = read()
            self.assertEqual(row["expires_at_epoch"], NOW + 1)
            providers = {field: f"reviewed-{field}" for field in REQUIRED}
            providers["risk_limits"] = row["provider_id"]
            verdict = evaluate_pretrade_certificate(
                {"risk_limits": row}, account=ACCOUNT,
                trusted_provider_ids=providers, now_epoch=NOW + 2,
            )
            self.assertEqual(verdict["failure_reasons"]["risk_limits"], "observation_expired")
            for invalid in (NOW, NOW - 11, float("nan"), float("inf"), True, "later", None):
                record["expires_at_epoch"] = invalid
                with self.subTest(component=component, invalid=invalid):
                    self.assert_denied(value)

    def test_all_records_require_account_key_and_provenance(self):
        for component in (None, "capital", "exposure", "policy"):
            for key, invalid in (
                ("account", "user:another:kraken"), ("api_key_sha256", "b" * 64),
                ("broker", "coinbase"), ("source_id", "unreviewed"),
                ("verified", False), ("read_only", 1), ("scope_verified", None),
                ("revision", True), ("revision", 0),
            ):
                with self.subTest(component=component, key=key):
                    value = snapshot()
                    row = value if component is None else value[component]
                    row[key] = invalid
                    self.assert_denied(value)
            for flag in PROVENANCE:
                with self.subTest(component=component, missing_proof=flag):
                    value = snapshot()
                    row = value if component is None else value[component]
                    del row["provenance"][flag]
                    self.assert_denied(value)

    def test_stale_capital_exposure_policy_and_envelope(self):
        for component in (None, "capital", "exposure", "policy"):
            for stamp in (NOW - 60.001, NOW + 0.001, float("nan"), float("inf"), True, "fresh", 0):
                with self.subTest(component=component, stamp=stamp):
                    value = snapshot()
                    row = value if component is None else value[component]
                    row["observed_at_epoch"] = stamp
                    self.assert_denied(value)
        value = snapshot()
        value["capital"]["observed_at_epoch"] = NOW - 60
        read, _ = self.provider(value)
        self.assertEqual(read()["observed_at_epoch"], NOW - 60)

    def test_read_duration_does_not_refresh_stale_records(self):
        for clocks in ((NOW, NOW + 51), (NOW, NOW - 1), (NOW, NOW + 61)):
            times = iter(clocks)
            read, _ = self.provider(clock=lambda: next(times))
            with self.subTest(clocks=clocks), self.assertRaises(KrakenRiskEvidenceDenied):
                read()

    def test_account_isolation_no_global_allocation(self):
        read, _ = self.provider(snapshot("user:alice:kraken", "b" * 64))
        with self.assertRaises(KrakenRiskEvidenceDenied):
            read()
        read, _ = self.provider(
            snapshot("user:alice:kraken", "b" * 64),
            account_scope="user:alice:kraken", approved_api_key_sha256="b" * 64,
        )
        self.assertEqual(read()["account"], "user:alice:kraken")
        mixed = snapshot()
        mixed["exposure"] = snapshot("user:alice:kraken")["exposure"]
        self.assert_denied(mixed)

    def test_missing_hydration_registration_real_capital_and_positions(self):
        for section, key, invalid in (
            ("capital", "hydrated", False), ("capital", "registered", False),
            ("capital", "is_real", False), ("capital", "real_capital", 0),
            ("capital", "usable_capital", 0), ("capital", "usable_capital", 1001),
            ("exposure", "hydrated", False), ("exposure", "positions", None),
            ("exposure", "positions", {}),
        ):
            with self.subTest(section=section, key=key):
                value = snapshot()
                value[section][key] = invalid
                self.assert_denied(value)

    def test_policy_numeric_types_are_finite_strict_and_required(self):
        base = snapshot()
        keys = [key for key, value in base["policy"].items() if type(value) in (float, int)]
        for key in keys:
            for invalid in (float("nan"), float("inf"), -float("inf"), True, "5", None, [], 10 ** 400):
                with self.subTest(key=key, invalid=repr(invalid)[:30]):
                    value = snapshot()
                    value["policy"][key] = invalid
                    self.assert_denied(value)
            value = snapshot()
            del value["policy"][key]
            self.assert_denied(value)
        for key in ("leverage_allowed", "short_allowed", "reduce_only_required", "trading_allowed",
                    "halt_active", "protective_exits_required"):
            value = snapshot()
            value["policy"][key] = 1 if value["policy"][key] else 0
            self.assert_denied(value)
        for invalid in (None, {}, {"Crypto": "40"}, {"Crypto": float("nan")}, {"Crypto": True}):
            value = snapshot()
            value["policy"]["max_asset_class_pct"] = invalid
            self.assert_denied(value)

    def test_capital_exposure_and_position_nonfinite_or_wrong_types(self):
        for section, key in (
            ("capital", "real_capital"), ("capital", "usable_capital"),
            ("exposure", "total_gross_exposure_usd"), ("exposure", "total_risk_usd"),
        ):
            for invalid in (float("nan"), float("inf"), True, "1000", -1):
                value = snapshot()
                value[section][key] = invalid
                self.assert_denied(value)
        for key in ("notional_usd", "risk_usd", "quantity", "protected_quantity",
                    "stop_distance_pct", "leverage"):
            for invalid in (float("nan"), float("inf"), True, "1", 0, -1):
                value = snapshot()
                value["exposure"]["positions"][0][key] = invalid
                self.assert_denied(value)

    def test_drawdown_position_leverage_and_protective_restrictions(self):
        for key, invalid in (
            ("halt_active", True), ("trading_allowed", False), ("max_position_pct", 3),
            ("position_size_multiplier", 0.5), ("position_size_multiplier", 1.1),
            ("daily_pnl_usd", -50), ("drawdown_pct", 1), ("peak_equity_usd", 1250),
            ("consecutive_losses", 5), ("max_single_asset_pct", 3),
            ("max_total_risk_pct", 0.01), ("max_total_exposure_pct", 3),
            ("max_stop_distance_pct", 1), ("max_asset_class_pct", {"Crypto": 3}),
        ):
            with self.subTest(policy=key):
                value = snapshot()
                value["policy"][key] = invalid
                self.assert_denied(value)
        for key, invalid in (
            ("leverage", 2), ("direction", "short"), ("state", "unknown"),
            ("protective_exit_verified", False), ("broker_acknowledged", False),
            ("reduce_only", False), ("protected_quantity", 0.0001), ("risk_usd", 0.1),
            ("asset_class", "Unknown"),
        ):
            with self.subTest(position=key):
                value = snapshot()
                value["exposure"]["positions"][0][key] = invalid
                self.assert_denied(value)
        value = snapshot()
        value["policy"]["peak_equity_usd"] = 1250
        value["policy"]["drawdown_pct"] = 20
        self.assert_denied(value)

    def test_complete_zero_exposure_is_valid_but_missing_inventory_is_not(self):
        value = snapshot()
        value["exposure"].update(positions=[], total_gross_exposure_usd=0, total_risk_usd=0)
        read, _ = self.provider(value)
        self.assertTrue(read()["verified"])
        del value["exposure"]["positions"]
        self.assert_denied(value)

    def test_limit_equality_matches_existing_governor_and_hard_caps(self):
        for key, limit in (
            ("max_open_positions", 1), ("max_total_risk_pct", 0.1),
            ("max_daily_loss_pct", 5), ("max_consecutive_losses", 5),
        ):
            value = snapshot()
            value["policy"][key] = limit
            if key == "max_daily_loss_pct":
                value["policy"]["daily_pnl_usd"] = -50
            if key == "max_consecutive_losses":
                value["policy"]["consecutive_losses"] = 5
            with self.subTest(denied_equality=key):
                self.assert_denied(value)
        value = snapshot()
        value["policy"].update(
            max_position_pct=4, max_single_asset_pct=4,
            max_total_exposure_pct=4, max_asset_class_pct={"Crypto": 4},
            max_stop_distance_pct=2, max_leverage=1, absolute_max_leverage=1,
        )
        read, _ = self.provider(value)
        self.assertTrue(read()["verified"])

    def test_pending_orders_count_without_netting_and_totals_must_match(self):
        value = snapshot()
        pending = copy.deepcopy(value["exposure"]["positions"][0])
        pending.update(position_id="pending-2", state="pending")
        value["exposure"]["positions"].append(pending)
        self.assert_denied(value)
        value["exposure"].update(total_gross_exposure_usd=80, total_risk_usd=2)
        read, _ = self.provider(value)
        self.assertTrue(read()["verified"])
        value["policy"]["max_open_positions"] = 1
        self.assert_denied(value)
        value["policy"]["max_open_positions"] = 12
        value["exposure"]["positions"][1]["position_id"] = "position-1"
        self.assert_denied(value)

    def test_source_exceptions_are_sanitized(self):
        read, source = self.provider()
        source.read_snapshot = Mock(side_effect=RuntimeError("sensitive source payload"))
        with self.assertRaisesRegex(KrakenRiskEvidenceDenied, "^risk_source_read_failed$") as caught:
            read()
        self.assertIsNone(caught.exception.__cause__)
        read, source = self.provider()
        source.read_snapshot = Mock(side_effect=[snapshot(), RuntimeError("private account details")])
        with self.assertRaisesRegex(KrakenRiskEvidenceDenied, "^risk_source_read_failed$"):
            read()

    def test_raw_global_reports_are_not_account_risk_snapshots(self):
        for value in (
            {"halt_active": False, "open_positions": 0, "total_risk_usd": 0},
            {"position_count": 0, "positions": [], "total_gross_exposure_usd": 0,
             "timestamp": datetime.fromtimestamp(NOW, timezone.utc).isoformat()},
            {"real_capital": 1000, "broker_balances": {"kraken": 1000}, "is_fresh": True},
        ):
            with self.subTest(value=value):
                self.assert_denied(value)

    def test_concurrent_account_key_policy_exposure_and_revision_changes(self):
        for mutate in (
            lambda value: value.update(account="user:other:kraken"),
            lambda value: value.update(api_key_sha256="b" * 64),
            lambda value: value.update(revision=8),
            lambda value: value["policy"].update(revision=8),
            lambda value: value["policy"].update(max_open_positions=13),
            lambda value: value["capital"].update(observed_at_epoch=NOW - 9),
            lambda value: value["exposure"].update(revision=8),
        ):
            read, source = self.provider()
            source.after_first = mutate
            with self.subTest(mutate=mutate), self.assertRaises(KrakenRiskEvidenceDenied):
                read()

    def test_bindings_are_copied_not_mutable_trust_inputs(self):
        bindings = dict(BINDINGS)
        read, _ = self.provider(reviewed_record_source_ids=bindings)
        bindings["policy"] = "attacker"
        self.assertTrue(read()["verified"])

    def capital_authority(self):
        """Fake exactly the existing public CapitalAuthority read interface."""
        authority = Mock()
        authority.is_hydrated = True
        authority.is_registered.return_value = True
        authority.is_fresh.return_value = True
        authority.is_brokers_complete.return_value = True
        authority.get_raw_per_broker.return_value = 1000.0
        authority.get_per_broker.return_value = 900.0
        authority.get_snapshot.return_value = {
            "last_updated": datetime.fromtimestamp(NOW - 10, timezone.utc).isoformat(),
            "broker_balances": {"reviewed-kraken-account": 1000.0, "other-account": 5000.0},
        }
        return authority

    def test_existing_capital_read_api_checks_exact_registered_account_only(self):
        authority = self.capital_authority()
        read, _ = self.provider(
            capital_authority=authority, reviewed_capital_broker_id="reviewed-kraken-account",
        )
        self.assertTrue(read()["verified"])
        authority.get_raw_per_broker.assert_called_with("reviewed-kraken-account")
        authority.is_fresh.assert_called_with(ttl_s=60.0)
        self.assertNotIn("refresh", [call[0] for call in authority.mock_calls])
        self.assertNotIn("get_real_capital", [call[0] for call in authority.mock_calls])
        authority.get_raw_per_broker.return_value = 6000.0
        with self.assertRaises(KrakenRiskEvidenceDenied):
            read()

    def test_existing_capital_registry_age_also_bounds_output_lifetime(self):
        authority = self.capital_authority()
        authority.get_snapshot.return_value["last_updated"] = datetime.fromtimestamp(
            NOW - 59, timezone.utc,
        ).isoformat()
        read, _ = self.provider(
            capital_authority=authority, reviewed_capital_broker_id="reviewed-kraken-account",
        )
        row = read()
        self.assertEqual(row["observed_at_epoch"], NOW - 59)
        self.assertEqual(row["expires_at_epoch"], NOW + 1)

    def test_capital_registry_failures_and_concurrent_change(self):
        for key in ("is_registered", "is_fresh", "is_brokers_complete"):
            authority = self.capital_authority()
            getattr(authority, key).return_value = False
            read, _ = self.provider(
                capital_authority=authority, reviewed_capital_broker_id="reviewed-kraken-account",
            )
            with self.subTest(key=key), self.assertRaises(KrakenRiskEvidenceDenied):
                read()
        authority = self.capital_authority()
        authority.is_hydrated = False
        read, _ = self.provider(
            capital_authority=authority, reviewed_capital_broker_id="reviewed-kraken-account",
        )
        with self.assertRaises(KrakenRiskEvidenceDenied):
            read()
        authority = self.capital_authority()
        authority.get_per_broker.side_effect = [900.0, 899.0]
        read, _ = self.provider(
            capital_authority=authority, reviewed_capital_broker_id="reviewed-kraken-account",
        )
        with self.assertRaises(KrakenRiskEvidenceDenied):
            read()

    def test_capital_public_read_api_must_not_hide_stale_or_missing_account_data(self):
        for observed, balances in (
            (NOW - 61, {"reviewed-kraken-account": 1000}),
            (NOW + 1, {"reviewed-kraken-account": 1000}),
            (NOW - 10, {"other-account": 1000}),
        ):
            authority = self.capital_authority()
            authority.get_snapshot.return_value = {
                "last_updated": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
                "broker_balances": balances,
            }
            read, _ = self.provider(
                capital_authority=authority, reviewed_capital_broker_id="reviewed-kraken-account",
            )
            with self.subTest(observed=observed, balances=balances):
                with self.assertRaises(KrakenRiskEvidenceDenied):
                    read()
        with self.assertRaises(KrakenRiskEvidenceDenied):
            self.provider(capital_authority=self.capital_authority())

    def test_optional_runtime_read_exceptions_fail_closed(self):
        governor = Mock()
        governor.get_status.side_effect = RuntimeError("private runtime status")
        read, _ = self.provider(global_governor=governor)
        with self.assertRaisesRegex(KrakenRiskEvidenceDenied, "^risk_source_read_failed$"):
            read()
        authority = self.capital_authority()
        authority.get_snapshot.side_effect = RuntimeError("private capital status")
        read, _ = self.provider(
            capital_authority=authority, reviewed_capital_broker_id="reviewed-kraken-account",
        )
        with self.assertRaisesRegex(KrakenRiskEvidenceDenied, "^risk_source_read_failed$"):
            read()

    def test_global_governor_health_is_only_an_additional_veto(self):
        governor = Mock()
        governor.get_status.return_value = {"halt_active": False}
        read, _ = self.provider(global_governor=governor)
        self.assertTrue(read()["verified"])
        governor.approve_entry.assert_not_called()
        governor.get_status.return_value = {"halt_active": True}
        with self.assertRaises(KrakenRiskEvidenceDenied):
            read()
        governor.get_status.return_value = {"halt_active": False}
        bad = snapshot()
        del bad["exposure"]
        read, _ = self.provider(bad, global_governor=governor)
        with self.assertRaises(KrakenRiskEvidenceDenied):
            read()
        governor.get_status.side_effect = [{"halt_active": False, "revision": 1},
                                            {"halt_active": False, "revision": 2}]
        read, _ = self.provider(global_governor=governor)
        with self.assertRaises(KrakenRiskEvidenceDenied):
            read()


if __name__ == "__main__":
    unittest.main()
